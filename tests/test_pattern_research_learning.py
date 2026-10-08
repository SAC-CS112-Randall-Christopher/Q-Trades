"""Opt-in outcome learning: real native/software owners, synthetic scored outcomes, no model/PG."""

import asyncio
import copy
import hashlib
import json

import pytest
from test_daily_pattern_analyzer import advance
from test_pattern_role_worker import (
    PatternTransport,
    build_pattern_worker_fixture,
    publish_native_event,
    restore_scored_body,
    rows,
    select,
)

from trading.experiment_registry import fingerprint
from trading.lab_role_contract import PATTERN_VERSION, packet_json, prompt, validate
from trading.paper_economics import sample
from trading.paper_engine import account
from trading.peft_role_model import PATTERN_LEARNING_QUESTION_POLICY
from trading.role_evidence import pattern_feature, pattern_followup_outcome, pattern_packet
from trading.role_worker import InputWait, RoleWorker


class LearningTransport(PatternTransport):
    def __init__(self, action="no_change"):
        super().__init__(action)
        self.authority["question_policy"] = PATTERN_LEARNING_QUESTION_POLICY
        self.measured = []
        self.packets = {}

    def preflight(self, role, packet, profile):
        encoded = packet_json(packet)
        system = prompt(role, PATTERN_VERSION)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        self.packets.setdefault(
            digest,
            {
                "role": role,
                "packet": copy.deepcopy(packet),
                "packet_json": encoded,
                "system": system,
                "profile": copy.deepcopy(profile),
                "sizing_options": {"num_ctx": 9000, "num_predict": 1024},
                "packet_sha256": digest,
                "packet_bytes": len(encoded.encode()),
                "system_bytes": len(system.encode()),
                "reserved_total": len(encoded.encode()) + len(system.encode()) + 1536,
                "basis": "Conservative UTF-8 input bytes plus unchanged "
                "1024 output/512 template reserves",
            },
        )
        self.measured.append(
            {
                "role": role,
                "packet_bytes": len(packet_json(packet).encode()),
                "system_bytes": len(prompt(role, PATTERN_VERSION).encode()),
                "reserved_total": len(packet_json(packet).encode())
                + len(prompt(role, PATTERN_VERSION).encode())
                + 1536,
            }
        )
        return super().preflight(role, packet, profile)

    def infer(self, role, packet, profile):
        response = super().infer(role, packet, profile)
        if packet["evidence"].get("e5", {}).get("lesson"):
            response["answer"]["evidence_ids"] = ["e3", "e5"]
        return response


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    f, worker, selection = build_pattern_worker_fixture(tmp_path, monkeypatch)
    worker.transport = LearningTransport("propose_experiment")
    try:
        yield f, worker, selection
    finally:
        if isinstance(worker.transport, LearningTransport):
            (tmp_path / "learning-packets.json").write_text(
                json.dumps(list(worker.transport.packets.values()), indent=2), encoding="utf-8"
            )
        f.close()


def mature(f, worker, *, outcome="data_blocked", record=True):
    """Actual software callbacks/evaluation/inbox, then financial-shaped fixture evidence.

    The outcome is not a funded trial or economic qualification. Existing sample
    serializers retain executable exposure, costs, missing marks and nulls.
    """
    first = select(f, worker)
    for _ in range(5):
        assert asyncio.run(worker.step(f.now)), (
            worker.get(first["id"])["reason"],
            worker.transport.measured,
        )
    first = worker.get(first["id"])
    assert first["stage"] == "outcome" and len(worker.transport.calls) == 2
    proposal = first["proposal"]
    inbox = worker.controller.inbox
    assert inbox.get(proposal["request_id"])["body"] == proposal
    inbox.update(proposal["request_id"], "completed", "financial-shaped-fixture")
    candidate, reference = account("candidate", f.now), account("reference", f.now)
    candidate["fees"], reference["fees"] = "0.12", "0.08"
    reference["valuation_issues"] = {"BTCUSD": "Synthetic unavailable executable mark"}
    end = f.now + 86400
    score = {
        "trial_id": "financial-shaped-fixture",
        "proposal_id": proposal["request_id"],
        "outcome": outcome,
        "reason": "Incomplete evidence is not an economic loss"
        if outcome == "data_blocked"
        else "Observed matched after-cost result is adverse",
        "available_at": end,
        "window_start": f.now,
        "window_end": end,
        "coverage_seconds": 2.0 if outcome == "data_blocked" else 86400.0,
        "net_after_operating_usd": {"candidate": None, "reference": None}
        if outcome == "data_blocked"
        else {"candidate": "-0.40", "reference": "-0.20"},
        "delta_usd": None if outcome == "data_blocked" else "-0.20",
        "passive_usd": None,
        "cash_usd": "0",
        "operating_each_usd": "0.5",
        "candidate_sample": sample(candidate, f.now),
        "reference_sample": sample(reference, f.now),
        "dependence": "Related trials are correlated",
        "qualification": "Exploration only; no promotion",
        "fees_treatment": "Executable equity embeds fees once",
        "additional_unknown": None,
    }
    original_outcome = {"id": 1, "at": end, "body": score}
    assert worker._update(first, "followup", result=first["result"] | {"outcome": original_outcome})
    advance(f, 86400)
    original_record = worker.lessons.record
    if not record:
        # Simulate missing lesson persistence without modifying a permanent row.
        worker.lessons.record = lambda task: "lesson-" + fingerprint(task["result"]["outcome"])[:32]
    try:
        assert asyncio.run(worker.step(f.now)), worker.get(first["id"])["reason"]
    finally:
        worker.lessons.record = original_record
    completed = worker.get(first["id"])
    assert (
        completed["status"] == "done" and completed["result"]["followup"]["action"] == "no_change"
    )
    if record:
        worker.select_followups()
    assert len(worker.transport.calls) == 3
    return completed


def later(f, worker):
    # Disjoint later native recognition/current prefix, not a replay of prior outcome inputs.
    advance(f, 86400 + 600)
    publish_native_event(f)
    assert worker.select_fresh_question(f.now) == 1, worker.question_selection_status()
    latest = max(worker.page()["tasks"], key=lambda row: row["created"])
    return worker.get(latest["id"])


@pytest.mark.parametrize("outcome", ["data_blocked", "rejected"])
def test_two_actual_software_generations_reuse_exact_mature_score_without_second_dispatch(
    fixture, outcome, tmp_path
):
    f, worker, _ = fixture
    original = mature(f, worker, outcome=outcome)
    original_result = copy.deepcopy(original["result"])
    finances = copy.deepcopy(f.paper.state["accounts"])
    proposals = rows(worker, "lab_proposals")
    original_attempts = rows(worker, "role_attempts")
    second = later(f, worker)
    context = second["context"]
    learning = context["pattern_learning"]
    assert learning["state"] == "mature_outcome" and learning["dispatch_available"] is False
    assert (
        context["catalog"] == {} and context["question_selection"]["lesson"] == learning["lesson"]
    )
    assert learning["predecessor_task"] == original["id"]
    assert context["lesson"]["source"] == original_result["outcome"]
    assert context["lesson"]["source_sha256"] == fingerprint(original_result["outcome"])
    role, packet = worker._packet(second)
    assert (
        packet["evidence"]["e3"]["original_event"]
        != worker._packet(original)[1]["evidence"]["e3"]["original_event"]
    )
    assert (
        restore_scored_body(packet["evidence"]["e5"]["outcome"])
        == original_result["outcome"]["body"]
    )
    assert packet["evidence"]["e5"]["outcome"]["source_sha256"] == learning["source_sha256"]
    assert fingerprint(restore_scored_body(packet["evidence"]["e5"]["outcome"])) == fingerprint(
        original_result["outcome"]["body"]
    )
    assert packet["evidence"]["e5"]["support"] == context["lesson"]["support"]
    assert packet["evidence"]["e5"]["cost_policy_sha256"] == fingerprint(context["policy"])
    assert packet["evidence"]["e2"]["evaluation_sha256"] == fingerprint(context["tool_evidence"])
    assert packet["evidence"]["e2"]["current_inputs"] == {
        key: context["fixed_comparison"]["p0"]["current_inputs"][key]
        for key in ("count", "sha256", "cutoff")
    }
    # Matched same-task projection measurement: original full outcome, original
    # numerical snapshot and exact method/lesson identities remain unchanged.
    uncompressed = copy.deepcopy(packet)
    prior, fixed, causal = (
        context["lesson"],
        context["fixed_comparison"]["p0"],
        context["tool_evidence"],
    )
    base = worker._base_packet(second)[1]
    uncompressed["scope"] = base["scope"]
    uncompressed["evidence"]["e0"] = base["evidence"]["e0"]
    uncompressed["evidence"]["e3"] = pattern_packet(context["pattern_comparison"])
    uncompressed["evidence"]["e2"] = {
        "features": {key: pattern_feature(value) for key, value in causal["features"].items()},
        "reference_features": {
            key: pattern_feature(value) for key, value in causal["reference_features"].items()
        },
        "executable_book": {
            key: causal["executable_book"][key]
            for key in ("observed", "bids", "asks")
            if key in causal["executable_book"]
        },
        "request_data_conditions": {
            key: {"kind": value["kind"]} for key, value in context["wait_requirements"].items()
        },
    }
    uncompressed["evidence"]["e5"] = {
        "state": learning["state"],
        "lesson": learning["lesson"],
        "predecessor_task": learning["predecessor_task"],
        "source_task": learning["source_task"],
        "source_sha256": learning["source_sha256"],
        "cutoff": learning["cutoff"],
        "dispatch_available": False,
        "dispatch_reason": learning["dispatch_reason"],
        "outcome": pattern_followup_outcome(prior["source"]),
        "cost_policy": prior["context"]["cost_policy"],
        "data_basis": prior["context"]["data_basis"],
        "unknowns": prior["unknowns"],
        "support": prior["support"],
        "interpretation_scope": prior["interpretation_scope"],
    }
    uncompressed["fixed_comparison"]["p0"].update(
        current_inputs=fixed["current_inputs"],
        detail="Original unchanged controls retained in task context; "
        "prior method is evidence, not a new dispatch capability",
    )
    uncompressed["question"] = (
        "Use the mature original outcome to assess this distinct native event. "
        "Fixed p0 was already used and is not offered again; "
        "retain no_change or a justified typed evidence wait."
    )
    measurements = {}
    for name, measured_packet in (("before", uncompressed), ("after", packet)):
        encoded = packet_json(measured_packet)
        measurements[name] = {
            "packet": measured_packet,
            "packet_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "serialized_bytes": len(encoded.encode()),
            "reserved_total": len(encoded.encode())
            + len(prompt(role, PATTERN_VERSION).encode())
            + 1536,
        }
    assert measurements["before"]["reserved_total"] > 9000
    assert measurements["after"]["reserved_total"] <= 9000
    assert restore_scored_body(uncompressed["evidence"]["e5"]["outcome"]) == restore_scored_body(
        packet["evidence"]["e5"]["outcome"]
    )
    (tmp_path / "matched-projection.json").write_text(
        json.dumps(
            {
                "task": second["id"],
                "context_sha256": fingerprint(context),
                "outcome_sha256": learning["source_sha256"],
                "measurement": measurements,
                "actual_model_or_tokenizer": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert packet["capabilities"] == {}
    assert packet["tool_inventory"]["strategy_family"] == ["breakout-retest-v1", "cost-breakout-v1"]
    assert (
        worker.transport.preflight(role, packet, worker.transport.admit(role))["reserved_total"]
        <= 9000
    )
    assert asyncio.run(worker.step(f.now)), worker.get(second["id"])["reason"]
    completed = worker.get(second["id"])
    assert completed["result"]["action"] == "no_change" and completed["proposal"] is None
    assert len(worker.transport.calls) == 4 and worker.transport.calls[-1][1]["evidence"]["e5"]
    assert rows(worker, "lab_proposals") == proposals and f.paper.state["accounts"] == finances
    assert rows(worker, "role_attempts")[: len(original_attempts)] == original_attempts
    assert worker.get(original["id"])["result"] == original_result
    selection = worker.lessons.get(learning["lesson"]["id"])["selection"]
    assert selection["next_task"] == second["id"] and selection["state"] == "selected"
    assert "unchanged" in selection["reason"] and "refinement" in selection["reason"]
    assert worker.select_fresh_question(f.now + 61) == 0
    assert len(rows(worker, "role_question_selections")) == 2
    bad = copy.deepcopy(completed["result"])
    bad.update(action="propose_experiment", capability="p0")
    with pytest.raises(ValueError):
        validate(role, bad, packet, PATTERN_VERSION)


def test_first_question_and_genuinely_unfunded_no_change_have_explicit_absence(fixture):
    f, worker, _ = fixture
    worker.transport.action = "no_change"
    first = select(f, worker)
    assert first["context"]["lesson"] is None
    assert first["context"]["pattern_learning"]["state"] == "first_question"
    assert asyncio.run(worker.step(f.now))
    second = later(f, worker)
    assert second["context"]["lesson"] is None
    assert second["context"]["pattern_learning"]["state"] == "unfunded_no_change"
    assert set(second["context"]["catalog"]) == {"p0"}
    assert not rows(worker, "lab_proposals")


def test_missing_expected_mature_lesson_refuses_without_model_or_new_root(fixture):
    f, worker, _ = fixture
    first = mature(f, worker, record=False)
    source = first["context"]["question_selection"] | {
        "dispatch_available": False,
        "dispatch_reason": "Used fixed p0",
    }
    with pytest.raises(InputWait, match="lesson"):
        worker._pattern_learning_prior(
            first, [], worker._selection_authority(), first["context"]["policy"], source, f.now
        )
    advance(f, 86400 + 600)
    publish_native_event(f)
    assert worker.select_fresh_question(f.now) == 0
    assert "priority" in worker.question_selection_status()["reason"].lower()
    assert len(rows(worker, "role_tasks")) == 1 and len(worker.transport.calls) == 3


def test_archived_predecessor_restart_exact_lesson_and_duplicate_coalesce(fixture, monkeypatch):
    f, worker, _ = fixture
    first = mature(f, worker)
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    worker.history.rollover()
    assert worker.get(first["id"])["archive_reference"]
    restarted = RoleWorker(
        f.registry,
        worker.controller,
        worker.transport,
        f.scanner.storage_owner,
        pattern_comparisons=worker.pattern_comparisons,
    )
    restarted.enabled, restarted.paper_admission = True, lambda: True
    second = later(f, restarted)
    assert second["context"]["pattern_learning"]["records"][0]["task"] == first["id"]
    assert second["context"]["lesson"]["source"] == first["result"]["outcome"]
    assert restarted.select_fresh_question(f.now + 61) == 0
    assert len(rows(restarted, "role_question_selections")) == 2


def test_third_distinct_event_carries_original_mature_source_across_restart(fixture):
    f, worker, _ = fixture
    original = mature(f, worker)
    second = later(f, worker)
    assert asyncio.run(worker.step(f.now)), worker.get(second["id"])["reason"]
    second = worker.get(second["id"])
    assert second["proposal"] is None and "outcome" not in second["result"]
    restart = RoleWorker(
        f.registry,
        worker.controller,
        worker.transport,
        f.scanner.storage_owner,
        pattern_comparisons=worker.pattern_comparisons,
    )
    restart.enabled, restart.paper_admission = True, lambda: True
    third = later(f, restart)
    binding = third["context"]["pattern_learning"]
    assert binding["predecessor_task"] == second["id"]
    assert binding["source_task"] == original["id"]
    assert binding["lesson"] == second["context"]["pattern_learning"]["lesson"]
    assert third["context"]["lesson"] == second["context"]["lesson"]
    assert asyncio.run(restart.step(f.now)), restart.get(third["id"])["reason"]
    assert len(rows(restart, "lab_proposals")) == 1 and len(worker.transport.calls) == 5
    assert restart.select_fresh_question(f.now + 61) == 0


@pytest.mark.parametrize("tamper", ["self", "unfunded", "hash", "policy"])
def test_inherited_binding_refuses_self_missing_outcome_and_changed_original(fixture, tamper):
    f, worker, _ = fixture
    first = mature(f, worker)
    second = later(f, worker)
    assert asyncio.run(worker.step(f.now))
    second = worker.get(second["id"])
    bad = copy.deepcopy(second)
    binding = bad["context"]["pattern_learning"]
    if tamper in {"self", "unfunded"}:
        binding["source_task"] = second["id"]
        if tamper == "unfunded":
            bad["id"] = "different-unfunded-task"
            bad["context"]["lesson"]["task"] = second["id"]
    elif tamper == "hash":
        binding["source_sha256"] = "f" * 64
    else:
        bad["context"]["selection_authority"]["question_policy"] = "pattern-question-selection-v1"
    source = first["context"]["question_selection"] | {
        "dispatch_available": False,
        "dispatch_reason": "Used fixed p0",
    }
    with pytest.raises(InputWait):
        worker._pattern_learning_prior(
            bad, [], worker._selection_authority(), first["context"]["policy"], source, f.now
        )


def test_prior_unavailable_or_future_source_and_protected_outcome_refuse(fixture):
    f, worker, _ = fixture
    first = mature(f, worker)
    selection = first["context"]["question_selection"]
    records = []
    terminal = worker._pattern_terminal(first["id"], worker._selection_authority(), records=records)
    source = dict(selection, dispatch_available=False, dispatch_reason="Used fixed p0")
    with pytest.raises(InputWait, match="cutoff"):
        worker._pattern_learning_prior(
            terminal,
            records,
            worker._selection_authority(),
            first["context"]["policy"],
            source,
            f.now - 1,
        )
    score = terminal["result"]["outcome"]["body"]
    with f.registry.transaction():
        f.registry.db.execute(
            "INSERT INTO evidence_windows VALUES(?,?,?,'holdout')",
            ("protected-outcome", score["window_start"], score["window_end"]),
        )
    advance(f, 86400 + 600)
    publish_native_event(f)
    assert worker.select_fresh_question(f.now) == 0
    assert "protected" in worker.question_selection_status()["reason"].lower()


@pytest.mark.parametrize(
    "dimension", ["strategy_sha", "reference_sha", "source_basis", "method_source_sha", "cost"]
)
def test_mature_prior_refuses_different_method_cost_reference_or_source_basis(fixture, dimension):
    f, worker, _ = fixture
    first = mature(f, worker)
    policy = copy.deepcopy(first["context"]["policy"])
    source = first["context"]["question_selection"] | {
        "dispatch_available": False,
        "dispatch_reason": "Used fixed p0",
    }
    if dimension == "cost":
        policy["daily_operating_usd"] = "0.1"
    else:
        source[dimension] = "different" if dimension == "source_basis" else "f" * 64
    with pytest.raises(
        InputWait, match="cost policy" if dimension == "cost" else "method/cost/source"
    ):
        worker._pattern_learning_prior(
            first, [], worker._selection_authority(), policy, source, f.now
        )


def test_learning_link_and_question_publication_roll_back_together(fixture, monkeypatch):
    f, worker, _ = fixture
    first = mature(f, worker)
    before = rows(worker, "research_selection")
    advance(f, 86400 + 600)
    publish_native_event(f)
    selected = worker.lessons.selected
    original_inputs = worker._pattern_inputs
    publication = {}

    def capture(*args, **kwargs):
        result = original_inputs(*args, **kwargs)
        for table in ("lesson_access", "evidence_windows"):
            publication[table] = rows(worker, table)
        return result

    def fail(*args, **kwargs):
        selected(*args, **kwargs)
        raise ValueError("Injected atomic lesson link failure")

    monkeypatch.setattr(worker.lessons, "selected", fail)
    monkeypatch.setattr(worker, "_pattern_inputs", capture)
    with pytest.raises(ValueError, match="Injected atomic lesson link failure"):
        worker.select_fresh_question(f.now)
    assert rows(worker, "research_selection") == before
    assert publication
    for table, original in publication.items():
        assert rows(worker, table) == original
    assert len(rows(worker, "role_tasks")) == len(rows(worker, "role_question_selections")) == 1
    assert worker.get(first["id"])["result"]["followup"]["action"] == "no_change"


@pytest.mark.parametrize("change", ["grant", "policy", "lesson", "archive", "used", "protected"])
def test_publication_rechecks_exact_original_authority_source_and_used_catalog(
    fixture, monkeypatch, change
):
    f, worker, _ = fixture
    first = mature(f, worker)
    advance(f, 86400 + 600)
    publish_native_event(f)
    original = worker._pattern_inputs
    access = rows(worker, "lesson_access")

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == "grant":
            old = worker.transport.selection_authority
            monkeypatch.setattr(
                worker.transport, "selection_authority", lambda: old() | {"grant_sha": "c" * 64}
            )
        elif change == "policy":
            f.paper.state["autonomous_lab"]["policy"]["operating_daily_usd"] = "0.51"
        elif change == "lesson":
            # Immutable row cannot be replaced; simulate source loss by owner read refusal.
            old = worker._pattern_learning_body
            monkeypatch.setattr(
                worker,
                "_pattern_learning_body",
                lambda *_a, **_k: (_ for _ in ()).throw(InputWait("Original lesson unavailable")),
            )
            assert old
        elif change == "archive":
            monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
            worker.history.rollover()
        elif change == "used":
            # A changing equivalent-rule observation must not publish an executable catalog.
            monkeypatch.setattr(worker.controller.inbox, "used", lambda _sha: False)
        else:
            score = first["result"]["outcome"]["body"]
            with worker.registry.transaction():
                worker.registry.db.execute(
                    "INSERT INTO evidence_windows VALUES(?,?,?,'holdout')",
                    (
                        "new-protected-before-publication",
                        score["window_start"],
                        score["available_at"],
                    ),
                )
        return result

    monkeypatch.setattr(worker, "_pattern_inputs", changed)
    assert worker.select_fresh_question(f.now) == 0
    assert len(rows(worker, "role_question_selections")) == 1
    assert worker.get(first["id"])["result"]["followup"]["action"] == "no_change"
    assert len(worker.transport.calls) == 3
    assert rows(worker, "lesson_access") == access


def test_legacy_pattern_policy_does_not_enter_learning_or_change_packet(fixture, monkeypatch):
    f, worker, _ = fixture
    worker.transport = PatternTransport("no_change")
    monkeypatch.setattr(
        worker, "_pattern_learning_prior", lambda *_a, **_k: pytest.fail("legacy learning")
    )
    saved = select(f, worker)
    assert "pattern_learning" not in saved["context"] and saved["context"]["lesson"] is None
    _, packet = worker._packet(saved)
    assert "e5" not in packet["evidence"] and set(packet["capabilities"]) == {"p0"}
    assert asyncio.run(worker.step(f.now))
    assert worker.get(saved["id"])["result"]["action"] == "no_change"


def test_same_event_and_data_wait_do_not_create_preferred_answer_repeat(fixture):
    f, worker, _ = fixture
    worker.transport.action = "request_data"
    first = select(f, worker)
    assert asyncio.run(worker.step(f.now))
    before = rows(worker, "role_attempts")
    assert worker.select_fresh_question(f.now + 61) == 0
    assert len(rows(worker, "role_tasks")) == 1 and rows(worker, "role_attempts") == before
    assert worker.get(first["id"])["result"]["action"] == "request_data"
