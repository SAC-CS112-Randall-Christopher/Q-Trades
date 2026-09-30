"""Synthetic lifecycle fixtures in disposable PostgreSQL; never market qualification."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from test_paper_engine import START, frame
from test_paper_store import pg_store as pg_store

from trading import autonomous_finance as finance
from trading.autonomous_lab import AutonomousLab
from trading.autonomous_spec import ORIGINALS, LabPolicy, RuleSpec, rule_feature
from trading.chart_indicators import overlays
from trading.experiment_registry import ExperimentRegistry
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore
from trading.paper_strategy import Bar
from trading.prospective_review import ProspectiveReview


def bars_at(now):
    end = int(now // 60) * 60000
    return [
        Bar(
            end - (400 - i) * 60000,
            D(100) + D(i) / 100,
            D(101) + D(i) / 100,
            D(99) + D(i) / 100,
            D(100) + D(i) / 100,
            D(10),
            end - (399 - i) * 60000 - 1,
        )
        for i in range(400)
    ]


def make_lab(store, directory, now=START, start_policy=True, **policy):
    def setup(engine):
        engine.universe_experiment(["BTCUSD", "ETHUSD"])
        if start_policy:
            finance.start(engine, LabPolicy(request_id="continuous-test-policy", **policy))
        engine.tick({"BTCUSD": frame(now)}, {})

    store.transact(now, setup)
    registry = ExperimentRegistry(directory / "experiments.sqlite3")
    ProspectiveReview(registry)
    # No network is used by this deterministic component fixture.
    paper = PaperRuntime(store, SimpleNamespace())
    paper.running = True
    paper.history = {"BTCUSD": bars_at(now)}
    paper.books = {"BTCUSD": frame(now)}
    return AutonomousLab(registry, paper, lambda: True)


def tick_lab(lab, now, price="100", eligible=False, coverage=False):
    paper = lab.paper
    paper.history = {"BTCUSD": bars_at(now)}
    paper.books = {"BTCUSD": frame(now, price, int(now * 10))}
    versions = {a["version"] for a in paper.state["accounts"].values() if a.get("lab_trial")}
    study = {
        "BTCUSD": {
            v: {
                "eligible": eligible,
                "atr": "1",
                "reason": "Synthetic fixture",
                "bar_open_ms": int(now // 60) * 60000,
                "input_available_at": now,
                "version": v,
            }
            for v in versions
        }
    }

    def apply(engine):
        if coverage:
            for t in engine.state["autonomous_lab"]["trials"].values():
                if t["status"] == "active":
                    # Accelerated lifecycle clock ONLY. Native soak separately measures
                    # actual coverage. This receipt is explicit and retained in QA.
                    t["covered_seconds"] = max(0, min(now, t["review_at"]) - t["started_at"])
            engine.emit("synthetic_coverage_fixture", "system", {"qualification": False})
        engine.tick(paper.books, study)

    paper.state = paper.store.transact(now, apply)
    return paper.state


def admit(lab, now):
    at = now
    for _ in range(30):
        tick_lab(lab, at)
        worked = lab.step(at)
        current = lab.paper.state["autonomous_lab"]
        active = [t for t in current["trials"].values() if t["status"] == "active"]
        if active:
            return active[0]
        assert not lab.last_error, lab.last_error
        at = at + 2 if worked else max(at + 2, current["next_action_at"])
    pytest.fail("No new trial after bounded synthetic clock: " + current["reason"])


def close_window(lab, trial, outcome="inconclusive"):
    start = trial["started_at"]
    tick_lab(lab, start + 2)  # Passive intent on a subsequent observed book.
    tick_lab(lab, start + 4)  # Fill before its original expiry, with execution fees.
    if outcome == "promising":
        tick_lab(lab, start + 120, "90", True)
        tick_lab(lab, start + 122, "90", True)
        tick_lab(lab, start + 125, "110")
        tick_lab(lab, start + 2900, "110")
        tick_lab(lab, start + 2902, "110")
        price = "110"
    elif outcome == "economically_unsuccessful":
        tick_lab(lab, start + 120, "100", True)
        tick_lab(lab, start + 122, "100", True)
        tick_lab(lab, start + 125, "99")
        tick_lab(lab, start + 127, "99")
        price = "99"
    elif outcome == "inconclusive":
        # Positive executable value remains inconclusive when below full-period passive.
        tick_lab(lab, start + 120, "109", True)
        tick_lab(lab, start + 122, "109", True)
        tick_lab(lab, start + 125, "110")
        tick_lab(lab, start + 2900, "110")
        tick_lab(lab, start + 2902, "110")
        price = "110"
    else:
        price = "100"
    at = trial["review_at"]
    tick_lab(lab, at, price, coverage=outcome != "data_blocked")
    assert lab.step(at), lab.last_error
    event = lab.paper.store.connection.execute(
        "SELECT body FROM paper_events WHERE kind='lab_trial_scored' AND body->>'trial_id'=%s",
        (trial["id"],),
    ).fetchone()
    assert event
    assert event["body"]["outcome"] == outcome, json.dumps(event["body"], indent=2)
    tick_lab(lab, at + 2, price)
    return event["body"]


def test_complete_positive_parent_child_independent_retirement_and_restart(pg_store, tmp_path):
    store, dsn = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600, hourly_compute_seconds=60)
    original = {n: copy.deepcopy(a) for n, a in lab.paper.state["accounts"].items()}
    parent = admit(lab, START)
    score = close_window(lab, parent, "promising")
    a = lab.paper.state["accounts"][parent["candidate"]]
    frozen = copy.deepcopy(a["rule_spec"])
    identity = (a["funding"], a["risk_policy"], a["admitted_at"])
    assert a["lab_protected"] and a["closed"] == 1 and D(a["fees"]) > 0
    assert D(score["net_after_operating_usd"]["candidate"]) >= D(score["passive_usd"])
    assert D(score["delta_usd"]) == 0
    assert store.archived_account(parent["reference"])
    child = admit(lab, parent["review_at"] + 4)
    p = child["contract"]["proposal"]
    assert p["kind"] == "variation" and p["parent_trial"] == parent["id"]
    assert set(child["contract"]["changed"]) == {"lookback"}
    assert p["reference"] == frozen
    score = close_window(lab, child)
    assert score["outcome"] == "inconclusive" and score["candidate_sample"]["closed"] == 1
    assert store.archived_account(child["candidate"])
    independent = admit(lab, child["review_at"] + 4)
    assert independent["contract"]["proposal"]["kind"] == "independent"
    assert independent["contract"]["proposal"]["strategy"]["family"] == "range_reversion"
    close_window(lab, independent, "economically_unsuccessful")
    a = lab.paper.state["accounts"][parent["candidate"]]
    assert a["rule_spec"] == frozen
    assert (a["funding"], a["risk_policy"], a["admitted_at"]) == identity
    for n in ORIGINALS:
        assert lab.paper.state["accounts"][n]["funding"] == original[n]["funding"]
        assert lab.paper.state["accounts"][n].get("rule_spec") is None
    assert store.reconcile()["balanced"]
    history = store.lab_history()
    assert len(history["trials"]) == 3
    lab.registry.close()
    store.close()
    restarted = PaperStore(dsn, owner=True)
    try:
        assert restarted.read()["autonomous_lab"]["historical_trials"] == 3
        assert restarted.archived_account(child["candidate"])["state"]["funding"] == "100"
        assert restarted.reconcile()["balanced"]
    finally:
        restarted.close()


def test_sequential_rollover_exceeds_old_lifetime_caps_and_keeps_losses(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(
        store, tmp_path, horizon_seconds=3600, daily_trials=24, hourly_compute_seconds=60
    )
    peak, losses, identities = 0, 0, set()
    now = START
    for i in range(36):
        trial = admit(lab, now)
        identities.add(trial["candidate"])
        peak = max(peak, finance.slots(lab.paper.state)["used"])
        outcome = "economically_unsuccessful" if i % 2 else "inconclusive"
        close_window(lab, trial, outcome)
        losses += outcome == "economically_unsuccessful"
        assert not lab.paper.state["autonomous_lab"]["trials"]
        now = trial["review_at"] + 4
    assert len(identities) == 36 and peak <= 20
    assert lab.paper.state["autonomous_lab"]["historical_trials"] == 36
    assert lab.paper.state["autonomous_lab"]["retired_count"] == 72
    assert D(lab.paper.state["autonomous_lab"]["retired_net_usd"]) < 0 and losses == 18
    assert store.reconcile()["balanced"]
    first = store.lab_history()
    second = store.lab_history(first["next_before"])
    assert len(first["trials"]) == 20 and len(second["trials"]) == 16
    assert not second["has_more"]
    assert len(first["trials"][0]["decisions"]) == 2
    assert (
        store.connection.execute(
            "SELECT count(*) AS n FROM paper_events WHERE kind='lab_trial_scored'"
        ).fetchone()["n"]
        == 36
    )
    assert len(store.export(0, 500)["records"]) == 500
    lab.registry.close()


def test_low_information_is_distinct_and_preserves_idle_costs(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600, daily_operating_usd="1")
    trial = admit(lab, START)
    score = close_window(lab, trial, "low_information")
    assert score["outcome"] == "low_information"
    assert score["candidate_sample"]["closed"] == 0
    assert D(score["net_after_operating_usd"]["candidate"]) == -D(1) / 24
    assert score["cash_usd"] == score["net_after_operating_usd"]["candidate"]
    assert store.archived_account(trial["candidate"])
    lab.registry.close()


def test_duplicate_rejection_replication_and_immutable_proposer_receipts(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    issued = lab.bundle(START)
    proposal = lab.propose(START)
    first = lab.submit(proposal, START)
    assert first["status"] == "evaluated"
    assert lab.submit(proposal, START) == first
    changed = proposal.model_copy(update={"question": "Changed frozen question"})
    with pytest.raises(ValueError, match="identity"):
        lab.submit(changed, START)
    invalid = proposal.model_copy(update={"request_id": "duplicate-request", "kind": "variation"})
    # Exercise retained duplicate receipt in the inbox; the public schema rejects
    # this non-child before it can reach a financial transaction.
    duplicate = lab.inbox.submit(invalid, first["evaluation"])
    assert duplicate["status"] == "rejected"
    forged = proposal.model_copy(
        update={"request_id": "forged-replication", "replication_of": "unknown"}
    )
    assert lab.inbox.submit(forged, first["evaluation"])["status"] == "rejected"
    with pytest.raises(sqlite3.Error, match="immutable"):
        lab.registry.db.execute(
            "UPDATE lab_bundles SET body='{}' WHERE sha256=?", (issued["sha256"],)
        )
    lab.registry.close()


def test_lost_ack_contention_and_no_retired_resurrection(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    proposal = lab.propose(START)
    lab.submit(proposal, START)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.lab_reserve(START, proposal), range(2)))
    assert len({r["trial_id"] for r in results}) == 1
    trial_id = results[0]["trial_id"]

    def failed_fund(engine):
        finance.fund(engine, trial_id)
        raise RuntimeError("Crash before funding commit")

    with pytest.raises(RuntimeError):
        store.transact(START, failed_fund)
    assert finance.slots(store.read())["reserved"] == 2
    lab.paper.state = store.transact(START, lambda e: finance.fund(e, trial_id))
    # Acknowledgment is deliberately lost. Duplicate recovery uses permanent intent.
    lab.paper.state = store.transact(START, lambda e: finance.fund(e, trial_id))
    assert (
        store.connection.execute(
            "SELECT count(*) AS n FROM paper_events WHERE kind='lab_account_funded'"
        ).fetchone()["n"]
        == 2
    )
    trial = lab.paper.state["autonomous_lab"]["trials"][trial_id]
    lab.inbox.update(proposal.request_id, "funded", trial_id)
    close_window(lab, trial)
    assert store.lab_reserve(trial["review_at"] + 4, proposal)["trial_id"] == trial_id
    assert trial_id not in store.read()["autonomous_lab"]["trials"]
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_protection_pauses_budget_periods_and_missing_data_are_durable(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600, hourly_compute_seconds=8)
    trial = admit(lab, START)
    lab.paper.state = store.transact(
        START + 6, lambda e: finance.control(e, "protect", trial["candidate"])
    )
    lab.paper.state = store.transact(START + 6, lambda e: finance.control(e, "pause_entries"))
    lab.paper.state = store.transact(START + 6, lambda e: finance.control(e, "pause_proposals"))
    score = close_window(lab, trial, "data_blocked")
    assert score["net_after_operating_usd"]["candidate"] is None
    assert (
        lab.paper.state["autonomous_lab"]["trials"][trial["id"]]["status"] == "operator_preserved"
    )
    assert lab.paper.state["accounts"][trial["candidate"]]["entries_paused"]
    with pytest.raises(ValueError, match="Unprotect"):
        store.transact(
            trial["review_at"] + 3, lambda e: finance.retire_trial(e, trial["id"], "operator")
        )
    lab.paper.state = store.transact(
        trial["review_at"] + 4, lambda e: finance.control(e, "unprotect", trial["candidate"])
    )
    lab.paper.state = store.transact(
        trial["review_at"] + 4, lambda e: finance.retire_trial(e, trial["id"], "operator")
    )
    assert store.reconcile()["balanced"]
    frozen = copy.deepcopy(store.read()["autonomous_lab"]["policy"])
    budget = store.read()["autonomous_lab"]["budget"]
    finance.periods(store.read()["autonomous_lab"], START - 86400)
    assert store.read()["autonomous_lab"]["budget"] == budget
    assert store.read()["autonomous_lab"]["policy"] == frozen
    lab.registry.close()


def test_slot_not_freed_for_holdings_dust_fault_or_uncertain_orders(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    trial = admit(lab, START)
    tick_lab(lab, START + 60, eligible=True)
    tick_lab(lab, START + 62, eligible=True)
    assert lab.paper.state["accounts"][trial["candidate"]]["positions"]
    lab.paper.state = store.transact(
        START + 63, lambda e: finance.retire_trial(e, trial["id"], "test")
    )
    assert finance.slots(lab.paper.state)["draining"] == 2
    tick_lab(lab, START + 64)
    # A venue minimum above the remaining holding causes dust, never a free slot.
    lab.paper.books["BTCUSD"]["rules"]["min_qty"] = D(100)
    lab.paper.state = store.transact(START + 66, lambda e: e.tick(lab.paper.books, {}))
    assert finance.slots(lab.paper.state)["draining"] == 2
    assert not store.archived_account(trial["candidate"])
    tick_lab(lab, START + 68)
    tick_lab(lab, START + 70)
    assert store.archived_account(trial["candidate"])
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_chart_formulas_are_causal_and_restart_after_gaps():
    bars = bars_at(START)[-21:]
    actual = overlays(bars)
    prefix = overlays(bars[:20])
    assert actual["points"][:20] == prefix["points"]
    mean = sum((b.close for b in bars[:20]), D(0)) / 20
    assert D(prefix["points"][-1]["sma"]) == mean
    assert D(prefix["points"][-1]["ema"]) == mean
    expected = mean + D(2) / 21 * (bars[-1].close - mean)
    assert D(actual["points"][-1]["ema"]) == expected
    last = bars[-1]
    gap = Bar(
        last.open_ms + 120000,
        last.open,
        last.high,
        last.low,
        last.close,
        D(0),
        last.close_ms + 120000,
    )
    after = overlays([*bars, gap])
    assert after["points"][-1]["sma"] is None and after["points"][-1]["vwap"] is None
    with pytest.raises(ValueError, match="ordered"):
        overlays([*bars, bars[-1]])


def test_real_rule_feature_refuses_stale_gapped_and_future_inputs():
    bars = bars_at(START)
    assert "atr" in rule_feature(bars, START, RuleSpec(), "paper-rest-ioc-v1")
    assert not rule_feature(bars, START + 200, RuleSpec(), "paper-rest-ioc-v1")["eligible"]
    assert "atr" not in rule_feature(
        bars[:200] + bars[201:], START, RuleSpec(), "paper-rest-ioc-v1"
    )
    assert not rule_feature(bars, START - 100, RuleSpec(), "paper-rest-ioc-v1")["eligible"]
