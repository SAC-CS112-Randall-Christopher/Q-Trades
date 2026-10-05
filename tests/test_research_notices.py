"""Deterministic notice fixtures. Model stubs/mature synthetic time are not operating proof."""

import asyncio
import copy
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_lessons import FollowupStub, complete
from test_research_storage import plan_at
from test_role_worker import make_lab
from test_station import runtime as runtime

from trading.api import create_app
from trading.config import Settings
from trading.experiment_lab import ExperimentLab
from trading.experiment_registry import ExperimentRegistry
from trading.research_notices import ResearchNotices, operational_conditions
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker


def condition(at, state="active", severity="warning", key="research_resource"):
    return {
        "key": key,
        "condition": state,
        "severity": severity,
        "source_at": at,
        "title": "Explicit synthetic operational fixture",
        "market": None,
        "account": None,
        "impact": "Fixture impact",
        "next_action": "Inspect original evidence",
        "link": "#role-research",
        "facts": {"fixture": True},
    }


@pytest.fixture
def notices(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    try:
        yield ResearchNotices(registry)
    finally:
        registry.close()


def test_burst_and_unchanged_sources_coalesce_without_queuing_any_research(notices):
    protected_before = notices.registry.db.execute("SELECT * FROM evidence_windows").fetchall()
    for n in range(30):
        notices.observe([condition(100 + n * 10)], 100 + n * 10)
    for _ in range(100):
        notices.observe([condition(390)], 391)
    result = notices.snapshot(392)
    row = result["operational"][0]
    assert row["state"] == "active" and row["notifications"] == 1
    assert row["active_observations"] == 30 and row["suppressed_active_observations"] == 29
    assert row["repeated_source_checks"] == 100 and row["observations"] == 30
    assert len(notices.detail(row["key"])["transitions"]) == 1
    assert notices.registry.db.execute("SELECT count(*) FROM experiments").fetchone()[0] == 0
    assert (
        notices.registry.db.execute("SELECT * FROM evidence_windows").fetchall() == protected_before
    )


def test_hysteresis_recovery_and_true_recurrence_remain_one_thread(notices):
    for at, state in [(100, "active"), (110, "active"), (120, "clear"), (130, "active")]:
        notices.observe([condition(at, state)], at)
    assert notices.snapshot(131)["operational"][0]["state"] == "active"
    assert notices.snapshot(131)["operational"][0]["notifications"] == 1
    notices.observe([condition(140, "clear")], 140)
    notices.observe([condition(150, "clear")], 150)
    row = notices.snapshot(151)["operational"][0]
    assert row["state"] == "recovered" and row["recoveries"] == 1
    notices.observe([condition(160)], 160)
    notices.observe([condition(170)], 170)
    row = notices.snapshot(171)["operational"][0]
    assert row["state"] == "active" and row["notifications"] == 2
    assert len(notices.snapshot(171)["operational"]) == 1


def test_delayed_clear_observations_cannot_recover_a_newer_active_fault(notices):
    notices.observe([condition(200)], 200)
    notices.observe([condition(210)], 210)
    notices.observe([condition(100, "clear")], 220)
    notices.observe([condition(110, "clear")], 230)
    row = notices.snapshot(231)["operational"][0]
    assert row["state"] != "recovered" and row["recoveries"] == 0
    assert row["last_source_at"] == 210


def test_same_source_timestamp_cannot_reuse_another_candidate_confirmation(notices):
    notices.observe([condition(100)], 100)
    notices.observe([condition(110)], 110)
    notices.observe([condition(110, "clear")], 120)
    row = notices.snapshot(121)["operational"][0]
    assert row["state"] != "recovered" and row["recoveries"] == 0
    notices.observe([condition(120, "clear")], 130)
    assert notices.snapshot(131)["operational"][0]["recoveries"] == 0
    notices.observe([condition(130, "clear")], 140)
    assert notices.snapshot(141)["operational"][0]["recoveries"] == 1


def test_explicit_producer_restart_resets_confirmation_and_old_epoch_cannot_return(notices):
    def from_epoch(at, state, epoch):
        return {**condition(at, state), "source_epoch": epoch}

    notices.observe([from_epoch(200, "active", "first")], 200)
    notices.observe([from_epoch(210, "active", "first")], 210)
    notices.observe([from_epoch(100, "clear", "restart")], 100)
    row = notices.snapshot(101)["operational"][0]
    assert row["last_confirmed_state"] == "active" and row["recoveries"] == 0
    notices.observe([from_epoch(110, "clear", "restart")], 110)
    assert notices.snapshot(111)["operational"][0]["recoveries"] == 1
    reopened = ResearchNotices(notices.registry)
    reopened.observe([from_epoch(90, "active", "first")], 120)
    row = reopened.snapshot(121)["operational"][0]
    assert row["state"] == "unknown" and row["last_source_epoch"] == "restart"
    assert row["last_source_at"] == 110 and row["last_confirmed_state"] == "recovered"
    assert "superseded" in row["source_error"]


def test_clock_rollback_requires_new_valid_distinct_observations(notices):
    notices.observe([condition(100)], 100)
    notices.observe([condition(110)], 110)
    notices.observe([condition(80, "clear")], 80)
    row = notices.snapshot(111)["operational"][0]
    assert row["state"] == "unknown" and row["last_source_at"] == 110
    assert row["recoveries"] == 0 and "clock" in row["source_error"]
    notices.observe([condition(120, "clear")], 120)
    assert notices.snapshot(121)["operational"][0]["recoveries"] == 0
    notices.observe([condition(130, "clear")], 130)
    assert notices.snapshot(131)["operational"][0]["recoveries"] == 1


def test_real_producer_stale_future_and_restart_checks_do_not_invent_recovery(notices, runtime):
    def observe(at, source_at, present):
        runtime.state["last_tick"] = at
        runtime._input_eligibility = {
            "observed_at": source_at,
            "markets": {"BTCUSD": {"frame_present": present}, "ETHUSD": {"frame_present": True}},
        }
        rows = operational_conditions(runtime, at)
        original = next(row for row in rows if row["key"] == "input:BTCUSD")
        notices.observe([original], at)
        return original

    runtime.running = True
    first = observe(100, 100, False)
    assert first["source_epoch"] == runtime._notice_epoch
    observe(104, 104, False)
    assert notices.snapshot(105)["operational"][0]["state"] == "active"
    stale = observe(120, 104, True)
    assert stale["condition"] == "unknown"
    future = observe(124, 130, True)
    assert future["condition"] == "unknown"
    assert notices.snapshot(125)["operational"][0]["recoveries"] == 0
    observe(130, 130, True)
    observe(134, 134, True)
    assert notices.snapshot(135)["operational"][0]["recoveries"] == 1
    assert not runtime.stream.records


def test_acknowledge_snooze_and_unknown_do_not_hide_critical_conditions(notices):
    notices.observe([condition(100, severity="critical", key="paper_processing")], 100)
    notices.present("paper_processing", "acknowledge", 101)
    notices.present("paper_processing", "snooze", 102, 300)
    row = notices.snapshot(103)["operational"][0]
    assert row["state"] == "active" and row["severity"] == "critical"
    assert row["acknowledged_at"] == 101 and row["snoozed_until"] == 402
    notices.observe([condition(110, "unknown", key="paper_processing")], 110)
    row = notices.snapshot(111)["operational"][0]
    assert row["state"] == "unknown" and row["last_confirmed_state"] == "active"
    assert row["severity"] == "critical" and row["recoveries"] == 0


def test_restart_and_detector_staleness_never_synthesize_recovery(tmp_path):
    path = tmp_path / "registry.sqlite"
    registry = ExperimentRegistry(path)
    first = ResearchNotices(registry)
    first.observe([condition(100)], 100)
    first.observe([condition(101)], 110)
    first.present("research_resource", "acknowledge", 111)
    registry.close()
    registry = ExperimentRegistry(path)
    try:
        resumed = ResearchNotices(registry)
        assert resumed.snapshot(120)["detector_last_check_at"] is None
        row = resumed.snapshot(150)["operational"][0]
        assert row["state"] == "unavailable" and row["last_confirmed_state"] == "active"
        assert row["acknowledged_at"] == 111 and row["recoveries"] == 0
        resumed.observe([condition(160, "clear")], 160)
        resumed.observe([condition(170, "clear")], 170)
        assert resumed.snapshot(171)["operational"][0]["state"] == "recovered"
    finally:
        registry.close()


@pytest.mark.parametrize(
    "change",
    [
        {"key": "unknown_scope"},
        {"source_at": 200},
        {"source_at": float("nan")},
        {"facts": {"oversized": "x" * 9000}},
        {"condition": "resolved_by_operator"},
    ],
)
def test_bad_observation_is_atomic_and_cannot_partly_update_threads(notices, change):
    bad = condition(100) | change
    with pytest.raises(ValueError):
        notices.observe([condition(100, severity="critical", key="paper_processing"), bad], 100)
    assert not notices.snapshot(101)["operational"]
    assert notices.last_checked_at is None


def test_existing_producers_distinguish_missing_market_stale_service_and_model_absence(runtime):
    runtime.state["last_tick"] = 100
    runtime._input_eligibility = {
        "observed_at": 100,
        "markets": {
            "BTCUSD": {"frame_present": True},
            "ETHUSD": {"frame_present": False, "reason": "no_fresh_book"},
        },
    }
    before = copy.deepcopy(runtime.state)
    rows = {r["key"]: r for r in operational_conditions(runtime, 100)}
    assert rows["input:BTCUSD"]["condition"] == "clear"
    assert rows["input:ETHUSD"]["condition"] == "active"
    assert rows["input:ETHUSD"]["facts"]["selector"]["reason"] == "no_fresh_book"
    assert "symbol=ETHUSD" in rows["input:ETHUSD"]["link"]
    assert all(r["condition"] == "unknown" for r in operational_conditions(runtime, 120))
    assert all(r["condition"] == "unknown" for r in operational_conditions(None, 120))
    runtime.error = "Original processing/accounting fault"
    assert operational_conditions(runtime, 120)[0]["severity"] == "critical"
    assert runtime.state == before and not runtime.stream.records


@pytest.mark.parametrize("state", ["unavailable", "capacity", "disk_pressure"])
def test_retained_recording_fault_remains_explicit_without_assuming_raw_capture_failed(
    runtime, state
):
    runtime.state["last_tick"] = 100
    runtime.evidence.storage_status = {
        "state": state,
        "reason": "Explicit synthetic retained-storage interruption",
        "latest_reference": "original-reference-before-interruption",
        "last_capture": 90,
        "full_omitted": 7,
    }
    rows = {r["key"]: r for r in operational_conditions(runtime, 100)}
    assert rows["retained_recording"]["condition"] == "active"
    assert rows["retained_recording"]["severity"] == "critical"
    assert rows["retained_recording"]["facts"]["last_capture"] == 90
    assert rows["raw_recording"]["condition"] == "clear"
    assert operational_conditions(runtime, 120)[3]["condition"] == "unknown"
    runtime.evidence.storage_status = {"state": "recording", "last_capture": 90}
    assert operational_conditions(runtime, 100)[3]["condition"] == "clear"


def test_notice_api_reads_are_side_effect_free_and_presentation_cannot_change_finance(
    notices, runtime, tmp_path
):
    notices.observe([condition(100, severity="critical", key="paper_processing")], 100)
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.lab = SimpleNamespace(notices=notices, notice_error=None)
        app.state.paper = runtime
        before = copy.deepcopy(runtime.state)
        changes = notices.registry.db.total_changes
        first = client.get("/api/research/notices")
        assert first.status_code == 200 and first.json()["operational"][0]["state"] == "unavailable"
        assert client.get("/api/research/notices/paper_processing").status_code == 200
        assert client.get("/api/research/notices/absent").status_code == 404
        assert notices.registry.db.total_changes == changes
        app.state.lab.notice_error = "Explicit fixture detector-persistence failure"
        assert client.get("/api/research/notices").json()["detector_error"]
        assert notices.registry.db.total_changes == changes
        app.state.lab.notice_error = None
        body = {"key": "paper_processing", "action": "acknowledge"}
        assert client.post("/api/research/notices/presentation", json=body).status_code == 403
        headers = {"X-Local-Operator": "1"}
        assert (
            client.post(
                "/api/research/notices/presentation",
                json=body,
                headers=headers | {"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/research/notices/presentation",
                json=body | {"action": "resume"},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/research/notices/presentation",
                json=body | {"seconds": 10000},
                headers=headers,
            ).status_code
            == 422
        )
        result = client.post("/api/research/notices/presentation", json=body, headers=headers)
        assert (
            result.json()["presentation_only"] and not result.json()["financial_or_service_effect"]
        )
        assert runtime.state == before and not runtime.stream.records
        app.state.lab = None
        assert client.get("/api/research/notices").status_code == 503


def test_full_notice_batch_retains_audit_states_and_recovery_in_the_api(
    notices, runtime, tmp_path, monkeypatch
):
    """Synthetic audit receipts through the actual status, registry and API owners."""
    clock = [time.time()]
    monkeypatch.setattr("trading.api.time.time", lambda: clock[0])
    accounts = copy.deepcopy(runtime.state["accounts"])
    runtime._capture_failure = "Explicit synthetic recording fault"
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    stages = [
        ("pending", "unknown"),
        ("balanced", "unknown"),
        ("balanced", "recovered"),
        ("unavailable", "unknown"),
        ("balanced", "unknown"),
        ("balanced", "recovered"),
        ("expired", "unknown"),
        ("balanced", "unknown"),
        ("balanced", "recovered"),
        ("imbalanced", "active"),
        ("balanced", "active"),
        ("balanced", "recovered"),
    ]
    with TestClient(app) as client:
        app.state.lab = SimpleNamespace(notices=notices, notice_error=None)
        app.state.paper = runtime
        for index, (mode, expected) in enumerate(stages):
            clock[0] += 5  # Distinct fixture observations; retain ordinary confirmation rules.
            runtime.state["last_tick"] = clock[0]
            original_audit = copy.deepcopy(runtime.receipts)
            if mode in {"balanced", "imbalanced"}:
                result = {
                    "reconciliation": {"balanced": mode == "balanced", "revision": index},
                    "observed_at": clock[0],
                    "observed_mono": time.monotonic(),
                }
                if mode == "imbalanced":
                    with pytest.raises(RuntimeError, match="reconciliation failed"):
                        runtime._accept_financial_audit(result)
                else:
                    runtime._accept_financial_audit(result)
            elif mode == "unavailable":
                runtime._readback_error = "Explicit synthetic monitoring outage"
            elif mode == "expired":
                runtime._readback_audit_mono = time.monotonic() - 121
            notices.observe(operational_conditions(runtime, clock[0]), clock[0])
            changes = notices.registry.db.total_changes
            response = client.get("/api/research/notices")
            assert response.status_code == 200
            body = response.json()
            rows = {row["key"]: row for row in body["operational"]}
            journal = rows["financial_monitoring"]
            assert body["detector_error"] is None and body["detector_last_check_at"] == clock[0]
            assert journal["state"] == expected
            assert journal["condition_evidence"]["facts"]["status"] == mode
            assert rows["raw_recording"]["state"] == "active"
            assert rows["raw_recording"]["observations"] == index + 1
            assert client.get("/api/status").json()["paper"]["journal"]["status"] == mode
            assert client.get("/api/health").json()["journal_monitoring"]["status"] == mode
            assert notices.registry.db.total_changes == changes
            if mode in {"unavailable", "expired"}:
                assert runtime.receipts == original_audit
                assert (
                    journal["condition_evidence"]["facts"]["checked_at"]
                    == original_audit["checked_at"]
                )
            if mode == "imbalanced":
                assert journal["severity"] == "critical" and journal["notifications"] == 1
        detail = client.get("/api/research/notices/financial_monitoring").json()
        transitions = [row["body"] for row in detail["transitions"]]
        assert any(row.get("state") == "active" for row in transitions)
        assert transitions[0]["state"] == "recovered"
    assert runtime.state["accounts"] == accounts and not runtime.stream.records
    # A synthetic later audit does not authorize restarting the financial supervisor.
    assert runtime._financial_failure and runtime.stream.changed.is_set()


def test_supervisor_persists_the_complete_producer_batch_without_research(tmp_path):
    lab = ExperimentLab(tmp_path / "registry.sqlite", None, lambda: False)
    lab.notice_source = lambda: operational_conditions(None, time.time())

    async def scenario():
        task = asyncio.create_task(lab.run())
        try:
            async def observed():
                while lab.notices.last_checked_at is None and lab.notice_error is None:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(observed(), 2)
            assert lab.notice_error is None and lab.child is None
            rows = lab.notices.snapshot(time.time())["operational"]
            assert {row["key"] for row in rows} == {
                row["key"] for row in operational_conditions(None, time.time())
            }
            assert len(rows) == 7 and all(row["state"] == "unknown" for row in rows)
            assert lab.registry.db.execute("SELECT count(*) FROM experiments").fetchone()[0] == 0
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    try:
        asyncio.run(scenario())
    finally:
        lab.registry.close()


@pytest.mark.parametrize("failed", [False, True])
def test_existing_supervisor_observes_even_when_research_admission_is_refused(tmp_path, failed):
    lab = ExperimentLab(tmp_path / "registry.sqlite", None, lambda: False)
    lab.notice_source = lambda: [condition(100, severity="critical")]
    if failed:

        def broken(*_):
            raise sqlite3.OperationalError("Explicit fixture storage outage")

        lab.notices.observe = broken

    async def scenario():
        task = asyncio.create_task(lab.run())
        try:

            async def observed():
                while lab.notices.last_checked_at is None and lab.notice_error is None:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(observed(), 2)
            assert lab.running
            assert bool(lab.notice_error) == failed
            assert lab.child is None
            assert lab.registry.db.execute("SELECT count(*) FROM experiments").fetchone()[0] == 0
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    try:
        asyncio.run(scenario())
    finally:
        lab.registry.close()


def test_real_role_lesson_metadata_uses_original_identity_and_no_alert_read_disclosure(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    worker = RoleWorker(lab.registry, lab, FollowupStub())
    worker.enabled = True  # Explicit test double; never an installed role.
    first = worker.enqueue(
        Question(question="Synthetic compare then choose a justified next test."), START
    )
    done, score = complete(worker, lab, first, START)
    clock[0] = score["available_at"] + 3
    notices = ResearchNotices(lab.registry)
    changes = lab.registry.db.total_changes
    snapshot = notices.snapshot(clock[0])
    assert snapshot["developments"][0]["id"] == done["id"]
    assert snapshot["findings"][0]["task"] == done["id"]
    assert snapshot["findings"][0]["available_at"] == score["available_at"]
    assert "delta_usd" not in json.dumps(snapshot) and "response" not in json.dumps(snapshot)
    assert lab.registry.db.total_changes == changes
    assert notices.snapshot(score["available_at"] - 1)["findings"] == []
    # The existing explicit detail path retains its required disclosure.
    detail = worker.lessons.get(snapshot["findings"][0]["id"])
    assert detail["source"]["body"] == score
    assert lab.registry.db.total_changes > changes
