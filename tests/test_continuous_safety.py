"""Crash/capacity/API checks using synthetic state and isolated test schemas."""

import copy
import sqlite3
import time
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from test_autonomous_lab import admit, bars_at, close_window, make_lab, tick_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

from trading import autonomous_finance as finance
from trading.api import create_app
from trading.autonomous_lab import AutonomousLab
from trading.autonomous_spec import LabPolicy, LabProposal, RuleSpec
from trading.config import Settings
from trading.research_activity import ResearchActivity, sqlite_rows


def submitted(lab, i, family="breakout"):
    bundle = lab.bundle(START)
    base = RuleSpec()
    return LabProposal(
        request_id=f"external-request-{i:05}",
        policy_id="continuous-test-policy",
        strategy=base
        if family == "breakout"
        else RuleSpec(family="range_reversion", lookback=20 + i),
        reference=base,
        source="external",
        kind="replication" if family == "breakout" else "independent",
        replication_of="reviewed-breakout-v1" if family == "breakout" else None,
        mechanism="Explicit baseline replication"
        if family == "breakout"
        else "Distinct range gate",
        question="Does the declared hypothesis add after-cost value in the subsequent window?",
        evidence_bundle_sha256=bundle["sha256"],
    )


def test_twenty_concurrent_slots_include_reservations_and_ordinary_accounts(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, family_slots=10, daily_trials=24)
    admitted = []
    for i in range(7):
        p = submitted(lab, i if i < 5 else i - 5, "breakout" if i < 5 else "range_reversion")
        # Distinct source identities across both families.
        if i >= 5:
            p = p.model_copy(update={"request_id": f"independent-request-{i}"})
        lab.submit(p, START)
        receipt = store.lab_reserve(START, p)
        lab.paper.state = store.read()
        assert finance.slots(lab.paper.state)["used"] <= 20
        admitted.append(receipt["trial_id"])
        if i < 6:
            lab.paper.state = store.transact(
                START, lambda e, t=receipt["trial_id"]: finance.fund(e, t)
            )
            lab.inbox.update(p.request_id, "funded", receipt["trial_id"])
    count = finance.slots(store.read())
    assert count["used"] == 20 and count["managed"] == 18 and count["reserved"] == 2
    with pytest.raises(ValueError, match="capacity"):
        store.lab_reserve(START, submitted(lab, 99))
    before = copy.deepcopy(store.read()["accounts"])
    with pytest.raises(ValueError, match="Protected"):
        store.transact(START, lambda e: finance.retire_account(e, "primary", "forbidden"))
    assert store.read()["accounts"] == before
    lab.paper.state = store.transact(
        START, lambda e: finance.retire_trial(e, admitted[0], "operator")
    )
    assert finance.slots(lab.paper.state)["used"] == 18
    assert store.archived_account(admitted[0] + "-candidate")
    receipt = store.lab_reserve(START, submitted(lab, 99))
    assert receipt["trial_id"] not in admitted and finance.slots(store.read())["used"] == 20
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_before_after_admission_and_score_ack_crashes_recover_once(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    assert lab.step(START)
    update = lab.inbox.update

    def fail_reserved(request, status, trial_id=None):
        if status == "reserved":
            raise RuntimeError("Synthetic lost acknowledgment after intent commit")
        update(request, status, trial_id)

    monkeypatch.setattr(lab.inbox, "update", fail_reserved)
    tick_lab(lab, START + 2)
    assert not lab.step(START + 2)
    assert finance.slots(store.read())["reserved"] == 2
    monkeypatch.setattr(lab.inbox, "update", update)
    tick_lab(lab, START + 4)
    assert lab.step(START + 4)
    tick_lab(lab, START + 6)
    assert lab.step(START + 6)
    trial = next(iter(lab.paper.state["autonomous_lab"]["trials"].values()))

    def fail_completed(request, status, trial_id=None):
        if status == "completed":
            raise RuntimeError("Synthetic lost acknowledgment after score commit")
        update(request, status, trial_id)

    tick_lab(lab, trial["started_at"] + 2)
    tick_lab(lab, trial["started_at"] + 4)
    monkeypatch.setattr(lab.inbox, "update", fail_completed)
    tick_lab(lab, trial["review_at"], coverage=True)
    assert not lab.step(trial["review_at"])
    assert not store.read()["autonomous_lab"]["trials"]
    monkeypatch.setattr(lab.inbox, "update", update)
    recovered = AutonomousLab(lab.registry, lab.paper, lambda: True)
    tick_lab(recovered, trial["review_at"] + 2)
    assert recovered.step(trial["review_at"] + 2)
    assert recovered.inbox.get(trial["proposal_id"])["status"] == "completed"
    for kind, expected in (
        ("lab_account_funded", 2),
        ("lab_trial_reserved", 1),
        ("lab_trial_scored", 1),
    ):
        assert (
            store.connection.execute(
                "SELECT count(*) AS n FROM paper_events WHERE kind=%s", (kind,)
            ).fetchone()["n"]
            == expected
        )
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_hourly_allowance_survives_crash_restart_and_resets_only_in_next_utc_period(
    pg_store, tmp_path
):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, hourly_compute_seconds=1)
    lab._budget(START)  # Durable dispatch reservation; pretend the process died immediately.
    recovered = AutonomousLab(lab.registry, lab.paper, lambda: True)
    assert not recovered.step(START)
    state = store.read()["autonomous_lab"]
    assert state["phase"] == "budget_wait" and state["budget"]["compute_seconds"] == 1
    boundary = (int(START // 3600) + 1) * 3600
    tick_lab(recovered, boundary)
    assert recovered.step(boundary)
    assert store.read()["autonomous_lab"]["budget"]["hour"] == int(boundary // 3600)
    assert store.read()["autonomous_lab"]["budget"]["steps"] == 1
    lab.registry.close()


def test_daily_budget_and_resource_guard_backoff_preserve_financial_history(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600, daily_trials=1)
    trial = admit(lab, START)
    close_window(lab, trial)
    tick_lab(lab, trial["review_at"] + 4)
    assert not lab.step(trial["review_at"] + 4)
    assert store.read()["autonomous_lab"]["phase"] == "budget_wait"
    next_day = (int(START // 86400) + 1) * 86400
    tick_lab(lab, next_day)
    lab.can_research = lambda: False
    assert not lab.step(next_day)
    assert "yielding" in store.read()["autonomous_lab"]["reason"]
    assert store.read()["autonomous_lab"]["historical_trials"] == 1
    assert store.archived_account(trial["candidate"])
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_uncertain_entry_and_faulted_draining_account_keep_capacity(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    trial = admit(lab, START)
    tick_lab(lab, START + 120, eligible=True)

    def mark(engine):
        a = engine.state["accounts"][trial["candidate"]]
        a["pending"]["BTCUSD"]["uncertain"] = True
        a["execution_uncertain"] = True
        finance.retire_trial(engine, trial["id"], "uncertain")

    lab.paper.state = store.transact(START + 121, mark)
    tick_lab(lab, START + 180)
    a = store.read()["accounts"][trial["candidate"]]
    assert a["pending"] and a["execution_uncertain"]
    assert finance.slots(store.read())["draining"] >= 1
    assert store.archived_account(trial["candidate"]) is None
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_hard_stop_and_operating_costs_are_preserved_without_double_charging(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600, daily_operating_usd="2.40")
    trial = admit(lab, START)
    tick_lab(lab, trial["started_at"] + 2)
    tick_lab(lab, trial["started_at"] + 4)
    tick_lab(lab, trial["started_at"] + 120, eligible=True)
    tick_lab(lab, trial["started_at"] + 122, eligible=True)
    tick_lab(lab, trial["started_at"] + 125, "20")
    tick_lab(lab, trial["started_at"] + 127, "20")
    tick_lab(lab, trial["review_at"], "20", coverage=True)
    assert lab.step(trial["review_at"])
    record = store.lab_history()["trials"][0]
    score = next(d["body"] for d in record["decisions"] if d["kind"] == "lab_trial_scored")
    assert score["outcome"] == "risk_stopped"
    assert D(score["operating_each_usd"]) == D(".10")
    assert D(score["cash_usd"]) == D("-.10")
    archived = store.archived_account(trial["candidate"])["state"]
    assert archived["risk_stop_id"] and archived["risk_peak"] == "100"
    assert archived["funding"] == "100" and archived["replenishments"] == 0
    assert D(score["net_after_operating_usd"]["candidate"]) == D(
        score["candidate_sample"]["equity"]
    ) - 100 - D(".10")
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_new_same_rule_reference_does_not_pause_parent_and_closure_rolls_back(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    parent = admit(lab, START)
    close_window(lab, parent, "promising")
    child = admit(lab, parent["review_at"] + 4)
    now = child["started_at"] + 1
    lab.paper.history = {"BTCUSD": bars_at(now)}
    study = {}
    lab.paper.numerical_study(now, study)
    account = lab.paper.state["accounts"][parent["candidate"]]
    feature = study["BTCUSD"][account["version"]]
    # Feature availability is common; the newborn reference's admission cutoff
    # must be applied per account in the engine, not to its continuing parent.
    assert feature["input_available_at"] == lab.paper.history["BTCUSD"][-1].close_ms / 1000
    assert feature["reason"] != "Awaiting a fresh subsequent closed candle"
    snapshot = store.read()

    def crash_archive(engine):
        finance.retire_trial(engine, child["id"], "synthetic crash")
        raise RuntimeError("Crash before closure commit")

    with pytest.raises(RuntimeError):
        store.transact(now, crash_archive)
    assert store.read() == snapshot and store.archived_account(child["candidate"]) is None
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_registry_beyond_512_retains_rejected_attempts_with_bounded_pages(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    proposal = submitted(lab, 0, "range_reversion")
    initial = lab.submit(proposal, START)
    lab.inbox.update(proposal.request_id, "completed")
    for i in range(1, 520):
        duplicate = proposal.model_copy(update={"request_id": f"retained-duplicate-{i:04}"})
        assert lab.inbox.submit(duplicate, initial["evaluation"])["status"] == "rejected"
    page = lab.inbox.page()
    assert len(page["proposals"]) == 20 and page["has_more"]
    assert sum(c["count"] for c in page["counts"]) == 520
    assert lab.inbox.get(proposal.request_id)["evaluation"] == initial["evaluation"]
    with pytest.raises(sqlite3.Error, match="retained"):
        lab.registry.db.execute("DELETE FROM lab_proposals")
    assert store.read()["autonomous_lab"]["historical_trials"] == 0
    lab.registry.close()


def test_activity_dates_use_readonly_durable_sources_with_original_search_path(pg_store, tmp_path):
    store, dsn = pg_store
    lab = make_lab(store, tmp_path)
    lab.paper.state = store.transact(
        START, lambda e: e.emit("decision", "primary", {"no_trade": True})
    )
    activity = ResearchActivity(tmp_path)
    result = activity.snapshot(dsn, lab.paper, None)
    assert result["signal"]["at"] == START
    assert result["processing"] == START
    assert result["completed_learning"] is None
    assert "Historical" not in result["next_action"]
    missing = tmp_path / "nonexistent.sqlite"
    assert sqlite_rows(missing, "SELECT * FROM nothing") == [] and not missing.exists()
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_normal_api_declared_start_inbox_controls_and_restart_persistence(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    # Normal API routes with real durable effects; the feed is explicitly synthetic.
    monkeypatch.setattr(time, "time", lambda: START + 2)
    lab = make_lab(store, tmp_path, now=time.time(), start_policy=False)
    path = tmp_path / "monitor.sqlite"
    with TestClient(create_app(Settings(), path, background=False)) as client:
        client.app.state.paper = lab.paper
        client.app.state.lab.autonomous = lab
        headers = {"X-Local-Operator": "1", "Origin": "http://testserver"}
        declared = LabPolicy(request_id="api-continuous-policy").model_dump(mode="json")
        assert client.post("/api/autonomous/start", json=declared).status_code == 403
        assert (
            client.post("/api/autonomous/start", json=declared, headers=headers).json()["status"]
            == "started"
        )
        assert (
            client.post("/api/autonomous/start", json=declared, headers=headers).json()["status"]
            == "already_started"
        )
        assert (
            client.post(
                "/api/autonomous/control", json={"action": ["bad"]}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/autonomous/control", json={"action": "pause_proposals"}, headers=headers
            ).status_code
            == 200
        )
        assert client.get("/api/autonomous").json()["lab"]["proposals_paused"]
        assert (
            client.post(
                "/api/autonomous/control", json={"action": "resume_proposals"}, headers=headers
            ).status_code
            == 200
        )
        proposal = lab.propose(time.time())
        response = client.post(
            "/api/autonomous/proposals", json=proposal.model_dump(), headers=headers
        )
        assert response.status_code == 200 and response.json()["status"] == "evaluated"
        evidence = client.get("/api/autonomous/proposals/" + proposal.request_id).json()
        assert evidence["issued_bundle"]["policy_id"] == declared["request_id"]
        assert len(evidence["evaluation"]["inputs"]) == 400
        assert client.get("/api/autonomous/history").json()["trials"] == []
        assert client.get("/api/autonomous/export").json()["records"]
    assert store.read()["autonomous_lab"]["policy"] == declared
    assert store.reconcile()["balanced"]
    lab.registry.close()
