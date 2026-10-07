"""Causal idle-question selection; synthetic inputs/callbacks never prove model quality."""

import asyncio
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal as D
from threading import Barrier
from types import SimpleNamespace

import pytest
from test_continuous_audit import range_bars
from test_development_latency_measurement import protected_status
from test_paper_engine import START, frame
from test_paper_pilot_worker import workspace as workspace
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_role_tool_requests import CapabilityFixture, catalog_denial
from test_role_worker import make_lab

from trading.autonomous_spec import LabPolicy, RuleSpec
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.lab_role_contract import CAPABILITY_VERSION, contract_hash
from trading.local_role_model import development_latency_observation
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker
from trading.rule_components import reviewed_feature


def abstention(action="no_change"):
    return {
        "action": action,
        "capability": None,
        "evidence_ids": ["e2"],
        "mechanism": "Test the frozen range comparison only on causal subsequent inputs.",
        "falsification": "Reject benefit unless the matched outcome clears all declared costs.",
        "rationale": "Current range eligibility is not evidence of profitable future returns.",
        "dependency": None,
        "unsupported_basis": None,
        "tool_request": None,
    }


class SelectionFixture(CapabilityFixture):
    """Explicit synthetic future authority; no operating grant or inference backend."""

    def __init__(self, answer=None):
        super().__init__(answer or abstention())
        self.authority = {
            "question_policy": "evidence-question-selection-v1",
            "grant_id": self.grant_id,
            "grant_sha": "a" * 64,
            "profile_sha": "b" * 64,
            "contract_version": CAPABILITY_VERSION,
            "contract_sha": contract_hash(CAPABILITY_VERSION),
        }

    def selection_authority(self):
        return copy.deepcopy(self.authority)


def causal_frame(now, bars, *, sequence=1, quantity="100"):
    """Typed input observation for explicit synthetic closed-bar fixture inputs."""
    value = frame(now, "99.5", sequence, quantity)
    value["entry_allowed"] = True  # Explicit synthetic current instrument/entry tier.
    risk = reviewed_feature(bars, now, RuleSpec(), "paper-rest-ioc-v1")
    value["diagnostic_risk_input_valid"] = (
        risk.get("closed_bars", 0) >= 305
        and "atr" in risk
        and 0 < now * 1000 - bars[-1].close_ms <= 90000
        and all(b.open_ms - a.open_ms == 60000 for a, b in zip(bars, bars[1:], strict=False))
    )
    return value


@pytest.fixture
def selection(workspace):
    worker, clock, directory = workspace
    worker.transport = SelectionFixture()
    paper = worker.controller.paper
    bars = range_bars(clock[0], 60)
    inputs = {"bars": bars, "frame": causal_frame(clock[0], bars)}
    paper.lab_history = lambda now, horizon: list(inputs["bars"])
    paper.control_frames = lambda: {"BTCUSD": inputs["frame"]} if inputs["frame"] else {}
    paper.ready_at = clock[0] - 60
    paper._candle_errors = {}
    return worker, clock, directory, inputs


def selected_tasks(worker):
    return [
        worker.get(row["id"])
        for row in worker.registry.db.execute(
            "SELECT id,context FROM role_tasks ORDER BY created,id"
        ).fetchall()
        if json.loads(row["context"]).get("question_selection")
    ]


def selection_rows(worker):
    return [
        tuple(row)
        for row in worker.registry.db.execute(
            "SELECT * FROM role_question_selections ORDER BY selection_sha"
        ).fetchall()
    ]


def raw_rows(worker, table):
    return [tuple(row) for row in worker.registry.db.execute("SELECT * FROM " + table)]


def later_inputs(selection, *, seconds=None):
    worker, clock, _, inputs = selection
    policy = worker.controller.paper.state["autonomous_lab"]["policy"]
    clock[0] += seconds if seconds is not None else policy["horizon_seconds"] + 60
    inputs["bars"] = range_bars(clock[0], 60)
    inputs["frame"] = causal_frame(clock[0], inputs["bars"], sequence=int(clock[0]))
    worker.controller.paper.state["last_tick"] = clock[0]


def test_first_question_has_actual_causal_cost_basis_and_no_financial_or_model_effect(selection):
    worker, clock, _, inputs = selection
    spec = RuleSpec(family="range_reversion")
    policy = worker.controller.paper.state["autonomous_lab"]["policy"]
    feature = reviewed_feature(inputs["bars"], clock[0], spec, policy["execution_profile"])
    assert feature["eligible"] is True
    assert feature["excursion_bps"] > feature["modeled_hurdle_bps"] > 0
    state = copy.deepcopy(worker.controller.paper.state)
    worker.knowledge = SimpleNamespace(
        retrieve=lambda *a, **kw: pytest.fail("Pilot selector cannot authorize RAG")
    )
    assert worker.select_fresh_question(clock[0]) == 1
    (task,) = selected_tasks(worker)
    basis = task["context"]["question_selection"]
    assert task["stage"] == "idea" and task["status"] == "queued"
    assert basis["authority"] == worker.transport.authority
    assert basis["method"] == "r1" and len(basis["scope_sha"]) == 64
    assert len(basis["selection_sha"]) == len(basis["source_sha"]) == 64
    assert basis["source_end"] == inputs["bars"][-1].close_ms / 1000
    assert basis["source_start"] < basis["source_end"] < clock[0]
    assert basis["source_count"] == len(inputs["bars"])
    assert basis["reason"] and basis["falsification"] and basis["limitations"]
    assert task["context"]["catalog"]["r1"]["strategy"] == spec.model_dump()
    assert task["context"]["catalog"]["r1"]["reference"] == RuleSpec().model_dump()
    assert task["context"]["tool_evidence"]["features"]["r1"] == feature
    assert "knowledge" not in task["context"]
    assert task["attempts"] == [] and worker.transport.calls == []
    assert raw_rows(worker, "role_attempt_allowances") == []
    assert worker.controller.paper.state == state
    assert len(selection_rows(worker)) == 1


@pytest.mark.parametrize("advance_at", [1, 2], ids=["preparation", "publication"])
@pytest.mark.parametrize("replace_state", [False, True], ids=["same-state", "published-state"])
def test_successful_admission_can_advance_tick_without_moving_causal_cutoff(
    selection, advance_at, replace_state
):
    worker, clock, _, inputs = selection
    paper = worker.controller.paper
    cutoff = clock[0]
    state_before = copy.deepcopy(paper.state)
    source_sha = fingerprint([str(bar) for bar in inputs["bars"]])
    callbacks = []

    def admitted():
        callbacks.append(clock[0])
        if len(callbacks) == advance_at:
            clock[0] += 0.25
            if replace_state:
                paper.state = copy.deepcopy(paper.state)
            paper.state["last_tick"] = clock[0]
        return True

    worker.paper_admission = admitted
    assert worker.select_fresh_question(cutoff) == 1
    (task,) = selected_tasks(worker)
    original = copy.deepcopy(task)
    state = copy.deepcopy(paper.state)
    assert len(callbacks) == 2 and clock[0] > cutoff
    assert task["created"] == task["context"]["tool_evidence"]["observed_at"] == cutoff
    assert task["context"]["question_selection"]["source_sha"] == source_sha
    assert task["context"]["question_selection"]["source_end"] < cutoff
    assert task["attempts"] == [] and worker.transport.calls == []
    assert raw_rows(worker, "role_attempt_allowances") == []
    assert worker.select_fresh_question(clock[0]) == 0
    assert selected_tasks(worker) == [original] and len(selection_rows(worker)) == 1
    assert paper.state == state
    state_before["last_tick"] = state["last_tick"]  # Only the fixture's paper tick advanced.
    assert state == state_before


def test_current_quote_snapshot_can_advance_without_moving_causal_feature_time(selection):
    worker, clock, _, inputs = selection
    paper = worker.controller.paper
    cutoff = clock[0]
    state_before = copy.deepcopy(paper.state)
    policy = paper.state["autonomous_lab"]["policy"]
    feature = reviewed_feature(
        inputs["bars"], cutoff, RuleSpec(family="range_reversion"), policy["execution_profile"]
    )
    observations = []

    def current_frames():
        clock[0] += 0.25
        paper.state["last_tick"] = clock[0]
        value = causal_frame(cutoff, inputs["bars"], sequence=len(observations) + 1)
        value["observed"] = clock[0]
        observations.append(value["observed"])
        return {"BTCUSD": value}

    paper.control_frames = current_frames
    assert worker.select_fresh_question(cutoff) == 1
    (task,) = selected_tasks(worker)
    assert len(observations) >= 3 and min(observations) > cutoff
    assert task["context"]["tool_evidence"]["observed_at"] == cutoff
    assert task["context"]["tool_evidence"]["features"]["r1"] == feature
    assert task["context"]["question_selection"]["source_end"] < cutoff
    assert task["context"]["tool_evidence"]["executable_book"]["observed"] > cutoff
    assert task["attempts"] == [] and worker.transport.calls == []
    assert raw_rows(worker, "role_attempt_allowances") == []
    state_before["last_tick"] = clock[0]  # Only the fixture's paper tick advanced.
    assert paper.state == state_before


@pytest.mark.parametrize("owner", ["tick", "book"])
def test_observation_value_is_captured_before_clock_can_see_a_later_publication(
    selection, monkeypatch, owner
):
    worker, clock, _, inputs = selection
    paper = worker.controller.paper
    cutoff = clock[0]
    policy = paper.state["autonomous_lab"]["policy"]
    observed = []

    def observation_clock():
        stamp = clock[0]
        observed.append(stamp)
        clock[0] += 0.25
        paper.state["last_tick"] = clock[0]
        inputs["frame"]["observed"] = clock[0]
        return stamp

    monkeypatch.setattr("trading.role_worker.time.time", observation_clock)
    if owner == "tick":
        worker._selection_room(worker.transport.authority, policy, cutoff)
    else:
        source = worker._selection_source("short", policy, cutoff)
        assert source["source_end"] < cutoff
        assert source["source_sha"] == fingerprint([str(bar) for bar in inputs["bars"]])
    assert observed == [cutoff] and clock[0] > cutoff
    assert raw_rows(worker, "role_tasks") == raw_rows(worker, "role_requests") == []
    assert raw_rows(worker, "role_attempt_allowances") == [] and worker.transport.calls == []


@pytest.mark.parametrize("owner,limit", [("tick", 10), ("book", 5)])
@pytest.mark.parametrize(
    "age,admitted", [(None, False), (-0.001, False), (0, True), ("limit", True), ("stale", False)]
)
def test_current_observation_keeps_exact_missing_future_and_age_boundaries(
    selection, owner, limit, age, admitted
):
    worker, clock, _, inputs = selection
    paper = worker.controller.paper
    cutoff = clock[0]
    clock[0] += 1
    paper.state["last_tick"] = clock[0]
    inputs["frame"]["observed"] = clock[0]
    age = limit if age == "limit" else limit + 0.001 if age == "stale" else age
    observation, key = (
        (paper.state, "last_tick") if owner == "tick" else (inputs["frame"], "observed")
    )
    if age is None:
        del observation[key]
    else:
        observation[key] = clock[0] - age
    state = copy.deepcopy(paper.state)
    assert worker.select_fresh_question(cutoff) == int(admitted)
    assert len(selected_tasks(worker)) == len(selection_rows(worker)) == int(admitted)
    assert raw_rows(worker, "role_attempt_allowances") == []
    assert worker.transport.calls == [] and paper.state == state


def test_later_current_observation_does_not_adopt_bars_after_original_cutoff(selection):
    worker, clock, _, inputs = selection
    paper = worker.controller.paper
    cutoff = clock[0]
    clock[0] += 120
    paper.state["last_tick"] = clock[0]
    inputs["bars"] = range_bars(clock[0], 60)
    inputs["frame"] = causal_frame(clock[0], inputs["bars"])
    state = copy.deepcopy(paper.state)
    assert worker.select_fresh_question(cutoff) == 0
    assert "causal coverage" in worker.question_selection_status()["reason"]
    assert raw_rows(worker, "role_tasks") == raw_rows(worker, "role_requests") == []
    assert raw_rows(worker, "role_attempt_allowances") == []
    assert worker.transport.calls == [] and paper.state == state


def test_old_grant_cannot_silently_enable_fresh_production(selection):
    worker, clock, _, _ = selection
    worker.transport.authority = None
    before = copy.deepcopy(worker.controller.paper.state)
    for _ in range(3):
        assert worker.select_fresh_question(clock[0]) == 0
    assert raw_rows(worker, "role_tasks") == raw_rows(worker, "role_requests") == []
    assert worker.transport.calls == [] and worker.controller.paper.state == before


@pytest.mark.parametrize(
    "failure",
    [
        "insufficient",
        "gap",
        "future",
        "stale_bars",
        "flat",
        "missing_book",
        "stale_book",
        "empty_book",
        "bootstrap",
        "candle_error",
        "typed_input_false",
        "typed_input_missing",
        "typed_input_null",
        "typed_input_integer",
        "typed_input_string",
        "entry_missing",
        "entry_false",
        "entry_null",
        "entry_integer",
        "entry_string",
        "paper_stopped",
        "paper_error",
        "paper_stale",
        "paused",
        "proposals_paused",
        "admission_false",
    ],
)
def test_unusable_inputs_never_become_questions_despite_retained_numeric_atr(selection, failure):
    worker, clock, _, inputs = selection
    paper = worker.controller.paper
    if failure == "insufficient":
        inputs["bars"] = inputs["bars"][-20:]
    elif failure == "gap":
        del inputs["bars"][-10]
    elif failure == "future":
        inputs["bars"] = range_bars(clock[0] + 120, 60)
    elif failure == "stale_bars":
        inputs["bars"] = range_bars(clock[0] - 180, 60)
    elif failure == "flat":
        inputs["bars"] = [
            type(bar)(bar.open_ms, D(100), D(100), D(100), D(100), bar.volume, bar.close_ms)
            for bar in inputs["bars"]
        ]
    elif failure == "missing_book":
        inputs["frame"] = None
    elif failure == "stale_book":
        inputs["frame"]["observed"] = clock[0] - 6
    elif failure == "empty_book":
        inputs["frame"]["book"] = replace(inputs["frame"]["book"], asks=())
    elif failure == "bootstrap":
        paper.ready_at = clock[0] + 1
    elif failure == "candle_error":
        paper._candle_errors["BTCUSD"] = "Explicit synthetic source failure"
    elif failure == "typed_input_false":
        inputs["frame"]["diagnostic_risk_input_valid"] = False
    elif failure == "typed_input_missing":
        del inputs["frame"]["diagnostic_risk_input_valid"]
    elif failure == "typed_input_null":
        inputs["frame"]["diagnostic_risk_input_valid"] = None
    elif failure == "typed_input_integer":
        inputs["frame"]["diagnostic_risk_input_valid"] = 1
    elif failure == "typed_input_string":
        inputs["frame"]["diagnostic_risk_input_valid"] = "true"
    elif failure == "entry_missing":
        del inputs["frame"]["entry_allowed"]
    elif failure.startswith("entry_"):
        inputs["frame"]["entry_allowed"] = {
            "entry_false": False,
            "entry_null": None,
            "entry_integer": 1,
            "entry_string": "true",
        }[failure]
    elif failure == "paper_stopped":
        paper.running = False
    elif failure == "paper_error":
        paper.error = "Explicit synthetic financial worker error"
    elif failure == "paper_stale":
        paper.state["last_tick"] = clock[0] - 11
    elif failure == "paused":
        paper.state["paused"] = True
    elif failure == "proposals_paused":
        paper.state["autonomous_lab"]["proposals_paused"] = True
    else:
        worker.paper_admission = lambda: False
    state = copy.deepcopy(paper.state)
    assert worker.select_fresh_question(clock[0]) == 0
    assert raw_rows(worker, "role_tasks") == raw_rows(worker, "role_requests") == []
    assert raw_rows(worker, "role_attempt_allowances") == []
    assert worker.transport.calls == [] and paper.state == state


@pytest.mark.parametrize(
    "condition", ["journal_missing", "audit_stale", "readback_error", "recording", "storage"]
)
def test_actual_protected_observation_refuses_missing_financial_or_storage_authority(
    selection, condition
):
    worker, clock, _, _ = selection
    status = protected_status()
    paper = status["paper"]
    if condition == "journal_missing":
        del paper["journal"]["available"]
    elif condition == "audit_stale":
        paper["journal"]["audit_age_seconds"] = 120
    elif condition == "readback_error":
        paper["performance"]["financial_readback"]["error"] = "Synthetic readback failed"
    elif condition == "recording":
        paper["research_evidence"]["state"] = "paused"
    else:
        paper["research_evidence"]["storage"]["free_bytes"] = 1
    observed = development_latency_observation(status)
    assert observed["admitted"] is False
    worker.paper_admission = lambda: observed["admitted"]
    assert worker.select_fresh_question(clock[0]) == 0
    assert raw_rows(worker, "role_tasks") == [] and worker.transport.calls == []


def test_latency_advisory_does_not_authorize_nonlatency_faults_or_force_calls(selection):
    worker, clock, _, _ = selection
    observed = development_latency_observation(protected_status())
    assert observed["admitted"] and observed["research_constrained"]
    worker.paper_admission = lambda: observed["admitted"]
    assert worker.select_fresh_question(clock[0]) == 1
    assert worker.transport.calls == [] and selected_tasks(worker)[0]["attempts"] == []


def test_same_source_poll_restart_and_one_new_bar_do_not_retry_completed_abstention(selection):
    worker, clock, _, inputs = selection
    assert worker.select_fresh_question(clock[0]) == 1
    task = selected_tasks(worker)[0]
    assert asyncio.run(worker.step(clock[0]))
    original = copy.deepcopy(worker.get(task["id"]))
    assert original["result"]["action"] == "no_change"
    retained = selection_rows(worker)
    allowances = raw_rows(worker, "role_attempt_allowances")
    replacement = RoleWorker(worker.registry, worker.controller, worker.transport)
    replacement.enabled = True
    replacement.paper_admission = worker.paper_admission
    for _ in range(100):
        inputs["frame"]["observed"] = clock[0]
        assert replacement.select_fresh_question(clock[0]) == 0
    later_inputs(selection, seconds=60)
    assert replacement.select_fresh_question(clock[0]) == 0
    assert replacement.get(task["id"]) == original
    assert selection_rows(replacement) == retained
    assert raw_rows(replacement, "role_attempt_allowances") == allowances
    assert len(worker.transport.calls) == 1


def test_later_covered_block_after_valid_no_change_has_distinct_falsifiable_identity(selection):
    worker, clock, _, _ = selection
    assert worker.select_fresh_question(clock[0]) == 1
    first = selected_tasks(worker)[0]
    assert asyncio.run(worker.step(clock[0]))
    original = copy.deepcopy(worker.get(first["id"]))
    allowances = raw_rows(worker, "role_attempt_allowances")
    later_inputs(selection)
    assert worker.select_fresh_question(clock[0]) == 1
    tasks = selected_tasks(worker)
    assert len(tasks) == 2 and tasks[0]["id"] != tasks[1]["id"]
    before = tasks[0]["context"]["question_selection"]
    after = tasks[1]["context"]["question_selection"]
    assert before["scope_sha"] == after["scope_sha"]
    assert before["source_sha"] != after["source_sha"]
    assert (
        after["source_end"] - before["source_end"]
        >= (worker.controller.paper.state["autonomous_lab"]["policy"]["horizon_seconds"])
    )
    assert worker.get(first["id"]) == original
    assert raw_rows(worker, "role_attempt_allowances") == allowances
    assert len(worker.transport.calls) == 1


@pytest.mark.parametrize("outcome", ["unsupported", "invalid", "unknown"])
def test_adverse_or_unresolved_answer_never_produces_preferred_answer_retry(selection, outcome):
    worker, clock, _, _ = selection
    assert worker.select_fresh_question(clock[0]) == 1
    task = selected_tasks(worker)[0]
    if outcome == "unknown":
        with worker.registry.transaction():
            worker.registry.db.execute(
                "INSERT INTO role_attempts(task,stage,attempt,started,status,profile,packet,"
                "wall_reserved,tokens_reserved) VALUES(?,'idea',1,?,'running','{}','{}',5,8192)",
                (task["id"], clock[0]),
            )
    else:
        worker.transport.answer = (
            catalog_denial()
            if outcome == "invalid"
            else (
                abstention("unsupported_capability")
                | {"unsupported_basis": {"kind": "feature", "identifier": "order_flow_imbalance"}}
            )
        )
        assert asyncio.run(worker.step(clock[0])) is (outcome == "unsupported")
    original = copy.deepcopy(worker.get(task["id"]))
    allowances = raw_rows(worker, "role_attempt_allowances")
    later_inputs(selection)
    assert worker.select_fresh_question(clock[0]) == 0
    assert selected_tasks(worker) == [original]
    assert raw_rows(worker, "role_attempt_allowances") == allowances


@pytest.mark.parametrize("stage", ["idea", "evaluate", "outcome", "data_wait", "tool_wait"])
def test_unresolved_manual_task_or_wait_has_priority_over_fresh_production(selection, stage):
    worker, clock, _, _ = selection
    task = worker.enqueue(Question(question="Retain an existing explicit research dependency."))
    if stage != "idea":
        worker._update(task, stage, "waiting", result={"fixture": "Unresolved original owner"})
    original = copy.deepcopy(worker.get(task["id"]))
    assert worker.select_fresh_question(clock[0]) == 0
    assert raw_rows(worker, "role_question_selections") == []
    assert worker.get(task["id"]) == original and worker.transport.calls == []


def test_atomic_selection_rolls_back_task_request_and_index_on_publication_failure(selection):
    worker, clock, _, _ = selection
    before = {
        table: raw_rows(worker, table)
        for table in (
            "role_tasks",
            "role_requests",
            "role_question_selections",
            "experiment_events",
        )
    }
    worker.registry.db.execute(
        "CREATE TEMP TRIGGER reject_selection BEFORE INSERT ON role_question_selections "
        "BEGIN SELECT RAISE(ABORT,'Synthetic selection publication failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="Synthetic selection"):
        worker.select_fresh_question(clock[0])
    assert {table: raw_rows(worker, table) for table in before} == before
    worker.registry.db.execute("DROP TRIGGER reject_selection")
    assert worker.select_fresh_question(clock[0]) == 1
    assert len(selected_tasks(worker)) == len(selection_rows(worker)) == 1
    with pytest.raises(sqlite3.IntegrityError):
        worker.registry.db.execute("DELETE FROM role_question_selections")


def test_two_registry_owners_publish_only_one_question_and_one_receipt(selection):
    worker, clock, _, _ = selection
    second_registry = ExperimentRegistry(worker.registry.path)
    second = RoleWorker(second_registry, worker.controller, worker.transport)
    second.enabled = True
    second.paper_admission = worker.paper_admission
    start = Barrier(3)

    def select(owner):
        start.wait(timeout=5)
        return owner.select_fresh_question(clock[0])

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(select, owner) for owner in (worker, second)]
            start.wait(timeout=5)
            assert sum(call.result(timeout=10) for call in calls) == 1
        assert len(selected_tasks(worker)) == len(selection_rows(worker)) == 1
        assert len(raw_rows(worker, "role_requests")) == 1
        assert raw_rows(worker, "role_attempt_allowances") == []
    finally:
        second_registry.close()


@pytest.mark.parametrize("drift", ["source", "policy", "authority"])
def test_prepared_candidate_cannot_publish_after_source_or_authority_drift(selection, drift):
    worker, clock, _, inputs = selection
    bundle = worker.controller.bundle
    prepared = []

    def changed(now):
        prepared.append(now)
        issued = bundle(now)
        if drift == "source":
            del inputs["bars"][-10]
        elif drift == "policy":
            worker.controller.paper.state["autonomous_lab"]["policy"] = LabPolicy(
                request_id="changed-during-source-preparation"
            ).model_dump(mode="json")
        else:
            worker.transport.authority["grant_sha"] = "e" * 64
        return issued

    worker.controller.bundle = changed
    assert worker.select_fresh_question(clock[0]) == 0
    assert prepared == [clock[0]]
    for table in (
        "role_tasks",
        "role_requests",
        "role_question_selections",
        "role_attempt_allowances",
    ):
        assert raw_rows(worker, table) == []
    assert worker.transport.calls == []


def test_lost_creation_acknowledgment_reopens_one_atomic_selection(selection, monkeypatch):
    worker, clock, _, _ = selection
    original_get = worker.get

    def lost_ack(identity):
        original_get(identity)
        raise OSError("Synthetic detail acknowledgment lost after committed publication")

    monkeypatch.setattr(worker, "get", lost_ack)
    with pytest.raises(OSError, match="acknowledgment lost"):
        worker.select_fresh_question(clock[0])
    assert len(selection_rows(worker)) == len(raw_rows(worker, "role_requests")) == 1
    monkeypatch.setattr(worker, "get", original_get)
    original = copy.deepcopy(selected_tasks(worker)[0])
    replacement = RoleWorker(worker.registry, worker.controller, worker.transport)
    replacement.enabled = True
    replacement.paper_admission = worker.paper_admission
    assert replacement.select_fresh_question(clock[0]) == 0
    assert selected_tasks(replacement) == [original]
    assert len(selection_rows(replacement)) == 1
    assert worker.transport.calls == []


def test_daily_question_ceiling_is_not_renewed_by_later_source_or_restart(selection):
    worker, clock, _, _ = selection
    worker.controller.paper.state["autonomous_lab"]["policy"] = LabPolicy(
        request_id="one-question-daily-fixture", daily_trials=1
    ).model_dump(mode="json")
    assert worker.select_fresh_question(clock[0]) == 1
    assert asyncio.run(worker.step(clock[0]))
    later_inputs(selection)
    replacement = RoleWorker(worker.registry, worker.controller, worker.transport)
    replacement.enabled = True
    replacement.paper_admission = worker.paper_admission
    assert replacement.select_fresh_question(clock[0]) == 0
    assert len(selection_rows(replacement)) == len(selected_tasks(replacement)) == 1
    assert len(worker.transport.calls) == 1


def test_normal_maintenance_retains_selection_reason_instead_of_generic_recovery(selection):
    worker, clock, _, _ = selection
    asyncio.run(worker._maintain("questions", worker.select_fresh_question))
    status = worker.question_selection_status()
    assert status["state"] == "selected" and status["reason"]
    assert len(selected_tasks(worker)) == 1 and worker.transport.calls == []
    worker._supervision("questions", "Synthetic permanent registry failure", 0, "failed")
    status = worker.question_selection_status()
    assert status["state"] == "unavailable" and status["reason"]


def mature_fixture(worker, clock, task, *, different_followup=False):
    """Synthetic recorded outcome only; no actual paper comparison or returns."""
    method = task["context"]["catalog"]["r1"]
    proposal = {
        "request_id": "synthetic-selection-lesson-proposal",
        "parent_trial": None,
        "mechanism": "A saved synthetic comparison, without economic or causal benefit proof.",
        "strategy": method["strategy"],
        "reference": method["reference"],
    }
    score = {
        "proposal_id": proposal["request_id"],
        "outcome": "inconclusive",
        "reason": "Synthetic saved outcome only; no actual paper comparison.",
        "available_at": clock[0],
        "window_start": clock[0] - 3600,
        "net_after_operating_usd": {"candidate": "-1", "reference": "-1"},
        "delta_usd": "0",
        "passive_usd": "0",
        "cash_usd": "-1",
        "operating_each_usd": "1",
        "fees_treatment": "Synthetic values only",
        "coverage_seconds": 3600,
    }
    followup = abstention()
    if different_followup:
        followup = followup | {"action": "propose_experiment", "capability": "r0"}
    worker._update(
        task,
        "complete",
        "done",
        proposal=proposal,
        result={
            "outcome": {"body": score, "sha256": fingerprint(score)},
            "followup": followup,
        },
    )
    return worker.get(task["id"])


def test_compatible_recorded_lesson_watermark_survives_verified_archive(selection, monkeypatch):
    """Synthetic recorded outcome proves provenance retention, not strategy benefit."""
    worker, clock, directory, _ = selection
    save_plan(directory, plan_at(directory))
    assert worker.select_fresh_question(clock[0]) == 1
    task = selected_tasks(worker)[0]
    assert asyncio.run(worker.step(clock[0]))
    mature_fixture(worker, clock, worker.get(task["id"]))
    retained = worker.get(task["id"])
    lesson_id = worker.lessons.record(retained)
    authority = worker.transport.selection_authority()
    policy = worker.controller.paper.state["autonomous_lab"]["policy"]
    before = worker._selection_lesson(authority, policy, "short")
    assert before["id"] == lesson_id
    assert worker.select_followups()["selected"] == 0
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    worker.history.rollover()
    compact = worker.registry.db.execute(
        "SELECT archive_reference FROM role_tasks WHERE id=?", (task["id"],)
    ).fetchone()
    assert compact["archive_reference"]
    replacement = RoleWorker(worker.registry, worker.controller, worker.transport)
    replacement.enabled = True
    replacement.paper_admission = worker.paper_admission
    assert replacement._selection_lesson(authority, policy, "short") == before
    assert replacement.get(task["id"])["attempts"] == retained["attempts"]
    assert replacement.get(task["id"])["result"] == retained["result"]
    later_inputs(selection)
    assert replacement.select_fresh_question(clock[0]) == 1
    new = selected_tasks(replacement)[-1]
    assert new["context"]["question_selection"]["lesson"] == before
    assert len(worker.transport.calls) == 1


@pytest.mark.parametrize("changed", ["grant_sha", "profile_sha"])
@pytest.mark.parametrize("stage", ["queued", "data_wait", "mature_followup"])
def test_same_id_replaced_full_authority_cannot_lease_resume_or_consume_old_work(
    selection, changed, stage
):
    worker, clock, _, _ = selection
    if stage == "data_wait":
        worker.transport.answer = abstention("request_data") | {"dependency": "new_closed_bars"}
    assert worker.select_fresh_question(clock[0]) == 1
    task = selected_tasks(worker)[0]
    if stage != "queued":
        assert asyncio.run(worker.step(clock[0]))
    if stage == "mature_followup":
        mature_fixture(worker, clock, worker.get(task["id"]), different_followup=True)
    original = copy.deepcopy(worker.get(task["id"]))
    tables = (
        "role_tasks",
        "role_attempts",
        "role_attempt_allowances",
        "role_requests",
        "role_followups",
        "research_lessons",
        "research_selection",
        "evidence_windows",
    )
    before = {table: raw_rows(worker, table) for table in tables}
    worker.transport.authority[changed] = "f" * 64
    later_inputs(selection)
    assert not asyncio.run(worker.step(clock[0]))
    assert worker.resume_sources(clock[0]) == 0
    assert worker.select_followups() == {"selected": 0, "waiting": 0}
    page = worker.page()
    assert page["current_task"] is None
    assert page["activity"]["queued"] == page["activity"]["pending_data"] == 0
    assert worker.question_selection_status()["state"] == "waiting"
    assert worker.get(task["id"]) == original
    assert {table: raw_rows(worker, table) for table in tables} == before
    assert len(worker.transport.calls) == (0 if stage == "queued" else 1)


@pytest.mark.parametrize("change", ["grant", "profile", "policy"])
def test_replaced_authority_cannot_adopt_old_selection_or_rewrite_original(selection, change):
    worker, clock, _, _ = selection
    assert worker.select_fresh_question(clock[0]) == 1
    task = selected_tasks(worker)[0]
    original = copy.deepcopy(worker.get(task["id"]))
    if change == "grant":
        worker.transport.grant_id = "replacement-synthetic-grant"
        worker.transport.authority["grant_id"] = worker.transport.grant_id
        worker.transport.authority["grant_sha"] = "c" * 64
    elif change == "profile":
        worker.transport.authority["profile_sha"] = "d" * 64
    else:
        paper = worker.controller.paper
        paper.state["autonomous_lab"]["policy"] = LabPolicy(
            request_id="replacement-selection-policy"
        ).model_dump(mode="json")
    worker.select_fresh_question(clock[0])
    assert worker.get(task["id"]) == original
    assert (
        original["context"]["question_selection"]["authority"] != (worker.transport.authority)
        or change == "policy"
    )
    assert raw_rows(worker, "role_attempt_allowances") == [] and worker.transport.calls == []


def test_selector_is_financially_neutral_with_actual_disposable_pending_and_partial_fill(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(store, tmp_path)
    lab.paper.history["BTCUSD"] = range_bars(clock[0], 60)
    lab.paper.books = {"BTCUSD": causal_frame(clock[0], lab.paper.history["BTCUSD"])}
    model = SelectionFixture()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    worker.paper_admission = lambda: True  # Explicit isolated protected-owner fixture.
    try:
        feature = {"eligible": True, "atr": "1", "bar_open_ms": 1, "version": "breakout-v1"}
        lab.paper.state = store.transact(
            clock[0],
            lambda engine: engine.tick(lab.paper.books, {"BTCUSD": {"breakout-v1": feature}}),
        )
        primary = lab.paper.state["accounts"]["primary"]
        assert primary["pending"] and not primary["positions"]
        order = copy.deepcopy(primary["pending"]["BTCUSD"])
        assert D(order["quantity"]) > D("0.1") and D(order["reserved"]) > 0
        before = copy.deepcopy(store.read())
        assert worker.select_fresh_question(clock[0]) == 1
        assert store.read() == before
        clock[0] += 2
        lab.paper.books = {
            "BTCUSD": causal_frame(
                clock[0], lab.paper.history["BTCUSD"], sequence=2, quantity="0.1"
            )
        }
        lab.paper.state = store.transact(
            clock[0],
            lambda engine: engine.tick(lab.paper.books, {"BTCUSD": {"breakout-v1": feature}}),
        )
        primary = lab.paper.state["accounts"]["primary"]
        position = primary["positions"]["BTCUSD"]
        assert 0 < D(position["quantity"]) < D(order["quantity"])
        # Native IOC semantics cancel the unfilled remainder and release its reserve.
        assert not primary["pending"]
        assert D(primary["cash"]) + D(position["cost"]) == D(100)
        reserve = store.connection.execute(
            "SELECT coalesce(sum(amount),0) AS amount FROM paper_journal "
            "WHERE account='primary' AND asset='USD' AND bucket='reserved'"
        ).fetchone()
        assert reserve["amount"] == 0
        fills = [
            event
            for event in store.export(0, 1000, "primary")["records"]
            if event["kind"] == "fill" and event["account"] == "primary"
        ]
        assert len(fills) == 1 and fills[0]["body"]["partial"] is True
        assert D(fills[0]["body"]["unfilled_cancelled"]) == (
            D(order["quantity"]) - D(position["quantity"])
        )
        before = copy.deepcopy(store.read())
        assert worker.select_fresh_question(clock[0]) == 0
        assert store.read() == before and store.reconcile()["balanced"]
        assert model.calls == [] and raw_rows(worker, "role_attempt_allowances") == []
    finally:
        lab.registry.close()
