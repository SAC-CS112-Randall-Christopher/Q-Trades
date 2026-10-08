"""Native/software method succession; financial proof requires the owned disposable PG fixture."""

import asyncio
import copy
import json
import sys
from collections import Counter

import pytest
from test_autonomous_lab import bars_at, close_window, make_lab, tick_lab
from test_daily_pattern_analyzer import advance
from test_paper_store import pg_store as pg_store
from test_pattern_research_learning import LearningTransport, later, mature
from test_pattern_role_worker import (
    build_pattern_worker_fixture,
    restore_scored_body,
    rows,
    select,
)
from test_role_question_selection import abstention, causal_frame

from trading.autonomous_finance import slots
from trading.autonomous_lab import AutonomousLab
from trading.autonomous_spec import LabProposal
from trading.experiment_registry import fingerprint
from trading.lab_role_contract import (
    PATTERN_METHOD_QUESTION_POLICY,
    PATTERN_METHODS,
    PATTERN_VERSION,
    packet_json,
    pattern_method_policy_sha,
    prompt,
    validate,
)
from trading.pattern_comparisons import PatternComparisonCommand, PatternComparisons
from trading.role_evidence import pattern_feature, pattern_followup_outcome, pattern_packet
from trading.role_worker import RoleWorker


class MethodTransport(LearningTransport):
    """Software callback, unchanged conservative 9000 input/reserve fixture guard."""

    def __init__(self, action="propose_experiment"):
        super().__init__(action)
        self.authority["question_policy"] = PATTERN_METHOD_QUESTION_POLICY
        self.authority["method_policy_sha256"] = pattern_method_policy_sha()
        self.matched_packets = []

    def infer(self, role, packet, profile):
        self.calls.append((role, copy.deepcopy(packet)))
        if role == "reviewer":
            answer = {
                "action": "exploratory_paper_only",
                "evidence_ids": ["e1", "e3"],
                "issues": [],
                "rationale": "Matched observed inputs support exploration only.",
            }
        else:
            followup = "body" in packet["evidence"].get("e1", {})
            action = "no_change" if followup or not packet["capabilities"] else self.action
            answer = abstention(action)
            answer["evidence_ids"] = ["e3", "e5"]
            if action == "propose_experiment":
                answer["capability"] = next(iter(packet["capabilities"]))
            elif action == "request_data":
                answer["dependency"] = "new_closed_bars"
        return {
            "complete": True,
            "answer": answer,
            "scope": "Deterministic disposable software callback; no actual model",
        }


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    f, worker, selection = build_pattern_worker_fixture(tmp_path, monkeypatch)
    worker.transport = MethodTransport()
    try:
        yield f, worker, selection
    finally:
        (tmp_path / "method-packets.json").write_text(
            json.dumps(list(worker.transport.packets.values()), indent=2), encoding="utf-8"
        )
        (tmp_path / "matched-method-packets.json").write_text(
            json.dumps(worker.transport.matched_packets, indent=2), encoding="utf-8"
        )
        f.close()


def mark_used(worker, method_id):
    """Ordinary inbox publication, labeled foreign fixture scope, not a funded result."""
    bridge = worker.pattern_comparisons
    now = bridge.scanner.paper.state["last_tick"]
    selection = bridge.candidate(now)
    described = bridge.describe(selection, method_id=method_id)
    original = bridge.prepare(
        PatternComparisonCommand(
            **selection.model_dump(),
            request_id="foreign-" + method_id,
            expected_finding_sha256=described["finding_sha256"],
        ),
        now,
        method_id=method_id,
    )
    assert original["status"] == "supported"
    proposal = LabProposal.model_validate(original["proposal"])
    worker.controller.inbox.submit(proposal, original["evaluation"]["candidate"])
    worker.controller.inbox.update(proposal.request_id, "completed", "foreign-fixture")
    return proposal


def restarted(f, worker):
    new = RoleWorker(
        f.registry,
        worker.controller,
        worker.transport,
        f.scanner.storage_owner,
        pattern_comparisons=worker.pattern_comparisons,
    )
    new.enabled, new.paper_admission = True, lambda: True
    return new


def verify_matched_prior_packet(worker, task, packet):
    """Same task/profile, equivalent expanded facts versus the current projection.

    This is a conservative byte comparison, not tokenizer or model-capacity proof.
    Earlier source-run refusals remain separate historical evidence.
    """
    context = task["context"]
    original = fingerprint(task)
    method = context["pattern_method"]["method_id"]
    prior = context["lesson"]
    native = pattern_packet(context["pattern_comparison"])
    observed = packet["evidence"]["e3"]
    assert observed["finding_sha256"] == native["finding_sha256"]
    assert observed["coverage"] == native["coverage"] and len(observed["coverage"]) == 5
    event = native["original_event"]
    assert observed["original_event"] == {
        key: value for key, value in event.items() if key != "reason"
    } | {"reason_sha256": fingerprint(event["reason"])}
    assert observed["native_proof"] == {
        "verified": native["native_proof"]["archive_verified"],
        "recognition_rows": native["native_proof"]["recognition_rows"],
        "contiguous": native["native_proof"]["contiguous_relevant_window"],
    }
    causal = context["tool_evidence"]
    for group in ("features", "reference_features"):
        for key, feature in causal[group].items():
            expected = pattern_feature(feature)
            expected.pop("detail_sha256")
            assert packet["evidence"]["e2"][group][key] == expected
    assert packet["evidence"]["e2"]["detail_sha256"] == fingerprint(causal)
    assert packet["evidence"]["e5"]["outcome"]["source_sha256"] == fingerprint(prior["source"])
    restored = restore_scored_body(packet["evidence"]["e5"]["outcome"])
    assert restored == prior["source"]["body"]
    assert fingerprint(restored) == fingerprint(prior["source"]["body"])
    assert packet["evidence"]["e5"]["support"] == prior["support"]
    assert packet["evidence"]["e5"]["data_basis"] == prior["context"]["data_basis"]
    assert packet["evidence"]["e5"]["same_cost_policy"] is True
    assert fingerprint(prior["context"]["cost_policy"]) == fingerprint(context["policy"])
    expanded = copy.deepcopy(packet)
    expanded["evidence"]["e3"] = native
    expanded["evidence"]["e0"] = worker._base_packet(task)[1]["evidence"]["e0"]
    for group in ("features", "reference_features"):
        expanded["evidence"]["e2"][group] = {
            key: pattern_feature(value) for key, value in causal[group].items()
        }
    expanded["evidence"]["e2"].pop("detail_sha256")
    expanded["fixed_comparison"][method].update(
        candidate=context["pattern_method"]["candidate"],
        reference=context["pattern_method"]["reference"],
    )
    learning = expanded["evidence"]["e5"]
    learning.update(
        cutoff=context["pattern_learning"]["cutoff"],
        dispatch_available=True,
        cost_policy_sha256=fingerprint(prior["context"]["cost_policy"]),
        unknowns=prior["unknowns"],
    )
    learning.pop("same_cost_policy")
    learning["outcome"].update(id=prior["source"]["id"], at=prior["source"]["at"])
    learning["method_transition"]["method_policy_sha256"] = pattern_method_policy_sha()
    assert len(packet["selection_authority"]) == 7
    assert expanded["selection_authority"] == packet["selection_authority"]
    assert packet["selection_authority"]["method_policy_sha256"] == pattern_method_policy_sha()
    system = prompt("researcher", PATTERN_VERSION)
    measurements = {}
    for label, value in (("expanded_equivalent", expanded), ("current", packet)):
        encoded = packet_json(value)
        measurements[label] = {
            "packet": value,
            "packet_json": encoded,
            "packet_bytes": len(encoded.encode()),
            "system_bytes": len(system.encode()),
            "reserved_total": len(encoded.encode()) + len(system.encode()) + 1536,
        }
    assert measurements["expanded_equivalent"]["reserved_total"] > 9000
    assert measurements["current"]["reserved_total"] <= 9000
    assert fingerprint(task) == original
    worker.transport.matched_packets.append(
        {
            "task_id": task["id"],
            "task_sha256": original,
            "profile": worker.transport.admit("researcher"),
            "authority": copy.deepcopy(packet["selection_authority"]),
            "system": system,
            "complete_scored_sha256": fingerprint(restored),
            "measurements": measurements,
            "reason_disclosure": "Original detector explanation is hash-addressed metadata; "
            "full original text remains in the exact task/preparation, not this model packet.",
        }
    )


def test_first_unused_p0_is_captured_in_all_owners(fixture):
    f, worker, _ = fixture
    task = select(f, worker)
    context = task["context"]
    method = context["pattern_method"]
    assert method == worker._pattern_method_identity("p0")
    assert context["question_selection"]["method_identity"] == method
    assert context["pattern_learning"]["previous_method"] is None
    assert context["pattern_learning"]["used_methods"] == {"p0": False, "p1": False}
    assert context["lesson"] is None and context["question"]["parent"] is None
    _, packet = worker._packet(task)
    assert set(packet["capabilities"]) == {"p0"}
    assert "p0" in packet["question"] and packet["evidence"]["e5"]["state"] == "first_question"
    worker.transport.preflight("researcher", packet, worker.transport.admit("researcher"))
    assert worker.select_fresh_question(f.now + 61) == 0
    assert not rows(worker, "role_attempts")


def test_foreign_used_p0_starts_p1_without_foreign_lesson(fixture):
    f, worker, _ = fixture
    foreign = mark_used(worker, "p0")
    prior = rows(worker, "lab_proposals")
    task = select(f, worker)
    context = task["context"]
    assert set(context["catalog"]) == {"p1"}
    assert context["pattern_method"] == worker._pattern_method_identity("p1")
    assert context["lesson"] is None
    assert context["pattern_learning"]["state"] == "first_question"
    assert context["pattern_learning"]["previous_method"] is None
    original = worker.pattern_comparisons.get(
        context["pattern_comparison"]["preparation_request_id"]
    )
    assert original["method_id"] == "p1"
    assert original["method_policy_sha256"] == pattern_method_policy_sha()
    assert original["proposal"]["strategy"]["family"] == "trend-pullback-v1"
    _, packet = worker._packet(task)
    assert set(packet["fixed_comparison"]) == set(packet["capabilities"]) == {"p1"}
    assert "p1" in packet["question"] and "fixed p0" not in packet["question"]
    assert packet["evidence"]["e5"]["lesson"] is None
    worker.transport.preflight("researcher", packet, worker.transport.admit("researcher"))
    assert rows(worker, "lab_proposals") == prior
    assert worker.controller.inbox.get(foreign.request_id)["body"] == foreign.model_dump()


@pytest.mark.parametrize("outcome", ["data_blocked", "rejected"])
def test_own_mature_p0_motivates_independent_p1_with_lossless_prior(fixture, outcome):
    f, worker, _ = fixture
    first = mature(f, worker, outcome=outcome)
    preserved = copy.deepcopy(first)
    second = later(f, worker)
    learning, context = second["context"]["pattern_learning"], second["context"]
    assert learning["previous_method"]["method_id"] == "p0"
    assert learning["next_method"]["method_id"] == "p1"
    assert learning["lesson"] == context["question_selection"]["lesson"]
    assert context["question"]["parent"] is None
    assert context["catalog"]["p1"]["kind"] == "independent"
    role, packet = worker._packet(second)
    assert restore_prior_score(packet) == first["result"]["outcome"]["body"]
    assert fingerprint(restore_prior_score(packet)) == fingerprint(
        first["result"]["outcome"]["body"]
    )
    assert packet["evidence"]["e5"]["outcome"]["source_sha256"] == fingerprint(
        first["result"]["outcome"]
    )
    assert packet["capabilities"]["p1"]["family"] == "trend-pullback-v1"
    assert packet["fixed_comparison"]["p1"]["detail_sha256"]
    assert packet["evidence"]["e5"]["method_transition"]["previous"] == "p0"
    assert packet["evidence"]["e5"]["method_transition"]["next"] == "p1"
    worker.transport.preflight(role, packet, worker.transport.admit(role))
    verify_matched_prior_packet(worker, second, packet)
    for _ in range(5):
        assert asyncio.run(worker.step(f.now)), worker.get(second["id"])["reason"]
    second = worker.get(second["id"])
    assert second["stage"] == "outcome"
    assert second["proposal"]["strategy"]["family"] == "trend-pullback-v1"
    assert second["proposal"]["kind"] == "independent"
    assert second["proposal"].get("parent_trial") is None
    assert second["evaluation"]["pattern_method"] == context["pattern_method"]
    assert worker.get(first["id"])["result"] == preserved["result"]
    assert len(rows(worker, "lab_proposals")) == 2
    assert all(item["reserved_total"] <= 9000 for item in worker.transport.measured)


def test_shared_score_projection_preserves_different_types_nulls_and_unknown_fields():
    """Equal facts may be referenced; different facts and absent keys remain exact."""
    current = {
        "id": 2,
        "at": 200,
        "body": {
            "same": "recorded",
            "typed": True,
            "null": None,
            "only_current": "new",
            "execution_samples": {
                "common": {"same": "100", "typed": True, "only_current": None},
                "candidate": {"strategy_version": "p1"},
                "reference": {"strategy_version": "reference"},
            },
        },
    }
    prior = {
        "body": {
            "same": "recorded",
            "typed": 1,
            "null": "unknown",
            "only_prior": None,
            "execution_samples": {
                "common": {"same": "100", "typed": 1.0, "only_prior": None},
                "candidate": {"strategy_version": "p0"},
                "reference": {"strategy_version": "reference"},
            },
        },
        "source_sha256": "a" * 64,
    }
    original, original_current = copy.deepcopy(prior), copy.deepcopy(current)
    RoleWorker._pattern_shared_outcome(prior, current)
    packet = {"evidence": {"e1": current, "e5": {"outcome": prior}}}
    restored = restore_prior_score(packet)
    # This synthetic input is already coalesced, so undo the existing sample
    # encoding once to compare the complete original body and canonical types.
    expected = restore_scored_body(original)
    assert fingerprint(restored) == fingerprint(expected)
    assert prior["source_sha256"] == original["source_sha256"]
    assert current == original_current
    assert prior["body"]["typed"] == 1 and type(prior["body"]["typed"]) is int
    assert type(prior["body"]["execution_samples"]["common"]["typed"]) is float
    collision = {
        "id": 1,
        "at": 100,
        "body": original["body"]
        | {
            "candidate_sample": {"fees": "0"},
            "reference_sample": {"fees": None},
            "execution_samples": {"common": {}, "unexpected_original_field": None},
        },
    }
    collision_current = copy.deepcopy(collision)
    collision_current["body"]["execution_samples"] = {"common": {}, "current_only": True}
    encoded = pattern_followup_outcome(collision)
    base = pattern_followup_outcome(collision_current)
    original_collision, original_base = copy.deepcopy(collision), copy.deepcopy(base)
    RoleWorker._pattern_shared_outcome(encoded, base)
    collision_packet = {"evidence": {"e1": base, "e5": {"outcome": encoded}}}
    # An original execution_samples key is unknown source data, not generated
    # sample encoding: reconstruct its exact body without unpacking it.
    assert fingerprint(restore_prior_projection(collision_packet)["body"]) == fingerprint(
        original_collision["body"]
    )
    assert collision == original_collision and base == original_base


@pytest.mark.parametrize("archive", [False, True])
def test_p1_data_wait_hot_and_cold_resume_keeps_exact_method(fixture, monkeypatch, archive):
    f, worker, _ = fixture
    mark_used(worker, "p0")
    worker.transport.action = "request_data"
    first = select(f, worker)
    assert asyncio.run(worker.step(f.now)), worker.get(first["id"])["reason"]
    answer = copy.deepcopy(worker.get(first["id"])["result"])
    if archive:
        monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
        worker.history.rollover()
        # Active typed waits deliberately remain hot; no forced cold state.
        assert worker.get(first["id"])["archive_reference"] is None
    advance(f, 120)
    f.paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
    new = restarted(f, worker)
    assert new.resume_sources(f.now) == 1
    second = next(t for t in new.page()["tasks"] if t["id"] != first["id"])
    second = new.get(second["id"])
    assert second["context"]["pattern_method"] == first["context"]["pattern_method"]
    assert set(second["context"]["catalog"]) == {"p1"}
    assert "p1" in new._packet(second)[1]["question"]
    assert new.get(first["id"])["result"] == answer
    if archive:
        new.history.rollover()
        cold = restarted(f, new)
        assert cold.get(first["id"])["archive_reference"]
        assert cold.get(first["id"])["result"] == answer
        assert (
            cold.get(first["id"])["context"]["pattern_method"]
            == (first["context"]["pattern_method"])
        )
        assert cold.resume_sources(f.now) == 0


@pytest.mark.parametrize("change", ["used", "grant", "policy", "method"])
def test_changed_during_preparation_refuses_publication_before_model(fixture, monkeypatch, change):
    f, worker, _ = fixture
    bridge = worker.pattern_comparisons
    actual = bridge.prepare

    def changed(*args, **kwargs):
        value = actual(*args, **kwargs)
        if change == "used":
            monkeypatch.setattr(bridge, "prepare", actual)
            mark_used(worker, "p0")
        elif change == "grant":
            worker.transport.authority["grant_sha"] = "d" * 64
        elif change == "policy":
            f.paper.state["autonomous_lab"]["policy"]["horizon_seconds"] += 1
        else:
            monkeypatch.setattr("trading.role_worker.pattern_method_policy_sha", lambda: "e" * 64)
        return value

    monkeypatch.setattr(bridge, "prepare", changed)
    assert worker.select_fresh_question(f.now) == 0
    assert not rows(worker, "role_tasks") and not rows(worker, "role_attempts")
    assert not worker.transport.calls


def test_all_foreign_used_is_honest_wait_with_no_source_adoption(fixture):
    f, worker, _ = fixture
    mark_used(worker, "p0")
    mark_used(worker, "p1")
    assert worker.select_fresh_question(f.now) == 0
    assert "All fixed methods" in worker.question_selection_status()["reason"]
    assert not rows(worker, "role_tasks") and not rows(worker, "research_lessons")


def test_used_state_changes_before_model_refuse_uncharged(fixture):
    f, worker, _ = fixture
    selected = select(f, worker)
    mark_used(worker, "p0")
    assert asyncio.run(worker.step(f.now)) is False
    retained = worker.get(selected["id"])
    assert retained["status"] == "waiting" and "availability" in retained["reason"]
    assert not rows(worker, "role_attempts") and not worker.transport.calls


def test_restart_archived_mature_source_preserves_next_method_and_dedup(fixture, monkeypatch):
    f, worker, _ = fixture
    first = mature(f, worker)
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    worker.history.rollover()
    assert worker.get(first["id"])["archive_reference"]
    new = restarted(f, worker)
    second = later(f, new)
    assert second["context"]["pattern_learning"]["source_task"] == first["id"]
    assert second["context"]["pattern_method"]["method_id"] == "p1"
    assert second["context"]["lesson"]["source"] == first["result"]["outcome"]
    assert new.select_fresh_question(f.now + 61) == 0
    assert len(rows(new, "role_question_selections")) == 2


def test_p1_unoffered_p0_answer_is_rejected_without_proposal(fixture):
    f, worker, _ = fixture
    mark_used(worker, "p0")
    task = select(f, worker)
    _, packet = worker._packet(task)
    answer = abstention("propose_experiment") | {"capability": "p0", "evidence_ids": ["e3"]}
    with pytest.raises(ValueError):
        validate("researcher", answer, packet)
    assert task["proposal"] is None and len(rows(worker, "lab_proposals")) == 1


def engine_shaped_score(task, start, end):
    """Projection fixture modeled on the retained actual PG02 score, not a funded result."""
    common = {
        "available_cash": "100",
        "cash": "100",
        "closed": 0,
        "equity": "100",
        "execution_drag": "0",
        "execution_profile": "paper-rest-ioc-v1",
        "fees": "0",
        "flat": True,
        "fresh": True,
        "funding": "100",
        "liquidation_drag": "0",
        "liquidation_fee": "0",
        "nav": "1",
        "net_pnl": "0",
        "operating_daily_usd": "0",
        "realized": "0",
        "reserved": "0",
        "risk_policy": "cash-spot-hard-stop-v1",
        "settings_version": 0,
        "starting_capital": "100",
        "units": "100",
        "unrealized": "0",
        "valuation_at": end,
        "valuation_issues": {},
        "wins": 0,
    }
    proposal = task["proposal"]
    return {
        "available_at": end,
        "candidate_sample": common
        | {"strategy_version": "lab-rule-" + fingerprint(proposal["strategy"])[:24]},
        "reference_sample": common
        | {"strategy_version": "lab-rule-" + fingerprint(proposal["reference"])[:24]},
        "cash_usd": None,
        "coverage_seconds": 2.0,
        "delta_usd": None,
        "dependence": "Related trials and shared market windows are correlated, "
        "not independent confirmation",
        "fees_treatment": "Executable equity already includes entry/exit/liquidation costs once",
        "net_after_operating_usd": {"candidate": None, "reference": None},
        "operating_each_usd": "0.0",
        "outcome": "data_blocked",
        "passive_usd": None,
        "proposal_id": proposal["request_id"],
        "qualification": "Exploration only; no CP7 or live promotion",
        "reason": "Fixed window lacks complete executable marks/coverage; "
        "no strategy-failure claim",
        "trial_id": "lab-" + fingerprint(proposal)[:24],
        "window_end": end,
        "window_start": start,
    }


def restore_prior_projection(packet):
    encoded = copy.deepcopy(packet["evidence"]["e5"]["outcome"])
    if "body_base" in encoded:
        assert encoded.pop("body_base") == "e1.body"
        body = copy.deepcopy(packet["evidence"]["e1"]["body"])
        for key in encoded.pop("body_remove", []):
            body.pop(key)
        body.update(encoded["body"])
        if "samples_overlay_common" in encoded:
            assert encoded.pop("samples_overlay_common") is True
            samples = copy.deepcopy(packet["evidence"]["e1"]["body"]["execution_samples"])
            for key in encoded.pop("samples_remove", []):
                samples.pop(key)
            common = samples["common"]
            for key in encoded.pop("sample_common_remove", []):
                common.pop(key)
            common.update(body["execution_samples"]["common"])
            samples.update(body["execution_samples"])
            samples["common"] = common
            body["execution_samples"] = samples
        encoded["body"] = body
    return encoded


def restore_prior_score(packet):
    return restore_scored_body(restore_prior_projection(packet))


def test_actual_engine_shaped_two_score_packets_remain_lossless(fixture, monkeypatch):
    """Native/software progression with recorded engine-shaped metadata; actual PG is separate."""
    f, worker, _ = fixture
    actual_update = worker._update

    def shaped_update(task, stage, *args, **kwargs):
        result = kwargs.get("result")
        if stage == "followup" and result and result.get("outcome"):
            result = copy.deepcopy(result)
            old = result["outcome"]["body"]
            result["outcome"]["body"] = engine_shaped_score(
                task, old["window_start"], old["window_end"]
            )
            kwargs["result"] = result
        return actual_update(task, stage, *args, **kwargs)

    monkeypatch.setattr(worker, "_update", shaped_update)
    first = mature(f, worker)
    second = later(f, worker)
    for _ in range(5):
        assert asyncio.run(worker.step(f.now)), worker.get(second["id"])["reason"]
    second = worker.get(second["id"])
    assert second["stage"] == "outcome"
    worker.controller.inbox.update(
        second["proposal"]["request_id"], "completed", "engine-shaped-fixture"
    )
    end = f.now + 86400
    score = engine_shaped_score(second, f.now, end)
    outcome = {"id": 2, "at": end, "body": score}
    assert worker._update(second, "followup", result=second["result"] | {"outcome": outcome})
    advance(f, 86400)
    second = worker.get(second["id"])
    original_task_sha = fingerprint(second)
    role, packet = worker._packet(second)
    worker.transport.preflight(role, packet, worker.transport.admit(role))
    assert restore_scored_body(packet["evidence"]["e1"]) == score
    assert fingerprint(restore_prior_score(packet)) == fingerprint(
        first["result"]["outcome"]["body"]
    )
    assert packet["evidence"]["e5"]["outcome"]["source_sha256"] == fingerprint(
        first["result"]["outcome"]
    )
    assert packet["evidence"]["e1"]["source_sha256"] == fingerprint(outcome)
    expanded = copy.deepcopy(packet)
    original_prior = pattern_followup_outcome(first["result"]["outcome"])
    for key in ("detail", "id", "at"):
        original_prior.pop(key)
    original_prior["body"]["execution_samples"]["encoding"] = "sample=common+named"
    expanded["evidence"]["e5"]["outcome"] = original_prior
    system = prompt(role, PATTERN_VERSION)
    measurements = {
        label: {
            "packet": value,
            "packet_json": packet_json(value),
            "packet_bytes": len(packet_json(value).encode()),
            "system_bytes": len(system.encode()),
            "reserved_total": len(packet_json(value).encode()) + len(system.encode()) + 1536,
        }
        for label, value in (("expanded_same_task", expanded), ("current", packet))
    }
    assert measurements["expanded_same_task"]["reserved_total"] > 9000
    assert measurements["current"]["reserved_total"] <= 9000
    worker.transport.matched_packets.append(
        {
            "task_id": second["id"],
            "task": copy.deepcopy(second),
            "task_sha256": fingerprint(second),
            "profile": worker.transport.admit(role),
            "authority": copy.deepcopy(packet["selection_authority"]),
            "system": system,
            "current_complete_scored_sha256": fingerprint(score),
            "prior_complete_scored_sha256": fingerprint(first["result"]["outcome"]["body"]),
            "measurements": measurements,
        }
    )
    assert asyncio.run(worker.step(f.now)), worker.get(second["id"])["reason"]
    assert fingerprint(second) == original_task_sha
    assert worker.get(second["id"])["status"] == "done"
    assert worker.get(first["id"])["result"] == first["result"]
    assert len(rows(worker, "lab_proposals")) == 2
    worker.select_followups()
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    worker.history.rollover()
    assert worker.get(first["id"])["archive_reference"]
    assert worker.get(second["id"])["archive_reference"]
    new = restarted(f, worker)
    third = later(f, new)
    assert third["context"]["catalog"] == {}
    assert third["context"]["pattern_method"]["method_id"] == "p1"
    role, packet = new._packet(third)
    new.transport.preflight(role, packet, new.transport.admit(role))
    assert restore_prior_score(packet) == score
    assert asyncio.run(new.step(f.now)), new.get(third["id"])["reason"]
    assert new.get(third["id"])["status"] == "done"
    assert len(rows(new, "lab_proposals")) == 2


@pytest.mark.parametrize("sample_shape", ["missing", "null", "non_dict", "mixed", "collision"])
def test_full_followup_packet_preserves_unavailable_or_original_sample_fields(
    fixture, sample_shape
):
    """Full caller regression on copied software task inputs, without financial or model effects."""
    f, worker, _ = fixture
    mature(f, worker)
    second = later(f, worker)
    for _ in range(5):
        assert asyncio.run(worker.step(f.now)), worker.get(second["id"])["reason"]
    saved = worker.get(second["id"])
    task = copy.deepcopy(saved)
    prior = task["context"]["lesson"]["source"]["body"]
    if sample_shape == "missing":
        prior.pop("candidate_sample")
        prior.pop("reference_sample")
    elif sample_shape == "null":
        prior.update(candidate_sample=None, reference_sample=None)
    elif sample_shape == "non_dict":
        prior.update(candidate_sample="unavailable", reference_sample=[])
    elif sample_shape == "mixed":
        prior.update(candidate_sample={"fees": None}, reference_sample=None)
    else:
        prior["execution_samples"] = {"unknown_original_field": None}
    task["stage"] = "followup"
    task["result"]["outcome"] = {
        "id": 2,
        "at": f.now + 86400,
        "body": engine_shaped_score(task, f.now, f.now + 86400),
    }
    original = copy.deepcopy(task)
    role, packet = worker._packet(task)
    projected = restore_prior_projection(packet)["body"]
    expected = original["context"]["lesson"]["source"]["body"]
    # Only generated encodings are unpacked. An original collision is literal
    # source data, retaining both its unknown field and original sample fields.
    restored = projected if sample_shape == "collision" else restore_prior_score(packet)
    assert fingerprint(restored) == fingerprint(expected)
    assert packet["evidence"]["e5"]["outcome"]["source_sha256"] == fingerprint(
        original["context"]["lesson"]["source"]
    )
    assert packet["evidence"]["e1"]["source_sha256"] == fingerprint(original["result"]["outcome"])
    assert fingerprint(restore_scored_body(packet["evidence"]["e1"])) == fingerprint(
        original["result"]["outcome"]["body"]
    )
    assert task == original and worker.get(saved["id"]) == saved
    total = len(packet_json(packet).encode()) + len(prompt(role, PATTERN_VERSION).encode()) + 1536
    if total > 9000:
        with pytest.raises(ValueError, match="Packet exceeds conservative context allowance"):
            worker.transport.preflight(role, packet, worker.transport.admit(role))
    else:
        worker.transport.preflight(role, packet, worker.transport.admit(role))
    worker.transport.matched_packets.append(
        {
            "kind": "full_caller_sample_regression",
            "shape": sample_shape,
            "task": original,
            "packet": packet,
            "task_sha256": fingerprint(original),
            "reserved_total": total,
            "guard_admitted": total <= 9000,
        }
    )


def retain_engine_proof(
    directory, store, paper, worker, initial_records, initial_cutoff, original_controls, failure
):
    """Retain bounded failed or successful disposable state before owners close."""
    errors = []

    def saved(name, producer):
        try:
            value = producer()
            encoded = json.dumps(value, indent=2, default=str).encode("utf-8")
            if len(encoded) > 4 * 1024**2:
                raise ValueError("Disposable proof exceeds the explicit 4 MiB artifact bound")
            (directory / name).write_bytes(encoded)
            return value
        except Exception as exc:
            errors.append({"artifact": name, "type": type(exc).__name__, "error": str(exc)[:1000]})
            return None

    audit = saved("actual-method-financial-export.json", lambda: store.export(0, 10000))
    saved("actual-method-paper-state.json", lambda: paper.state)
    saved("actual-method-packets.json", lambda: list(worker.transport.packets.values()))
    task_state = saved(
        "actual-method-worker-state.json",
        lambda: {
            "tasks": [
                worker.get(row[0])
                for row in worker.registry.db.execute(
                    "SELECT id FROM role_tasks ORDER BY id LIMIT 20"
                ).fetchall()
            ],
            "attempts": rows(worker, "role_attempts"),
            "proposal_rows": rows(worker, "lab_proposals"),
        },
    )
    records = audit["records"] if audit is not None else None
    counts = Counter((row["account"], row["kind"]) for row in records) if records else Counter()
    proof = {
        "scope": "Actual disposable engine; synthetic native inputs/accelerated clock "
        "and software answers. Not real 24-hour coverage, trading edge or model proof.",
        "original_failure": failure,
        "original_event_journal_prefix": {
            "cutoff": initial_cutoff,
            "rows": len(initial_records),
            "sha256": fingerprint(initial_records),
            "preserved": None
            if records is None
            else ([row for row in records if row["id"] <= initial_cutoff] == initial_records),
        },
        "final_event_rows": None if records is None else len(records),
        "export_has_more": None if audit is None else audit["has_more"],
        "event_counts": [
            {"account": account_id, "kind": kind, "count": count}
            for (account_id, kind), count in sorted(counts.items())
        ],
        "trials": list(paper.state["autonomous_lab"]["trials"].values()),
        "trial_events": [row for row in records or [] if row["kind"].startswith("lab_")],
        "completed_tasks": [
            {
                "id": task["id"],
                "status": task["status"],
                "stage": task["stage"],
                "proposal": task["proposal"],
                "outcome": (task["result"] or {}).get("outcome"),
            }
            for task in (task_state or {}).get("tasks", [])
            if (task["result"] or {}).get("outcome")
        ],
        "account_count": len(paper.state["accounts"]),
        "slots": slots(paper.state),
        "original_controls": original_controls,
        "original_controls_preserved": all(
            {name: paper.state["accounts"][key].get(name) for name in controls} == controls
            for key, controls in original_controls.items()
        ),
        "reconcile": saved("actual-method-reconcile.json", store.reconcile),
        "software_callbacks": len(worker.transport.calls),
        "capture_errors": errors,
    }
    saved("actual-method-engine-proof.json", lambda: proof)
    if errors:
        (directory / "actual-method-capture-errors.json").write_text(
            json.dumps(errors, indent=2), encoding="utf-8"
        )
    return errors


def test_actual_two_independent_comparisons_preserve_mature_source_and_accounts(
    pg_store, tmp_path, monkeypatch
):
    """Owned PG engine with synthetic time/software answers; no trading-edge inference."""
    store, _ = pg_store
    f, worker, _ = build_pattern_worker_fixture(tmp_path / "native", monkeypatch)
    worker.transport = MethodTransport()
    (tmp_path / "financial").mkdir()
    financial = make_lab(
        store, tmp_path / "financial", now=f.now, holding_horizons=("medium",), horizon_seconds=3600
    )
    financial.registry.close()
    paper = financial.paper
    # Reuse the existing native scanner fixture's read contract. Live quotes are
    # explicitly unavailable; no cost estimate, venue connection or fresh quote is invented.
    scanner_reads = f.paper
    paper.quotes, paper.stream = scanner_reads.quotes, scanner_reads.stream
    paper._fallback = scanner_reads._fallback
    paper.universe, paper.history = f.paper.universe, copy.deepcopy(f.paper.history)
    paper.ready_at, paper._candle_errors = f.now - 60, {}
    paper.memory_book, paper.constrained = lambda symbol: None, lambda: False
    paper.control_frames = lambda: {"BTCUSD": causal_frame(f.now, paper.history["BTCUSD"])}
    f.paper = f.scanner.paper = paper
    controller = AutonomousLab(f.registry, paper, lambda: True)
    worker.controller = controller
    worker.pattern_comparisons = PatternComparisons(f.scanner, controller)
    original_controls = {
        key: {
            name: copy.deepcopy(value.get(name))
            for name in ("funding", "risk_policy", "rule_spec", "admitted_at")
        }
        for key, value in paper.state["accounts"].items()
    }
    initial_audit = store.export(0, 10000)
    assert initial_audit["has_more"] is False
    initial_records = copy.deepcopy(initial_audit["records"])
    initial_cutoff = initial_audit["next_after"]
    completed = []
    try:
        for method_id in ("p0", "p1"):
            if method_id == "p0":
                task = select(f, worker)
            else:
                task = later(f, worker)
                assert task["context"]["lesson"]["source"] == completed[0]["result"]["outcome"]
                assert task["context"]["pattern_learning"]["previous_method"]["method_id"] == "p0"
            assert task["context"]["pattern_method"]["method_id"] == method_id
            for _ in range(5):
                assert asyncio.run(worker.step(f.now)), worker.get(task["id"])["reason"]
                f.now += 1
                paper.state["last_tick"] = f.now
            assert worker.get(task["id"])["stage"] == "outcome"
            if method_id == "p0":
                tick_lab(controller, f.now)
                assert controller.step(f.now) is False
                assert paper.state["autonomous_lab"]["phase"] == "capture_blocked"
                f.now = max(f.now + 2, paper.state["autonomous_lab"]["next_action_at"])
            active = []
            for _ in range(32):
                tick_lab(controller, f.now)
                recording = f.storage.snapshot()
                assert (
                    recording["state"] == "recording" and recording["plan"] == f.plan.model_dump()
                )
                (f.registry.path.parent / "research-storage-status.json").write_text(
                    json.dumps(recording | {"receipt_at": f.now}), encoding="utf-8"
                )
                worked = controller.step(f.now)
                active = [
                    t
                    for t in paper.state["autonomous_lab"]["trials"].values()
                    if t["status"] == "active"
                ]
                if active:
                    break
                assert not controller.last_error, controller.last_error
                f.now = (
                    f.now + 2
                    if worked
                    else max(f.now + 2, paper.state["autonomous_lab"]["next_action_at"])
                )
            assert len(active) == 1, {
                "error": controller.last_error,
                "phase": paper.state["autonomous_lab"]["phase"],
            }
            trial = active[0]
            assert trial["contract"]["proposal"]["kind"] == "independent"
            assert trial["contract"]["proposal"].get("parent_trial") is None
            assert (
                trial["contract"]["proposal"]["strategy"]["family"] == PATTERN_METHODS[method_id][0]
            )
            assert trial["review_at"] - trial["started_at"] >= 86400
            outcome = close_window(controller, trial, "data_blocked")
            f.now = outcome["available_at"] + 2
            assert asyncio.run(worker.step(f.now))
            f.now += 1
            assert asyncio.run(worker.step(f.now)), worker.get(task["id"])["reason"]
            done = worker.get(task["id"])
            assert done["status"] == "done" and done["result"]["followup"]["action"] == "no_change"
            assert done["result"]["outcome"]["body"]["outcome"] == "data_blocked"
            assert restore_scored_body(worker.transport.calls[-1][1]["evidence"]["e1"]) == outcome
            assert worker.select_followups()["selected"] == 0
            completed.append(done)
            assert store.reconcile()["balanced"] is True
        assert len(rows(worker, "lab_proposals")) == 2
        assert len(rows(worker, "role_attempts")) == len(worker.transport.calls) == 6
        for key, controls in original_controls.items():
            assert {name: paper.state["accounts"][key].get(name) for name in controls} == controls
        monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
        worker.history.rollover()
        new = restarted(f, worker)
        for done in completed:
            assert new.get(done["id"])["result"] == done["result"]
            assert new.get(done["id"])["archive_reference"]
        before = rows(worker, "lab_proposals")
        third = later(f, new)
        assert third["context"]["pattern_method"]["method_id"] == "p1"
        assert third["context"]["catalog"] == {}
        assert third["context"]["lesson"]["source"] == completed[1]["result"]["outcome"]
        assert asyncio.run(new.step(f.now)), new.get(third["id"])["reason"]
        assert rows(worker, "lab_proposals") == before and len(worker.transport.calls) == 7
        assert all(p["reserved_total"] <= 9000 for p in worker.transport.measured)
        assert store.reconcile()["balanced"] is True
        final_audit = store.export(0, 10000)
        assert final_audit["has_more"] is False
        final_records = final_audit["records"]
        assert [record for record in final_records if record["id"] <= initial_cutoff] == (
            initial_records
        )
    finally:
        original_error = sys.exc_info()[1]
        failure = (
            None
            if original_error is None
            else {"type": type(original_error).__name__, "error": str(original_error)[:2000]}
        )
        try:
            errors = retain_engine_proof(
                tmp_path,
                store,
                paper,
                worker,
                initial_records,
                initial_cutoff,
                original_controls,
                failure,
            )
        except Exception as exc:
            errors = [
                {"artifact": "capture_owner", "type": type(exc).__name__, "error": str(exc)[:1000]}
            ]
            print(json.dumps(errors), file=sys.stderr)
        try:
            f.close()
        except Exception as exc:
            if original_error is None:
                raise
            close_error = {"type": type(exc).__name__, "error": str(exc)[:1000]}
            try:
                (tmp_path / "actual-method-close-error.json").write_text(
                    json.dumps(close_error), encoding="utf-8"
                )
            except OSError:
                print(json.dumps(close_error), file=sys.stderr)
        if errors and original_error is None:
            pytest.fail("Disposable proof capture failed; exact capture errors retained")
