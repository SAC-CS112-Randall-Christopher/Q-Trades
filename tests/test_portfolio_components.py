import copy
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from test_execution_replay import slices
from test_paper_engine import START, frame, study

from trading.paper_engine import PaperEngine, initial_state
from trading.portfolio_components import ComponentEngine, component_replay, scanner, size_band


def test_half_size_uses_original_risk_and_venue_minimum_without_funding_change():
    original = initial_state(START)
    original["accounts"]["primary"]["version"] = "breakout-v1"
    parent = PaperEngine(copy.deepcopy(original), START)
    a = parent.state["accounts"]["primary"]
    parent.value(a, {"BTCUSD": frame()})
    parent.enter("primary", a, "BTCUSD", frame(), study()["BTCUSD"]["breakout-v1"])
    baseline = copy.deepcopy(a["pending"]["BTCUSD"])
    engine = ComponentEngine(
        copy.deepcopy(original), START, "component_size", {("primary", "BTCUSD", START)}
    )
    b = engine.state["accounts"]["primary"]
    engine.value(b, {"BTCUSD": frame()})
    engine.enter("primary", b, "BTCUSD", frame(), study()["BTCUSD"]["breakout-v1"])
    small = b["pending"]["BTCUSD"]
    assert D(small["quantity"]) <= D(baseline["quantity"]) / 2
    assert D(small["reserved"]) < D(baseline["reserved"])
    assert b["funding"] == a["funding"] and small["stop_distance"] == baseline["stop_distance"]
    assert sum(D(line["amount"]) for line in engine.events[-1]["lines"]) == 0
    assert size_band(None) == 1 and size_band({"status": "supported", "downside_bps": -100}) == D(
        ".25"
    )
    assert (
        engine.enter("primary", b, "ETHUSD", frame(), {})
        == "Matched-entry replay: no recorded baseline entry at this point"
    )


def test_components_require_baseline_reconciliation_and_keep_open_economics(decision_packet):
    recorder, records = slices(decision_packet)
    for r in records:
        r["at"] = r["payload"]["at"]
        r["payload"]["financial_commit"] = {"committed_at": r["at"] + 0.01}
    # Commit availability belongs in the immutable hash too.
    from trading.research_evidence import digest

    for r in records:
        r["sha256"] = digest(r["payload"])
    plan = SimpleNamespace(
        test_start=records[0]["at"], test_end=records[-1]["at"], as_of=records[-1]["at"] + 1
    )
    result = component_replay(records, "component_exit", plan)
    assert result["baseline_reconciled"] and result["matched_entries"]
    assert result["fees_already_embedded_once"]
    assert result["accounts"][0]["ending"]["cash"] is not None
    late = copy.deepcopy(records)
    for r in late:
        r["payload"]["financial_commit"]["committed_at"] = plan.as_of + 1
        r["sha256"] = digest(r["payload"])
    assert component_replay(late, "component_exit", plan)["requested_decisions"] == 0
    records[0]["payload"]["after_tick_sha256"] = "0" * 64
    records[0]["sha256"] = digest(records[0]["payload"])
    assert component_replay(records, "component_exit", plan)["status"] == "unavailable"
    recorder._archive.close()


def test_same_budget_scanner_keeps_held_pending_and_does_not_invent_unobserved_outcomes():
    plan = SimpleNamespace(test_start=100, test_end=200, as_of=201)
    rows = [
        {
            "symbol": f"ASSET{i}USD",
            "eligible": True,
            "confirmed": True,
            "change_percent": str(i),
            "quote_volume": "1000000",
            "spread_bps": "2",
            "range_percent": str(10 - i),
            "trades": 1000,
        }
        for i in range(6)
    ]
    snap = {
        "scanned_at": 150,
        "metadata_at": 120,
        "captured_at": 202,
        "rows": rows,
        "held_pending": ["HELDUSD"],
    }
    r = scanner(snap, plan)
    assert r["same_extra_slot_budget"] == 4 and r["baseline"][0] == r["challenger"][0] == "HELDUSD"
    assert r["useful_future_coverage"] is None and r["unobserved_outcomes"] == 6
    assert set(r["baseline"]) != set(r["challenger"])
    snap["scanned_at"] = 300
    assert scanner(snap, plan)["status"] == "unavailable"
    assert scanner(None, plan)["status"] == "unavailable"


def test_scanner_missing_metrics_and_capacity_do_not_relax_limits():
    plan = SimpleNamespace(test_start=100, test_end=200, as_of=201)
    snap = {
        "scanned_at": 150,
        "metadata_at": 120,
        "captured_at": 202,
        "rows": [],
        "held_pending": [f"HELD{i}USD" for i in range(7)],
    }
    assert scanner(snap, plan)["status"] == "unavailable"
    with pytest.raises(ValueError):
        size_band({"status": "supported", "downside_bps": "NaN"})


def test_shorter_exit_keeps_stops_and_requires_later_book_for_fills():
    from test_paper_engine import buy

    state = initial_state(START)
    buy(state)
    at = START + 1802
    baseline = PaperEngine(copy.deepcopy(state), at)
    candidate = ComponentEngine(copy.deepcopy(state), at, "component_exit", set())
    f = frame(at, price="103", sequence=4)
    feature = study()["BTCUSD"]["breakout-v1"]
    baseline.exit_position("primary", baseline.state["accounts"]["primary"], "BTCUSD", f, feature)
    candidate.exit_position("primary", candidate.state["accounts"]["primary"], "BTCUSD", f, feature)
    assert not baseline.state["accounts"]["primary"]["pending"]
    a = candidate.state["accounts"]["primary"]
    assert a["pending"]["BTCUSD"]["reason"] == "Independent thirty-minute exit"
    assert not any(e["kind"] == "fill" for e in candidate.events)
    later = ComponentEngine(candidate.state, at + 2, "component_exit", set())
    later.tick({"BTCUSD": frame(at + 2, price="103", sequence=5)}, study())
    assert any(e["kind"] == "trade_closed" and e["account"] == "primary" for e in later.events)
