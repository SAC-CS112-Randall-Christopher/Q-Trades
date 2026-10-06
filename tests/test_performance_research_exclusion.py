"""Diagnostic paper activity is accounting/performance evidence, never research support."""

import copy
import json
from threading import RLock
from types import SimpleNamespace

import pytest
from test_llm_training import corpus, prepared, reseal, task
from test_memory_quality import fitted
from test_numerical_candidates import fixture_artifact
from test_paper_engine import START
from test_paper_learning import candidate_state, windows
from test_training_workflow import local, observed

from trading.account_purpose import (
    PERFORMANCE_DIAGNOSTIC_ACCOUNT as DIAGNOSTIC,
)
from trading.account_purpose import (
    PERFORMANCE_DIAGNOSTIC_PURPOSE as PURPOSE,
)
from trading.account_purpose import (
    PERFORMANCE_DIAGNOSTIC_VERSION as VERSION,
)
from trading.account_purpose import (
    event_research_eligible,
    require_research_provenance,
    research_account,
)
from trading.autonomous_finance import retire_account, slots, validate_parent
from trading.compact_memory import CompactMemory, journal_target, linked_events
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.llm_training import Candidate, candidate_from_task
from trading.paper_challengers import admit
from trading.paper_economics import begin, scores
from trading.paper_engine import PaperEngine, initial_state
from trading.paper_learning import comparison, designate, matched_control, retain_report, snapshot
from trading.paper_store import PaperStore
from trading.prospective_review import ProspectiveReview, ProspectiveSpec
from trading.research_evidence import canonical, digest
from trading.training_workflow import SourceSelection


def diagnostic_state():
    state = initial_state(START)
    diagnostic = copy.deepcopy(state["accounts"]["primary"])
    diagnostic.update(purpose=PURPOSE, version=VERSION, label="Performance Diagnostic")
    # Distinct fixture capital identifies any accidental diagnostic benchmark.
    diagnostic.update(
        cash="1000", equity="1000", funding="1000", starting_capital="1000", units="1000"
    )
    state["accounts"][DIAGNOSTIC] = diagnostic
    for account in state["accounts"].values():
        account.update(valuation_fresh=True, valuation_at=START, operating_daily_usd="0")
    return state


@pytest.mark.parametrize("purpose", [PURPOSE, "unknown", None, "", 7])
def test_explicit_nonresearch_purpose_never_grants_eligibility(purpose):
    assert not research_account({"purpose": purpose})
    assert research_account({}) and research_account({"purpose": "research"})


def test_reserved_identity_and_version_defend_missing_or_changed_marker():
    assert not research_account({}, DIAGNOSTIC)
    assert not research_account({"version": VERSION, "purpose": "research"})
    assert not event_research_eligible({"account": DIAGNOSTIC, "body": {"version": "breakout-v1"}})
    assert not event_research_eligible({"account": "other", "body": {"purpose": "unknown"}})


def test_economics_keeps_diagnostic_accounting_but_never_ranks_or_funds_its_benchmark():
    state = diagnostic_state()
    original = copy.deepcopy(state)
    window = begin(state, START)
    for benchmark in window["benchmarks"].values():
        benchmark.update(fresh=True, coverage=True)
        for leg in benchmark["legs"].values():
            leg["status"] = "cash"
    diagnostic = window["accounts"][DIAGNOSTIC]
    diagnostic["last"] = copy.deepcopy(diagnostic["last"])
    diagnostic["last"].update(equity="2000", nav="2", closed=999, wins=999)
    result = scores(window, START + 86400, complete=True)["scores"]
    assert result[DIAGNOSTIC]["net_pnl"] == "1000"
    assert result[DIAGNOSTIC]["eligible"] is False and result[DIAGNOSTIC]["rank"] is None
    assert any("excluded from research" in reason for reason in result[DIAGNOSTIC]["reasons"])
    assert not any(benchmark["capital"] == "1000" for benchmark in window["benchmarks"].values())
    assert result["primary"]["eligible"] is True and result["primary"]["rank"] == 1
    assert state == original
    assert slots(state)["used"] == slots(initial_state(START))["used"] + 1


@pytest.mark.parametrize("target", ["candidate", "control"])
def test_forged_research_artifact_cannot_make_diagnostic_comparison(target):
    engine, candidate, control = candidate_state()
    name = candidate if target == "candidate" else control
    engine.state["accounts"][name]["purpose"] = PURPOSE
    before = copy.deepcopy(engine.state)
    with pytest.raises(ValueError, match="excluded from research"):
        comparison(engine.state, candidate, [], START, 0)
    assert engine.state == before
    if target == "candidate":
        with pytest.raises(ValueError, match="excluded from research"):
            matched_control(engine, candidate)
        assert snapshot(engine.state)["accounts"] == []


def test_research_retirement_cannot_remove_diagnostic_even_with_forged_trial():
    state = diagnostic_state()
    state["accounts"][DIAGNOSTIC]["lab_trial"] = "forged-trial"
    engine = PaperEngine(state, START)
    before = copy.deepcopy(engine.state)
    with pytest.raises(ValueError, match="excluded from research"):
        retire_account(engine, DIAGNOSTIC, "forged research retirement")
    assert engine.state == before and engine.events == []


def test_diagnostic_parent_and_previously_eligible_designation_are_refused():
    state = diagnostic_state()
    state["autonomous_lab"] = {
        "trials": {"forged-parent": {"status": "preserved", "candidate": DIAGNOSTIC}}
    }
    with pytest.raises(ValueError, match="excluded from research"):
        validate_parent(state, SimpleNamespace(kind="variation", parent_trial="forged-parent"))
    engine, candidate, control = candidate_state()
    retained = windows(engine, candidate, control)
    engine.now = retained[-1]["end"]
    engine.state["evidence_kind"] = "observed_public_feed"
    report = comparison(engine.state, candidate, retained, engine.now, 0)
    assert report["decision"] == "eligible_for_paper_designation"
    receipt = retain_report(engine, "diagnostic-promotion-fixture", report)
    engine.state["accounts"][candidate]["purpose"] = PURPOSE
    with pytest.raises(ValueError, match="excluded from research"):
        designate(engine, receipt["request_id"], receipt["sha256"], 0)
    assert engine.state["learning"]["incumbent"] == "primary"


def event(account, kind="order_intent", at=100.0, **body):
    return {
        "account": account,
        "at": at,
        "kind": kind,
        "body": {
            "symbol": "BTCUSD",
            "version": "breakout-v1",
            "side": "buy",
            "created_at": 100.0,
            **body,
        },
    }


def test_compact_exclusion_preserves_original_financial_indices_and_records():
    events = [
        event(DIAGNOSTIC),
        event("primary"),
        event("unknown", purpose="unknown"),
        event("breakout-v1"),
    ]
    receipt = {
        "committed_at": 100.5,
        "events": [{"event_index": i, "event_id": 500 + i} for i in range(4)],
    }
    original = copy.deepcopy((events, receipt))
    linked = linked_events(events, receipt)
    assert [item["account"] for item in linked] == ["primary", "breakout-v1"]
    assert [item["reference"]["event_index"] for item in linked] == [1, 3]
    assert [item["reference"]["event_id"] for item in linked] == [501, 503]
    assert (events, receipt) == original


def closed_links(account, base_id):
    events = [
        event(account),
        event(account, "fill", 102.0),
        event(
            account,
            "trade_closed",
            200.0,
            opened_at=102.0,
            closed_at=200.0,
            cost="10",
            proceeds="11",
            pnl="1",
        ),
    ]
    return [
        dict(item, reference={"event_id": base_id + i}, committed_at=201.0)
        for i, item in enumerate(events)
    ]


def test_compact_append_and_manually_injected_labels_refuse_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.compact_memory.time.time", lambda: 2800.0)
    memory = CompactMemory(tmp_path / "compact.sqlite")
    diagnostic, legitimate = closed_links(DIAGNOSTIC, 1), closed_links("primary", 10)
    original = copy.deepcopy(diagnostic + legitimate)
    try:
        memory.append(
            {
                "at": 2800.0,
                "collected_at": 2800.0,
                "events": diagnostic + legitimate,
                "fresh": False,
            }
        )
        assert memory.db.execute("SELECT count(*) FROM compact_events").fetchone()[0] == 3
        # Bypass the intake to exercise the final label-selection defense too.
        with memory.db:
            for item in diagnostic:
                memory.db.execute(
                    "INSERT INTO compact_events VALUES(?,?,?,?)",
                    (item["reference"]["event_id"], 201.0, canonical(item), digest(item)),
                )
        target = journal_target(memory.db, 100.0, 2800.0, 2800.0)
        assert target["status"] == "available" and target["entry"]["account"] == "primary"
        diagnostic_only = CompactMemory(tmp_path / "diagnostic-only.sqlite")
        try:
            with diagnostic_only.db:
                for item in diagnostic:
                    diagnostic_only.db.execute(
                        "INSERT INTO compact_events VALUES(?,?,?,?)",
                        (item["reference"]["event_id"], 201.0, canonical(item), digest(item)),
                    )
            assert (
                journal_target(diagnostic_only.db, 100.0, 2800.0, 2800.0)["status"] == "unavailable"
            )
        finally:
            diagnostic_only.close()
        assert diagnostic + legitimate == original
    finally:
        memory.close()


def test_diagnostic_research_snapshot_refuses_before_outcome_queries():
    store = PaperStore.__new__(PaperStore)
    store.transaction_lock = RLock()
    calls = []
    saved = diagnostic_state()["accounts"][DIAGNOSTIC]

    def execute(sql, parameters):
        calls.append((sql, parameters))
        return SimpleNamespace(
            fetchone=lambda: {"revision": 1, "account": saved, "state_at": START}
        )

    store.connection = SimpleNamespace(execute=execute)
    with pytest.raises(ValueError, match="excluded from research"):
        store.research_account(DIAGNOSTIC, START)
    assert len(calls) == 1
    forged = {"account": DIAGNOSTIC, "state": saved}
    with pytest.raises(ValueError, match="excluded from research"):
        store.research_outcomes(forged, "BTCUSD")
    with pytest.raises(ValueError, match="excluded from research"):
        store.research_cost_groups(forged, "BTCUSD", start=0)
    assert len(calls) == 1


def test_prospective_plan_omits_diagnostic_and_refuses_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.prospective_review.time.time", lambda: START)
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    owner = ProspectiveReview(registry)
    state = diagnostic_state()
    with pytest.raises(ValueError, match="excluded from research"):
        owner.freeze(
            ProspectiveSpec(
                request_id="diagnostic-candidate-plan",
                name="Forged diagnostic",
                starts_at=START + 3600,
                candidate=DIAGNOSTIC,
            ),
            state,
        )
    plan = owner.freeze(
        ProspectiveSpec(
            request_id="diagnostic-baseline-plan", name="Baseline fixture", starts_at=START + 3600
        ),
        state,
    )
    assert DIAGNOSTIC not in plan["configurations"] and "primary" in plan["configurations"]


def test_diagnostic_task_export_selection_and_preparation_refuse_provenance(tmp_path):
    original = task()
    packet = json.loads(original["attempts"][0]["packet"])
    packet["evidence"]["e0"]["purpose"] = PURPOSE
    original["attempts"][0]["packet"] = json.dumps(packet)
    with pytest.raises(ValueError, match="excluded from research"):
        candidate_from_task(original, "idea", 1)
    rows = corpus()
    candidate = rows[0]["candidate"]
    candidate["packet"]["evidence"]["e0"].update(account=DIAGNOSTIC)
    reseal(candidate)
    with pytest.raises(ValueError, match="excluded from research"):
        Candidate.model_validate(candidate)
    with pytest.raises(ValueError, match="excluded from research"):
        prepared(rows)
    workflow = local(tmp_path)
    workflow.roles = SimpleNamespace(training_candidate=lambda *args: {"candidate": candidate})
    with pytest.raises(ValueError, match="excluded from research"):
        workflow.select(
            SourceSelection(
                kind="model_attempt", identity="diagnostic-task", stage="idea", attempt=1
            )
        )
    assert (
        workflow.registry.db.execute("SELECT count(*) FROM training_candidates").fetchone()[0] == 0
    )


def test_shared_market_observations_remain_eligible_while_diagnostic_exists(tmp_path):
    workflow = local(tmp_path)
    result = observed(workflow)
    require_research_provenance(result)
    assert result["candidate"]["source_kind"] == "observed_episode"
    require_research_provenance(
        {"account": "primary", "facts": "Performance Diagnostic is a separate account."}
    )


def test_mixed_original_archive_does_not_taint_legitimate_selected_training_target():
    rows = corpus()
    archive = {
        "kind": "decision",
        "state_before": diagnostic_state(),
        "events": [event(DIAGNOSTIC), event("primary")],
    }
    original = copy.deepcopy(archive)
    candidate = rows[0]["candidate"]
    candidate["packet"]["evidence"]["e0"].update(account="primary", original_capture=archive)
    reseal(candidate)
    assert Candidate.model_validate(candidate).task_id == candidate["task_id"]
    prepared(rows)
    assert archive == original
    candidate["packet"]["evidence"]["e0"]["account"] = DIAGNOSTIC
    reseal(candidate)
    with pytest.raises(ValueError, match="excluded from research"):
        Candidate.model_validate(candidate)


@pytest.mark.parametrize("family", ["numerical", "memory"])
def test_hash_consistent_diagnostic_artifact_cannot_admit_research_account(family):
    artifact = fixture_artifact() if family == "numerical" else fitted()[3]
    artifact["provenance"] = {"account": DIAGNOSTIC, "purpose": PURPOSE}
    hasher = fingerprint if family == "numerical" else digest
    artifact["sha256"] = hasher({key: value for key, value in artifact.items() if key != "sha256"})
    engine = PaperEngine(initial_state(START), START)
    original = copy.deepcopy(engine.state)
    with pytest.raises(ValueError, match="excluded from research"):
        admit(engine, "diagnostic-artifact-fixture", artifact, "100", "0")
    assert engine.state == original and engine.events == []


def test_financial_label_replay_preserves_recorded_diagnostic_admission(decision_packet):
    import time

    from trading.evidence_runtime import plain
    from trading.memory_dataset import executable_label
    from trading.paper_diagnostics import create_diagnostic, start_diagnostic

    recorder, packet, frames, studies = decision_packet
    state = copy.deepcopy(packet["state_before"])
    engine = PaperEngine(state, packet["at"])
    create_diagnostic(engine, "diagnostic-label-create-0001")
    start_diagnostic(engine, "diagnostic-label-start-0001", 1)
    packet.update(state_before=plain(state), diagnostic_allowed=False)
    engine = PaperEngine(state, packet["at"])
    engine.tick(frames, copy.deepcopy(studies), diagnostic_allowed=False)
    recorder.complete(packet, engine.events, state, [], {}, time.perf_counter())
    record = {"id": 1, "sha256": digest(packet), "payload": packet}
    verified = {}
    try:
        # Lack of a matured trade remains truthful; this verifies that the entire
        # mixed financial record reconciles before selecting legitimate targets.
        label = executable_label(
            {"status": "available", "cutoff": packet["at"], "horizon_at": packet["at"]},
            [record],
            packet["at"],
            verified,
        )
        assert label["status"] == "unavailable"
        assert "No complete linked" in label["reason"]
        assert verified[record["sha256"]] == packet
    finally:
        if recorder._archive is not None:
            recorder._archive.close()
