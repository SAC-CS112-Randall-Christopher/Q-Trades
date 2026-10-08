"""Finite source QA without a model; the explicit PG node needs its owned fixture."""

import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import RLock

import pytest
import test_pattern_role_worker as pattern_worker_tests
from test_autonomous_lab import bars_at
from test_daily_pattern_analyzer import advance
from test_paper_store import pg_store as pg_store
from test_pattern_comparisons import command
from test_pattern_role_worker import PatternTransport, build_pattern_worker_fixture

from trading.autonomous_lab import InputWait
from trading.autonomous_spec import LabProposal
from trading.experiment_registry import fingerprint
from trading.finite_role_test import active, finite_scope
from trading.role_worker import Question, RoleWorker


class FiniteTransport(PatternTransport):
    """Model/financial authority stub; actual Peft fencing is verified separately."""

    def __init__(self, worker, selection, now, clock):
        super().__init__()
        self.scope = {
            **self.authority,
            "finite_test": {
                "not_before": now - 1,
                "expires_at": now + 30 * 3600 - 1,
                "max_requests": 3,
                "selection": selection.model_dump(),
                "finding_sha256": worker.pattern_comparisons.describe(selection)["finding_sha256"],
            },
        }
        self.before_claim = None
        self.after_answer = None
        self.reservations = []
        self.finite_request_verifier = worker.validate_finite_request
        self.clock = clock
        self.policy_lock = RLock()

    def finite_test(self):
        return copy.deepcopy(self.scope)

    def infer(self, role, packet, profile):
        raise ValueError("Finite fixture requires reserved dispatch")

    @contextmanager
    def finite_operation(self, fence):
        with self.policy_lock:

            def guard():
                scope = finite_scope(self.finite_test())
                active(scope, self.clock())
                expected = {key: value for key, value in scope.items() if key != "finite_test"}
                expected.update(
                    finite_test_sha=fingerprint(scope["finite_test"]),
                    not_before=scope["finite_test"]["not_before"],
                    expires_at=scope["finite_test"]["expires_at"],
                )
                if any(fence.get(key) != value for key, value in expected.items()):
                    raise ValueError("Disposable finite authority differs")

            guard()
            yield guard

    def infer_reserved(self, role, packet, profile, reservation):
        self.reservations.append(copy.deepcopy(reservation))
        self.finite_request_verifier(role, packet, profile, reservation)
        if self.before_claim:
            self.before_claim()
        self.finite_request_verifier(role, packet, profile, reservation, claim=True)
        self.finite_request_verifier(role, packet, profile, reservation)
        answer = super().infer(role, packet, profile)
        if self.after_answer:
            self.after_answer()
        return answer


@pytest.fixture
def finite(tmp_path, monkeypatch):
    f, worker, selection = build_pattern_worker_fixture(tmp_path, monkeypatch)
    transport = FiniteTransport(worker, selection, f.now, lambda: f.now)
    worker.transport = transport
    worker.controller.finite_transport = transport
    worker.controller.inbox.finite_validator = worker.validate_finite_proposal
    try:
        yield f, worker, selection
    finally:
        f.close()


def select(f, worker):
    assert worker.select_fresh_question(f.now) == 1, worker.question_selection_status()
    identity = worker.registry.db.execute("SELECT id FROM role_tasks").fetchone()[0]
    return worker.get(identity)


def own(f, worker, saved):
    worker.registry.db.execute(
        "UPDATE role_tasks SET owner=?,lease_until=? WHERE id=?",
        (worker.owner, f.now + 630, saved["id"]),
    )
    saved["_claimed_owner"] = worker.owner


def attempts(worker):
    return [dict(row) for row in worker.registry.db.execute("SELECT * FROM role_attempts")]


def test_real_native_one_root_is_immutable_and_manual_requests_refuse(finite):
    f, worker, selection = finite
    original = copy.deepcopy(f.paper.state)
    saved = select(f, worker)
    binding = saved["context"]["finite_test"]
    assert binding["root_task"] == saved["id"]
    assert binding["finite_test"]["selection"] == selection.model_dump()
    assert worker.finite.binding(saved) == binding
    with pytest.raises(InputWait, match="manual"):
        worker.enqueue(Question(question="An independent manual investigation", horizon="medium"))
    assert worker.select_fresh_question(f.now) == 0
    assert worker.finite.count(binding) == 0 and not attempts(worker)
    assert f.paper.state == original and worker.transport.calls == []
    for table in ("role_finite_tests", "role_finite_tasks"):
        with pytest.raises(Exception, match="immutable"):
            worker.registry.db.execute("UPDATE " + table + " SET body='{}'")


def test_concurrent_selection_and_same_id_replacement_never_claim_second_root(finite):
    f, worker, _ = finite
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: worker.select_fresh_question(f.now), range(4)))
    assert sum(results) == 1
    assert worker.registry.db.execute("SELECT count(*) FROM role_finite_tests").fetchone()[0] == 1
    worker.transport.scope["grant_sha"] = "d" * 64
    worker.transport.authority["grant_sha"] = "d" * 64
    assert worker.select_fresh_question(f.now) == 0
    assert worker.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0] == 1
    assert worker.transport.calls == []


def test_actual_reserved_callback_is_once_only_and_answer_recovery_spends_no_call(finite):
    f, worker, _ = finite
    saved = select(f, worker)
    own(f, worker, saved)
    first = asyncio.run(worker._answer(saved))
    row = attempts(worker)[0]
    role, packet = worker._packet(saved)
    profile = json.loads(row["profile"])
    reservation = worker.transport.reservations[0]
    assert row["dispatch_started"] == f.now
    assert worker.finite.count(saved["context"]["finite_test"]) == 1
    with pytest.raises(ValueError, match="reservation"):
        worker.validate_finite_request(role, packet, profile, reservation, claim=True)
    assert asyncio.run(worker._answer(saved)) == first
    assert len(worker.transport.calls) == 1 and len(attempts(worker)) == 1


def test_lifetime_budget_counts_hot_failed_unknown_and_cold_charges(finite):
    f, worker, _ = finite
    saved = select(f, worker)
    binding = saved["context"]["finite_test"]
    with worker.registry.transaction():
        for stage, status in (("review", "failed"), ("followup", "running")):
            worker.registry.db.execute(
                "INSERT INTO role_attempts(task,stage,attempt,started,status,profile,packet,"
                "wall_reserved,tokens_reserved) VALUES(?,?,1,?,?, '{}','{}',1,1)",
                (saved["id"], stage, f.now - 7200, status),
            )
        worker.registry.db.execute(
            "INSERT INTO role_archive_attempts(task,stage,attempt,started,wall_reserved,"
            "tokens_reserved,status) VALUES(?,'old-stage',1,?,1,1,'answered')",
            (saved["id"], f.now - 7200),
        )
    own(f, worker, saved)
    assert worker.finite.count(binding) == 3
    with pytest.raises(InputWait, match="lifetime"):
        asyncio.run(worker._answer(saved))
    assert worker.transport.calls == [] and worker.finite.count(binding) == 3


def test_lost_lease_before_dispatch_is_charged_without_callback(finite):
    f, worker, _ = finite
    saved = select(f, worker)
    own(f, worker, saved)
    worker.transport.before_claim = lambda: worker.registry.db.execute(
        "UPDATE role_tasks SET owner=NULL,lease_until=NULL WHERE id=?", (saved["id"],)
    )
    with pytest.raises(ValueError, match="ownership"):
        asyncio.run(worker._answer(saved))
    assert len(attempts(worker)) == 1 and attempts(worker)[0]["status"] == "failed"
    assert attempts(worker)[0]["dispatch_started"] is None and worker.transport.calls == []
    assert worker.finite.count(saved["context"]["finite_test"]) == 1


def test_expiry_before_reservation_and_after_answer_preserves_raw_result(finite, monkeypatch):
    f, worker, _ = finite
    worker.transport.scope["finite_test"]["expires_at"] = f.now + 1
    saved = select(f, worker)
    preflight = worker.transport.preflight
    original_time = f.now

    def expire(*args):
        measured = preflight(*args)
        f.now = worker.transport.scope["finite_test"]["expires_at"]
        return measured

    monkeypatch.setattr(worker.transport, "preflight", expire)
    own(f, worker, saved)
    with pytest.raises(InputWait, match="authorization window"):
        asyncio.run(worker._answer(saved))
    assert not attempts(worker) and not worker.transport.calls
    f.now = original_time
    monkeypatch.setattr(worker.transport, "preflight", preflight)
    worker.registry.db.execute(
        "UPDATE role_tasks SET owner=NULL,lease_until=NULL WHERE id=?", (saved["id"],)
    )
    worker.transport.after_answer = lambda: setattr(
        f, "now", worker.transport.scope["finite_test"]["expires_at"]
    )
    assert asyncio.run(worker.step(f.now)) is False
    retained = worker.get(saved["id"])
    assert retained["stage"] == "idea" and retained["result"] is None
    assert retained["attempts"][0]["status"] == "answered"
    assert json.loads(retained["attempts"][0]["response"])["answer"]["action"] == "no_change"
    assert len(worker.transport.calls) == 1


def test_unmarked_task_is_not_claimed_under_finite_grant(finite):
    f, worker, _ = finite
    saved = select(f, worker)
    context = copy.deepcopy(saved["context"])
    context.pop("finite_test")
    context.pop("selection_authority")
    worker.registry.db.execute(
        "INSERT INTO role_tasks(id,created,updated,stage,status,context) "
        "VALUES('unmarked-task',?,?,'idea','queued',?)",
        (f.now, f.now - 1, json.dumps(context)),
    )
    assert asyncio.run(worker.step(f.now))
    unmarked = worker.registry.db.execute(
        "SELECT owner,lease_until,status FROM role_tasks WHERE id='unmarked-task'"
    ).fetchone()
    assert tuple(unmarked) == (None, None, "queued")
    assert all(a["task"] == saved["id"] for a in attempts(worker))


def test_real_data_resumption_keeps_original_root_and_archive_charges(finite, monkeypatch):
    f, worker, _ = finite
    worker.transport.action = "request_data"
    original = select(f, worker)
    assert asyncio.run(worker.step(f.now))
    waiting = worker.get(original["id"])
    first_answer = copy.deepcopy(waiting["result"])
    advance(f, 120)
    f.paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
    assert worker.resume_sources(f.now) == 1
    child_summary = next(t for t in worker.page()["tasks"] if t["id"] != original["id"])
    child = worker.get(child_summary["id"])
    assert child["context"]["finite_test"]["root_task"] == original["id"]
    assert asyncio.run(worker.step(f.now))
    assert worker.finite.count(original["context"]["finite_test"]) == 2
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    worker.history.rollover()
    stub = worker.registry.db.execute(
        "SELECT context,archive_reference FROM role_tasks WHERE id=?", (child["id"],)
    ).fetchone()
    assert (
        stub["archive_reference"]
        and json.loads(stub["context"])["finite_test"] == child["context"]["finite_test"]
    )
    assert worker.get(original["id"])["result"] == first_answer
    assert worker.finite.count(original["context"]["finite_test"]) == 2
    worker.history.restore(child["id"])
    restarted = RoleWorker(
        f.registry,
        worker.controller,
        worker.transport,
        f.scanner.storage_owner,
        pattern_comparisons=worker.pattern_comparisons,
    )
    assert restarted.finite.count(original["context"]["finite_test"]) == 2
    assert restarted.select_fresh_question(f.now) == 0


def test_preparation_expiry_rolls_back_publication_but_original_get_bypasses_guard(
    finite, monkeypatch
):
    f, worker, selection = finite
    bridge = worker.pattern_comparisons
    cmd = command(bridge, selection, "finite-preparation-0001")
    evaluate = bridge._evaluation

    def expire(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        f.now = worker.transport.scope["finite_test"]["expires_at"]
        return result

    monkeypatch.setattr(bridge, "_evaluation", expire)
    windows = [tuple(r) for r in f.registry.db.execute("SELECT * FROM evidence_windows")]
    with pytest.raises(InputWait, match="authorization window"):
        bridge.prepare(cmd, f.now, admission=worker._finite_current)
    assert bridge.get(cmd.request_id) is None
    assert [tuple(r) for r in f.registry.db.execute("SELECT * FROM evidence_windows")] == windows
    f.now -= 60
    monkeypatch.setattr(bridge, "_evaluation", evaluate)
    saved = bridge.prepare(cmd, f.now, admission=worker._finite_current)
    f.now = worker.transport.scope["finite_test"]["expires_at"]
    assert bridge.prepare(cmd, f.now, admission=worker._finite_current) == saved


def change_authority(worker, monkeypatch, drift):
    if drift == "old_format":
        monkeypatch.setattr(worker.transport, "finite_test", lambda: None)
    elif drift == "new_grant":
        worker.transport.scope["grant_id"] = "replacement-grant-0001"
    else:
        worker.transport.scope["grant_sha"] = "d" * 64


@pytest.mark.parametrize("drift", ("old_format", "new_grant", "same_id_replacement"))
def test_selection_preparation_refuses_captured_authority_drift(finite, monkeypatch, drift):
    f, worker, _ = finite
    bridge = worker.pattern_comparisons
    evaluate = bridge._evaluation
    windows = [tuple(row) for row in f.registry.db.execute("SELECT * FROM evidence_windows")]

    def changed(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        change_authority(worker, monkeypatch, drift)
        return result

    monkeypatch.setattr(bridge, "_evaluation", changed)
    assert worker.select_fresh_question(f.now) == 0
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == 0
    assert (
        f.registry.db.execute("SELECT count(*) FROM pattern_comparison_requests").fetchone()[0] == 0
    )
    assert [
        tuple(row) for row in f.registry.db.execute("SELECT * FROM evidence_windows")
    ] == windows
    assert f.registry.db.execute("SELECT count(*) FROM role_finite_tests").fetchone()[0] == 0
    assert not attempts(worker) and not worker.transport.calls


@pytest.mark.parametrize("drift", ("old_format", "new_grant", "same_id_replacement"))
def test_fresh_input_disclosure_refuses_captured_authority_drift(finite, monkeypatch, drift):
    f, worker, selection = finite
    bridge = worker.pattern_comparisons
    scope = worker.transport.finite_test()
    original = bridge.prepare(command(bridge, selection, "finite-original-0001"), f.now)
    advance(f, 120)
    f.paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
    evaluate = bridge._evaluation
    windows = [tuple(row) for row in f.registry.db.execute("SELECT * FROM evidence_windows")]

    def changed(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        change_authority(worker, monkeypatch, drift)
        return result

    monkeypatch.setattr(bridge, "_evaluation", changed)
    with pytest.raises(InputWait, match="authority changed"):
        worker._pattern_inputs(
            {
                key: original[key]
                for key in ("request_id", "finding_sha256", "issued_bundle_sha256")
            },
            Question(question="Inspect original fixed comparison", horizon="medium"),
            f.paper.state["autonomous_lab"]["policy"],
            f.now,
            finite_authority=scope,
        )
    assert [
        tuple(row) for row in f.registry.db.execute("SELECT * FROM evidence_windows")
    ] == windows
    assert bridge.get(original["request_id"]) == original
    assert not attempts(worker) and not worker.transport.calls


def test_accepted_lost_ack_reconciles_after_expiry_without_submit_or_evaluation(
    finite, monkeypatch
):
    f, worker, _ = finite
    worker.transport.action = "propose_experiment"
    saved = select(f, worker)
    for _ in range(4):
        assert asyncio.run(worker.step(f.now)), worker.get(saved["id"])
        advance(f, 1)
    submitted = worker.get(saved["id"])
    assert submitted["stage"] == "submit"
    proposal = LabProposal.model_validate(submitted["proposal"])
    fence = worker.finite_proposal(submitted, proposal)
    receipt = worker.controller.submit(proposal, f.now, _finite_scope=fence)
    assert worker.controller.inbox.finite_scope(proposal) == fence
    spent = copy.deepcopy(attempts(worker))
    f.now = worker.transport.scope["finite_test"]["expires_at"]
    monkeypatch.setattr(worker.controller, "evaluate", lambda *a: pytest.fail("new evaluation"))
    monkeypatch.setattr(worker.controller, "submit", lambda *a, **k: pytest.fail("new submit"))
    monkeypatch.setattr(worker, "_admitted", lambda: pytest.fail("new admission"))
    assert asyncio.run(worker.step(f.now))
    assert worker.get(saved["id"])["stage"] == "outcome"
    assert worker.get(saved["id"])["result"]["proposal_id"] == receipt["request_id"]
    assert attempts(worker) == spent
    assert len(worker.transport.calls) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_requests", True),
        ("max_requests", 4),
        ("expires_at", float("inf")),
        ("not_before", True),
        ("finding_sha256", "F" * 64),
        ("not_before", 10**400),
    ],
)
def test_strict_finite_scope_rejects_invalid_limits(finite, field, value):
    _, worker, _ = finite
    scope = worker.transport.finite_test()
    scope["finite_test"][field] = value
    with pytest.raises(ValueError):
        finite_scope(scope)


def test_exact_absolute_window_never_restarts(finite):
    f, worker, _ = finite
    scope = worker.transport.finite_test()
    for at in (scope["finite_test"]["not_before"] - 1, scope["finite_test"]["expires_at"]):
        with pytest.raises(ValueError, match="authorization window"):
            active(scope, at)
    assert active(scope, f.now) is None


def test_disposable_financial_fence_rechecks_original_scope_and_expiry(finite):
    f, worker, _ = finite
    scope = worker.transport.finite_test()
    fence = {key: value for key, value in scope.items() if key != "finite_test"}
    fence.update(
        finite_test_sha=fingerprint(scope["finite_test"]),
        not_before=scope["finite_test"]["not_before"],
        expires_at=scope["finite_test"]["expires_at"],
    )
    with worker.transport.finite_operation(fence) as guard:
        guard()
        f.now = scope["finite_test"]["expires_at"]
        with pytest.raises(ValueError, match="authorization window"):
            guard()
    f.now -= 1
    with pytest.raises(ValueError, match="authority differs"):
        with worker.transport.finite_operation({**fence, "grant_sha": "d" * 64}):
            pytest.fail("Wrong authority entered")


def test_actual_disposable_engine_finite_three_request_chain(pg_store, tmp_path, monkeypatch):
    """Reuse the real capture wait, pair/fills/fees/data_blocked path; never start PG here."""
    build = pattern_worker_tests.build_pattern_worker_fixture
    observed = {}

    def finite_build(folder, patch, answer_action="no_change"):
        f, worker, selection = build(folder, patch, answer_action)
        worker.transport = FiniteTransport(worker, selection, f.now, lambda: f.now)
        worker.transport.action = answer_action
        close = f.close

        def verified_close():
            try:
                claims = worker.registry.db.execute("SELECT * FROM role_finite_tests").fetchall()
                scope = worker.finite.prior(worker.transport.finite_test())
                observed.update(
                    claims=len(claims),
                    requests=worker.finite.count(scope) if scope else None,
                    callbacks=len(worker.transport.calls),
                    proposals=worker.registry.db.execute(
                        "SELECT count(*) FROM lab_proposals"
                    ).fetchone()[0],
                    unexpired=scope is not None and f.now < scope["finite_test"]["expires_at"],
                    dispatched=all(a["dispatch_started"] is not None for a in attempts(worker)),
                )
            finally:
                close()

        f.close = verified_close
        return f, worker, selection

    monkeypatch.setattr(pattern_worker_tests, "build_pattern_worker_fixture", finite_build)
    pattern_worker_tests.test_actual_disposable_engine_trial_outcome_and_followup_without_model(
        pg_store, tmp_path, monkeypatch
    )
    assert observed == {
        "claims": 1,
        "requests": 3,
        "callbacks": 3,
        "proposals": 1,
        "unexpired": True,
        "dispatched": True,
    }
