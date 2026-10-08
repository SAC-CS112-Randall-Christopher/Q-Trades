"""Finite inbox authority and financial fences; synthetic software evidence only."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from test_paper_engine import START, frame, study
from test_paper_store import pg_store as pg_store
from test_peft_development import declared as declared
from test_peft_finite_pilot import finite as finite
from test_peft_finite_pilot import scope as transport_scope
from test_peft_paper_pilot import pilot as pilot

from trading.autonomous_lab import AutonomousLab, InputWait
from trading.autonomous_spec import LabProposal, RuleSpec
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.lab_proposals import LabProposals
from trading.paper_engine import PaperEngine


@pytest.fixture
def inbox(tmp_path):
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    owner = LabProposals(registry)
    try:
        yield owner
    finally:
        registry.close()


def intent(owner, request="finite-proposal-001"):
    issued = owner.bundle({"evidence": {}, "basis": "synthetic finite-authority fixture"})
    proposal = LabProposal(
        request_id=request,
        policy_id="finite-policy-001",
        source="external",
        kind="independent",
        strategy=RuleSpec(
            version="reviewed-lab-rules-v4", family="breakout-retest-v1", holding_horizon="medium"
        ),
        reference=RuleSpec(
            version="reviewed-lab-rules-v4", family="cost-breakout-v1", holding_horizon="medium"
        ),
        mechanism="Synthetic inbox identity fixture; no strategy-quality claim",
        question="Does the exact existing proposal retain its finite authorization?",
        evidence_bundle_sha256=issued["sha256"],
    )
    fence = {
        "grant_id": "finite-grant-001",
        "grant_sha": "a" * 64,
        "profile_sha": "b" * 64,
        "contract_version": "reviewed-rule-role-v8",
        "contract_sha": "c" * 64,
        "question_policy": "pattern-question-selection-v1",
        "finite_test_sha": "d" * 64,
        "not_before": START - 1,
        "expires_at": START + 30 * 3600,
        "root_task": "role-" + "1" * 32,
        "task": "role-" + "1" * 32,
        "proposal_id": proposal.request_id,
        "proposal_sha": fingerprint(proposal.model_dump()),
    }
    return proposal, fence


def permit(owner, expected):
    # The real worker verifies immutable root/task identity; this fixture tests
    # only the inbox's transactional claim/recovery seam with an explicit stub.
    def validate(scope, proposal):
        assert owner.registry.db.in_transaction
        if scope != expected or fingerprint(proposal.model_dump()) != scope["proposal_sha"]:
            raise ValueError("Different exact claimed authority")

    owner.finite_validator = validate


def test_one_claim_exact_ack_recovery_without_fresh_authority(inbox):
    proposal, fence = intent(inbox)
    permit(inbox, fence)
    original = inbox.submit(proposal, {"basis": "synthetic"}, _finite_scope=fence)
    assert inbox.finite_scope(proposal) == fence
    before = inbox.registry.db.execute("SELECT count(*) FROM experiment_events").fetchone()[0]

    def expired(*args):
        raise ValueError("Expired; no new effect")

    inbox.finite_validator = expired
    assert inbox.submit(proposal, {"changed": True}, _finite_scope=fence) == original
    assert (
        inbox.registry.db.execute("SELECT count(*) FROM experiment_events").fetchone()[0] == before
    )
    assert inbox.registry.db.execute("SELECT count(*) FROM lab_finite_proposals").fetchone()[0] == 1


def test_second_proposal_same_grant_refused_even_with_new_intent(inbox):
    first, scope = intent(inbox)
    permit(inbox, scope)
    original = inbox.submit(first, {}, _finite_scope=scope)
    second, changed = intent(inbox, "finite-proposal-002")
    permit(inbox, changed)
    with pytest.raises(ValueError, match="one proposal"):
        inbox.submit(second, {}, _finite_scope=changed)
    assert inbox.get(first.request_id) == original
    with pytest.raises(ValueError, match="Unknown"):
        inbox.get(second.request_id)


def test_concurrent_distinct_intents_claim_only_one_proposal(inbox):
    pairs = [intent(inbox, f"finite-proposal-{i:03}") for i in range(4)]
    expected = {p.request_id: s for p, s in pairs}
    inbox.finite_validator = lambda scope, p: (
        None if scope == expected[p.request_id] else (_ for _ in ()).throw(ValueError("identity"))
    )

    def submit(pair):
        proposal, scope = pair
        try:
            inbox.submit(proposal, {}, _finite_scope=scope)
        except ValueError as exc:
            assert "one proposal" in str(exc)
            return False
        return True

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(submit, pairs)) == 1
    assert inbox.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 1
    assert inbox.registry.db.execute("SELECT count(*) FROM lab_finite_proposals").fetchone()[0] == 1


def test_failed_event_rolls_back_inbox_and_authority_claim(inbox, monkeypatch):
    proposal, scope = intent(inbox)
    permit(inbox, scope)

    def fail(*args):
        raise RuntimeError("Synthetic publication failure")

    monkeypatch.setattr(inbox.registry, "event", fail)
    with pytest.raises(RuntimeError, match="publication failure"):
        inbox.submit(proposal, {}, _finite_scope=scope)
    assert inbox.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0
    assert inbox.registry.db.execute("SELECT count(*) FROM lab_finite_proposals").fetchone()[0] == 0


def test_unscoped_old_proposal_cannot_be_adopted_or_rewritten(inbox):
    proposal, fence = intent(inbox)
    original = inbox.submit(proposal, {})
    permit(inbox, fence)
    with pytest.raises(ValueError, match="different finite authority"):
        inbox.submit(proposal, {}, _finite_scope=fence)
    assert inbox.get(proposal.request_id) == original
    assert inbox.finite_scope(proposal) is None


@pytest.mark.parametrize("unavailable", [True, False])
def test_unavailable_or_expired_worker_authority_cannot_publish(inbox, unavailable):
    proposal, fence = intent(inbox)
    if not unavailable:
        inbox.finite_validator = lambda *args: (_ for _ in ()).throw(ValueError("Expired"))
    with pytest.raises(ValueError):
        inbox.submit(proposal, {}, _finite_scope=fence)
    assert inbox.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0
    assert inbox.registry.db.execute("SELECT count(*) FROM lab_finite_proposals").fetchone()[0] == 0


def test_claim_is_immutable_and_exact_body_recovery_checked(inbox):
    proposal, fence = intent(inbox)
    permit(inbox, fence)
    inbox.submit(proposal, {}, _finite_scope=fence)
    for sql in (
        "UPDATE lab_finite_proposals SET sha256='different'",
        "DELETE FROM lab_finite_proposals",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            inbox.registry.db.execute(sql)
    changed = proposal.model_copy(update={"question": "A different question cannot reuse intent"})
    with pytest.raises(ValueError, match="differs"):
        inbox.finite_scope(changed)


def test_dispatch_guard_has_no_registry_transaction_and_preserves_old_path(inbox):
    lab = AutonomousLab(inbox.registry, SimpleNamespace(), lambda: True)
    proposal, fence = intent(lab.inbox)
    with lab._finite_dispatch(proposal) as guard:
        assert guard is None
    permit(lab.inbox, fence)
    lab.inbox.submit(proposal, {}, _finite_scope=fence)
    events = []

    @contextmanager
    def operation(scope):
        assert scope == fence and not inbox.registry.db.in_transaction
        events.append("enter")

        def guard():
            assert not inbox.registry.db.in_transaction
            events.append("check")

        yield guard
        events.append("exit")

    lab.finite_transport = SimpleNamespace(finite_operation=operation)
    with lab._finite_dispatch(proposal) as guard:
        assert guard is not None
        guard()
    assert events == ["enter", "check", "exit"]
    lab.finite_transport = None
    with pytest.raises(InputWait, match="unavailable"):
        with lab._finite_dispatch(proposal):
            pytest.fail("Unowned finite dispatch")


@pytest.mark.parametrize("checkpoint", [1, 2, 3])
def test_actual_transaction_expiry_rolls_back_state_journal_and_projection(pg_store, checkpoint):
    store, _ = pg_store
    state = copy.deepcopy(store.read())
    records = copy.deepcopy(store.export(0, 1000)["records"])
    before = store.reconcile()
    calls = 0

    def expiry():
        nonlocal calls
        calls += 1
        if calls == checkpoint:
            raise InputWait("Synthetic finite deadline closed")

    with pytest.raises(InputWait, match="deadline closed"):
        store.transact(
            START + 1,
            lambda engine: engine.tick({"BTCUSD": frame(START + 1)}, study()),
            authorize=expiry,
        )
    assert calls == checkpoint and store.last_commit_receipt is None
    assert store.read() == state and store.export(0, 1000)["records"] == records
    assert store.reconcile() == before and before["balanced"]
    store.transact(START + 2, lambda engine: engine.tick({"BTCUSD": frame(START + 2)}, study()))
    assert store.reconcile()["balanced"]


def actual_scoped_lab(store, directory, finite):
    from test_autonomous_lab import make_lab

    lab = make_lab(store, directory, horizon_seconds=86400, holding_horizons=["medium"])
    model, grant, _, _, _, clock = finite
    clock[0] = START
    grant["finite_test"].update(not_before=START - 1, expires_at=START + 100)
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    proposal, _ = intent(lab.inbox)
    proposal = proposal.model_copy(
        update={"policy_id": lab.paper.state["autonomous_lab"]["policy"]["request_id"]}
    )
    fence = transport_scope(model) | {
        "root_task": "role-" + "1" * 32,
        "task": "role-" + "1" * 32,
        "proposal_id": proposal.request_id,
        "proposal_sha": fingerprint(proposal.model_dump()),
    }
    permit(lab.inbox, fence)
    # Exact claimed-worker authority is an explicit stub here; worker/transport
    # binding is separately tested. Actual financial/inbox owners are exercised.
    lab.inbox.submit(proposal, lab.evaluate(proposal, START), _finite_scope=fence)
    lab.finite_transport = model
    return lab, proposal, clock


@pytest.mark.parametrize("closed", ["expired", "paused"])
def test_actual_closed_queue_cannot_reserve_or_fund(pg_store, tmp_path, finite, closed):
    from test_autonomous_lab import tick_lab

    store, _ = pg_store
    lab, proposal, clock = actual_scoped_lab(store, tmp_path / "lab", finite)
    try:
        original = copy.deepcopy(store.read()["accounts"])
        if closed == "expired":
            clock[0] = START + 101
        else:
            finite[0].set_enabled(False)
        tick_lab(lab, START + 101)
        assert not lab.step(START + 101)
        retained = lab.inbox.get(proposal.request_id)
        assert retained["status"] == "blocked" and "Finite" in retained["reason"]
        assert not lab.paper.state["autonomous_lab"]["trials"]
        for name, account in original.items():
            assert lab.paper.state["accounts"][name]["funding"] == account["funding"]
        assert store.reconcile()["balanced"]
    finally:
        lab.registry.close()


def test_actual_lost_reserve_ack_recovers_after_expiry_without_new_funding(
    pg_store, tmp_path, finite
):
    from test_autonomous_lab import tick_lab

    store, _ = pg_store
    lab, proposal, clock = actual_scoped_lab(store, tmp_path / "lab", finite)
    try:
        with store.transaction_lock:
            with lab._finite_dispatch(proposal) as guard:
                assert guard is not None
                receipt = store.lab_reserve(START, proposal, authorize=guard)
        assert lab.inbox.get(proposal.request_id)["status"] == "evaluated"
        prefix = copy.deepcopy(store.export(0, 1000)["records"])
        clock[0] = START + 101
        tick_lab(lab, START + 101)
        assert lab.step(START + 101)
        assert lab.inbox.get(proposal.request_id)["trial_id"] == receipt["trial_id"]
        assert lab.inbox.get(proposal.request_id)["status"] == "reserved"
        tick_lab(lab, START + 103)
        assert not lab.step(START + 103)
        trial = lab.paper.state["autonomous_lab"]["trials"][receipt["trial_id"]]
        assert trial["status"] == "reserved"
        assert trial["candidate"] not in lab.paper.state["accounts"]
        events = store.export(0, 1000)["records"]
        assert events[: len(prefix)] == prefix
        assert sum(e["kind"] == "lab_trial_reserved" for e in events) == 1
        assert not any(e["kind"] == "lab_account_funded" for e in events)
        assert store.reconcile()["balanced"]
    finally:
        lab.registry.close()


def test_actual_existing_orders_keep_matched_decisions_after_research_expiry(
    pg_store, tmp_path, finite
):
    store, _ = pg_store
    lab, proposal, clock = actual_scoped_lab(store, tmp_path / "lab", finite)
    try:
        clock[0] = START + 101
        with pytest.raises(InputWait):
            with lab._finite_dispatch(proposal):
                pytest.fail("Expired research permission")
        baseline = copy.deepcopy(store.read())
        baseline.pop("revision", None)
        observed = []
        for offset, price, sequence in [(1, "100", 1), (2, "100", 2), (6, "98", 3), (8, "98", 4)]:
            now = START + offset
            frames = {"BTCUSD": frame(now, price, sequence)}
            inputs = study()
            control = PaperEngine(copy.deepcopy(baseline), now)
            control.tick(frames, inputs)
            control.assert_invariants()
            store.transact(
                now, lambda engine, frames=frames, inputs=inputs: engine.tick(frames, inputs)
            )
            actual = copy.deepcopy(store.read())
            actual.pop("revision", None)
            assert actual == control.state
            baseline = copy.deepcopy(control.state)
            account = actual["accounts"]["primary"]
            observed.append(
                (bool(account["pending"]), bool(account["positions"]), account["closed"])
            )
            assert store.reconcile()["balanced"]
        assert any(pending for pending, _, _ in observed)
        assert any(position for _, position, _ in observed)
        assert observed[-1][2] == 1
        assert not any(e["kind"] == "lab_account_funded" for e in store.export(0, 1000)["records"])
    finally:
        lab.registry.close()


def test_actual_lost_funding_ack_recovers_after_expiry_without_refunding(
    pg_store, tmp_path, finite
):
    from test_autonomous_lab import tick_lab

    from trading import autonomous_finance as finance

    store, _ = pg_store
    lab, proposal, clock = actual_scoped_lab(store, tmp_path / "lab", finite)
    try:
        with store.transaction_lock:
            with lab._finite_dispatch(proposal) as guard:
                assert guard is not None
                receipt = store.lab_reserve(START, proposal, authorize=guard)
        lab.inbox.update(proposal.request_id, "reserved", receipt["trial_id"])
        with store.transaction_lock:
            with lab._finite_dispatch(proposal) as guard:
                lab.paper.state = store.transact(
                    START + 1,
                    lambda engine: finance.fund(engine, receipt["trial_id"]),
                    authorize=guard,
                )
        prefix = copy.deepcopy(store.export(0, 1000)["records"])
        funding = {name: account["funding"] for name, account in store.read()["accounts"].items()}
        assert lab.inbox.get(proposal.request_id)["status"] == "reserved"
        clock[0] = START + 101
        tick_lab(lab, START + 101)
        assert lab.step(START + 101)
        assert lab.inbox.get(proposal.request_id)["status"] == "funded"
        assert {
            name: account["funding"] for name, account in store.read()["accounts"].items()
        } == funding
        events = store.export(0, 1000)["records"]
        assert events[: len(prefix)] == prefix
        assert sum(e["kind"] == "lab_account_funded" for e in events) == 2
        assert store.reconcile()["balanced"]
    finally:
        lab.registry.close()
