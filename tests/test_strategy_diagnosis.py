"""Labeled original-record fixtures and disposable accounting; no market-value proof."""

import copy
import time
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_station import runtime as runtime
from test_trade_history import closure

from trading.api import create_app
from trading.config import Settings
from trading.research_storage import ResearchStorage, save_plan
from trading.scoped_tools import run
from trading.strategy_diagnosis import cost_diagnosis, input_coverage, input_row, interval_start


def packet(at=START + 300, symbol="BTCUSD"):
    return {
        "kind": "decision",
        "at": at,
        "frames": {symbol: {"source": "binance.us-depth-websocket"}},
        "state_before": {
            "accounts": {
                "primary": {
                    "version": "breakout-v1",
                    "symbols": [symbol],
                    "execution_profile": "original-frozen-fixture",
                    "last_decision": {symbol: {"at": at - 60, "reason": "prior signal"}},
                }
            }
        },
        "events": [
            {
                "kind": "decision",
                "account": "primary",
                "body": {"symbol": symbol, "at": at, "reason": "No closed-bar breakout"},
            }
        ],
        "input_eligibility": {
            "markets": {symbol: {"frame_present": True, "reason": "eligible_frame"}}
        },
        "candle_input_status": {
            symbol: {
                "continuous": True,
                "retained_bars": 600,
                "last_close_ms": at * 1000 - 1,
            }
        },
        "feature_timing": {symbol: {"available_at": at - 1, "computed_at": at - 0.5}},
        "book_features": {symbol: {"spread_bps": "2", "bid_depth_quote": "1000"}},
    }


def test_original_no_signal_is_distinct_from_absent_input_and_prior_decision():
    value = packet()
    before = copy.deepcopy(value)
    row = input_row(value, "original-reference", "BTCUSD", "primary", value["at"])
    assert row["could_evaluate"] and row["decision_at_this_tick"]
    assert row["recorded_decision"]["reason"] == "No closed-bar breakout"
    assert row["original_book_measurements"]["spread_bps"] == "2"
    assert value == before
    value["events"] = []
    value["book_features"] = {}
    value["input_eligibility"]["markets"]["BTCUSD"] = {
        "frame_present": False,
        "reason": "no_fresh_book",
    }
    row = input_row(value, "reference", "BTCUSD", "primary", value["at"])
    assert not row["could_evaluate"] and not row["decision_at_this_tick"]
    assert row["recorded_decision"] is None and row["original_book_measurements"] is None
    assert row["prior_decision"]["reason"] == "prior signal"
    assert row["problems"] == ["missing_or_stale_book"]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("continuous", False, "candle_gap"),
        ("retained_bars", 599, "warmup_incomplete"),
        ("candle_error", "missing", "candle_error"),
        ("last_close_ms", (START + 400) * 1000, "stale_or_future_candle"),
        ("last_close_ms", (START + 1) * 1000, "stale_or_future_candle"),
    ],
)
def test_each_input_boundary_remains_distinct(field, value, expected):
    original = packet()
    original["candle_input_status"]["BTCUSD"][field] = value
    row = input_row(original, "reference", "BTCUSD", "primary", original["at"])
    assert expected in row["problems"] and not row["could_evaluate"]


def test_wrong_market_account_later_features_and_unknown_availability_do_not_pass():
    original = packet()
    original["feature_timing"]["BTCUSD"]["available_at"] = original["at"] + 1
    row = input_row(original, "ref", "BTCUSD", "primary", None)
    assert {"feature_not_available_at_tick", "source_availability_unknown"} <= set(row["problems"])
    wrong = input_row(original, "ref", "ETHUSD", "other-account", original["at"])
    assert {"account_absent", "input_eligibility_unknown"} <= set(wrong["problems"])
    assert wrong["recorded_decision"] is None and wrong["original_book_measurements"] is None


def test_candles_do_not_prove_a_supported_execution_venue():
    original = packet()
    original["frames"]["BTCUSD"]["source"] = "different-venue-simulation"
    row = input_row(original, "ref", "BTCUSD", "primary", original["at"])
    assert not row["could_evaluate"]
    assert "execution_venue_unknown_or_different" in row["problems"]


def test_missing_future_and_bootstrap_feature_origins_are_not_available_inputs():
    original = packet()
    original["feature_timing"] = {}
    row = input_row(original, "ref", "BTCUSD", "primary", original["at"])
    assert "feature_timing_unknown" in row["problems"]
    original["feature_origin"] = {
        "BTCUSD": {"computed_at": original["at"] + 1, "available_at": original["at"] + 2}
    }
    row = input_row(original, "ref", "BTCUSD", "primary", original["at"])
    assert {"feature_not_computed_at_tick", "feature_not_available_at_tick"} <= set(row["problems"])
    original["feature_origin"]["BTCUSD"] = {
        "computed_at": original["at"] - 1,
        "available_at": original["at"] - 1,
        "ready_at": original["at"],
    }
    row = input_row(original, "ref", "BTCUSD", "primary", original["at"])
    assert "bootstrap_feature" in row["problems"]


def test_cold_read_budget_fails_without_returning_partial_inputs(tmp_path, monkeypatch):
    plan = plan_at(tmp_path)
    archive = ResearchStorage(plan)
    archive.append([packet()], START + 301)
    archive.close()
    import trading.strategy_diagnosis as diagnosis

    clock = iter([0, 3])
    monkeypatch.setattr(diagnosis.time, "monotonic", lambda: next(clock))
    with pytest.raises(ValueError, match="two-second"):
        input_coverage(plan, "BTCUSD", "primary", START, START + 400)


def test_indexed_population_is_bounded_and_later_availability_is_excluded(tmp_path):
    plan = plan_at(tmp_path)
    archive = ResearchStorage(plan)
    at = START + 300
    for n in range(30):
        archive.append([packet(at + n)], at + n + 0.1)
    archive.append([packet(at + 30)], at + 1000)
    archive.close()
    result = input_coverage(plan, "BTCUSD", "primary", at - 1, at + 40)
    assert result["population"]["more_retained_records"] is True
    assert result["population"]["retained_samples_inspected"] == 5
    assert result["population"]["later_available_excluded"] == 1
    assert result["population"]["total_engine_ticks"] is None
    assert all(row["source_available_at"] <= at + 40 for row in result["rows"])
    assert all(
        row["original_scope"]["execution_profile"] == "original-frozen-fixture"
        for row in result["rows"]
    )


def test_missing_archive_fails_without_reconstructing_current_data(tmp_path):
    plan = plan_at(tmp_path)
    archive = ResearchStorage(plan)
    archive.append([packet()], START + 301)
    archive.close()
    target = Path(plan.root)
    assert target.resolve().is_relative_to(tmp_path.resolve())
    for directory, pattern in (
        (target / "temporary", "*.sqlite"),
        (target / "research", "*.jsonl.gz"),
    ):
        for path in directory.glob(pattern):
            path.unlink()
    with pytest.raises((ValueError, OSError)):
        input_coverage(plan, "BTCUSD", "primary", START, START + 400)


@pytest.mark.parametrize("start", [START + 401, START - 3601, float("nan"), float("inf")])
def test_wrong_or_unbounded_interval_fails(start):
    with pytest.raises(ValueError):
        interval_start(start, START + 400)


def test_oversized_selected_records_fail_clearly_before_opening_payloads(tmp_path):
    plan = plan_at(tmp_path)
    archive = ResearchStorage(plan)
    archive.append([packet()], START + 301)
    archive.db.execute("UPDATE storage_records SET bytes=?", (9 * 1024**2,))
    archive.db.commit()
    archive.close()
    with pytest.raises(ValueError, match="eight-MiB"):
        input_coverage(plan, "BTCUSD", "primary", START, START + 400)


def test_cost_cohort_reuses_original_accounting_and_fees_once(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    event = closure()
    event["body"].update(pnl="-1", cost="101", proceeds="100", fees="2")

    def original(engine):
        engine.emit("trade_closed", "primary", event["body"])
        engine.emit("trade_closed", "breakout-v1", {**event["body"], "pnl": "90"})
        engine.emit("trade_closed", "primary", {**event["body"], "symbol": "ETHUSD", "pnl": "80"})

    store.transact(START + 300, original)
    snapshot = store.research_account("primary", START + 301)
    outcomes = store.research_outcomes(snapshot, "BTCUSD", start=START)
    outcomes["original_cost_groups"] = store.research_cost_groups(snapshot, "BTCUSD", start=START)
    result = cost_diagnosis(outcomes)
    assert result["status"] == "cost_dominated"
    assert result["measured"]["gross_before_recorded_fees_usd"] == "1"
    assert result["measured"]["net_closed_pnl_usd"] == "-1"
    assert result["population"]["closed_trades"] == 1
    assert result["source_outcomes"]["interval"] == {"start": START, "end": START + 301}
    assert result["source_outcomes"]["account"] == "primary"
    assert result["hypotheses"] and "fees" in result["facts"][0]
    group = result["measured"]["original_cost_groups"][0]
    assert group["trades"] == 1 and group["execution_profile"] is None
    assert group["holding_horizon"] is None  # Never inferred from the current account.
    assert Decimal(result["measured"]["gross_before_recorded_fees_usd"]) - Decimal(
        result["measured"]["recorded_fees_usd"]
    ) == Decimal(result["measured"]["net_closed_pnl_usd"])


def test_different_original_versions_do_not_become_one_matched_experiment(pg_store):
    store, _ = pg_store

    def original(engine):
        for n in range(18):
            body = {**closure()["body"], "version": f"original-{n:02}"}
            engine.emit("trade_closed", "primary", body)

    store.transact(START + 300, original)
    snapshot = store.research_account("primary", START + 301)
    groups = store.research_cost_groups(snapshot, "BTCUSD", start=START)
    assert groups["more_groups"] and len(groups["groups"]) == 16
    assert {row["version"] for row in groups["groups"]} == {f"original-{n:02}" for n in range(16)}
    outcomes = store.research_outcomes(snapshot, "BTCUSD", start=START)
    outcomes["original_cost_groups"] = groups
    result = cost_diagnosis(outcomes)
    assert result["population"]["closed_trades"] == 18
    assert result["population"]["more_cost_groups"]
    assert result["measured"]["matched_trial_comparison"] is None


@pytest.mark.parametrize(
    ("trades", "pnl", "fees", "expected"),
    [
        (0, "0", "0", "no_closed_trades"),
        (1, "-4", "2", "negative_before_fees"),
        (1, "2", "1", "positive_after_recorded_fees"),
        (1, "0", "0", "breakeven_after_recorded_fees"),
        (1, "0", "2", "cost_dominated"),
    ],
)
def test_negative_positive_and_no_trade_results_are_retained(trades, pnl, fees, expected):
    outcomes = {
        "market_totals": {"trades": trades, "net_pnl": pnl, "fees": fees},
        "account_totals": {"net_pnl": None, "cash": "80"},
        "open_holdings": {"BTCUSD": {}},
        "pending_orders": {},
        "events": [],
        "has_more": False,
    }
    result = cost_diagnosis(outcomes)
    assert result["status"] == expected
    assert result["measured"]["whole_account"]["net_pnl"] is None
    assert result["measured"]["open_holdings"] == {"BTCUSD": {}}


def test_real_api_saved_input_diagnosis_reopens_exactly_with_original_links(
    runtime, tmp_path, monkeypatch
):
    at = time.time() - 30
    runtime.state["last_tick"] = time.time()
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    archive = ResearchStorage(plan)
    reference = archive.append([packet(at)], at + 0.1)[0]
    archive.close()
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.paper = runtime
        body = {
            "tool": "input_diagnosis",
            "symbol": "BTCUSD",
            "account": "primary",
            "start": at - 1,
            "request_id": "diagnosis-original-01",
        }
        assert client.post("/api/research/tools/run", json=body).status_code == 403
        response = client.post(
            "/api/research/tools/run", json=body, headers={"X-Local-Operator": "1"}
        )
        assert response.status_code == 200
        saved = response.json()
        assert saved["status"] == "completed"
        assert saved["result"]["result"]["rows"][0]["reference"] == reference
        assert client.get(f"/api/research/tools/runs/{saved['id']}").json() == saved
        assert (
            client.get(f"/api/research/tools/runs/{saved['id']}/detail").json()["facts"][
                "diagnosis"
            ]
            == "input_coverage"
        )
        assert client.get("/api/research/storage/evidence", params={"reference": reference}).json()[
            "payload"
        ] == packet(at)


def test_wrong_account_and_absent_accounting_never_use_primary(runtime):
    with pytest.raises(ValueError, match="account is unavailable"):
        run(runtime, "cost_diagnosis", "BTCUSD", "absent", "no-fallback")
    with pytest.raises(ValueError, match="Durable accounting"):
        run(runtime, "cost_diagnosis", "BTCUSD", "primary", "no-accounting")


@pytest.mark.parametrize("catalog", ["empty", "other_market"])
def test_retained_input_diagnosis_does_not_require_current_catalog(runtime, tmp_path, catalog):
    at = time.time() - 30
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    archive = ResearchStorage(plan)
    reference = archive.append([packet(at)], at + 0.1)[0]
    archive.close()
    if catalog == "empty":
        runtime.instruments.clear()
    else:
        runtime.instruments.pop("BTCUSD")
    runtime.history.clear()
    before = copy.deepcopy(runtime.state)
    result = run(runtime, "input_diagnosis", "BTCUSD", "primary", "retained-original-01")
    assert result["result"]["rows"][0]["reference"] == reference
    assert result["envelope"]["security"] == "BTCUSD"
    assert runtime.state == before and not runtime.stream.records


@pytest.mark.parametrize("fault", ["stopped", "error", "stale"])
def test_retained_diagnosis_api_survives_live_worker_fault_and_reopens(runtime, tmp_path, fault):
    at = time.time() - 30
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    archive = ResearchStorage(plan)
    reference = archive.append([packet(at)], at + 0.1)[0]
    archive.close()
    runtime.running = fault != "stopped"
    runtime.error = "Synthetic live worker error" if fault == "error" else None
    runtime.state["last_tick"] = time.time() - (20 if fault == "stale" else 0)
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.paper = runtime
        body = {
            "tool": "input_diagnosis",
            "symbol": "BTCUSD",
            "account": "primary",
            "request_id": "retained-during-fault-01",
        }
        saved = client.post("/api/research/tools/run", json=body, headers={"X-Local-Operator": "1"})
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result["status"] == "completed"
        assert result["result"]["result"]["rows"][0]["reference"] == reference
        assert client.get(f"/api/research/tools/runs/{result['id']}").json() == result
        assert client.get(f"/api/research/tools/runs/{result['id']}/detail").status_code == 200
        app.state.last_tool_at = 0
        body.update(tool="market_evidence", request_id="live-read-remains-guarded")
        assert (
            client.post(
                "/api/research/tools/run", json=body, headers={"X-Local-Operator": "1"}
            ).status_code
            == 503
        )


def test_compact_cost_diagnosis_retains_whole_account_basis_and_valuation_time(pg_store):
    store, _ = pg_store
    snapshot = store.research_account("primary", START + 301)
    outcomes = store.research_outcomes(snapshot, "BTCUSD", start=START)
    result = cost_diagnosis(outcomes)["measured"]
    assert result["account_totals_basis"] == outcomes["account_totals_basis"]
    assert result["accounting_at"] == outcomes["accounting_at"]
    assert result["closed_trade_cohort"] == {
        "account": "primary",
        "symbol": "BTCUSD",
        "interval": outcomes["interval"],
        "basis": "Selected interval/market closed events; not a whole-account period return",
    }


def test_retained_cost_api_without_live_catalog_keeps_native_accounting_and_guards(
    pg_store, runtime, tmp_path, monkeypatch
):
    store, _ = pg_store
    runtime.store = store
    runtime.state = store.read()
    runtime.running = False
    runtime.error = "Synthetic stopped live reader"
    runtime.instruments.clear()
    runtime.history.clear()
    monkeypatch.setattr("trading.scoped_tools.time.time", lambda: START + 301)
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.paper = runtime
        body = {
            "tool": "cost_diagnosis",
            "symbol": "BTCUSD",
            "account": "primary",
            "start": START,
            "request_id": "native-retained-cost-01",
        }
        assert client.post("/api/research/tools/run", json=body).status_code == 403
        result = client.post(
            "/api/research/tools/run", json=body, headers={"X-Local-Operator": "1"}
        )
        assert result.status_code == 200, result.text
        saved = result.json()
        assert saved["status"] == "completed", saved
        measured = saved["result"]["result"]["measured"]
        original = store.research_outcomes(
            store.research_account("primary", START + 301), "BTCUSD", start=START
        )
        assert measured["accounting_at"] == original["accounting_at"]
        assert measured["account_totals_basis"] == original["account_totals_basis"]
        assert measured["closed_trade_cohort"]["symbol"] == "BTCUSD"
        assert client.get(f"/api/research/tools/runs/{saved['id']}").json() == saved
        assert client.get(f"/api/research/tools/runs/{saved['id']}/detail").status_code == 200
        app.state.last_tool_at = 0
        runtime.disk_free = 0
        body["request_id"] = "native-retained-disk-refusal"
        assert (
            client.post(
                "/api/research/tools/run", json=body, headers={"X-Local-Operator": "1"}
            ).status_code
            == 503
        )
        assert store.reconcile()["balanced"]


def test_unexpected_counter_read_failure_has_terminal_redacted_receipt(
    runtime, tmp_path, monkeypatch
):
    at = time.time() - 30
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    archive = ResearchStorage(plan)
    archive.append([packet(at)], at + 0.1)
    archive.close()
    runtime.state["last_tick"] = time.time()

    def fail():
        raise RuntimeError("Synthetic sensitive driver text must not escape")

    monkeypatch.setattr(runtime, "public_request_counts", fail)
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.paper = runtime
        result = client.post(
            "/api/research/tools/run",
            headers={"X-Local-Operator": "1"},
            json={
                "tool": "input_diagnosis",
                "symbol": "BTCUSD",
                "request_id": "unexpected-counter-read-01",
            },
        )
        assert result.status_code == 200, result.text
        receipt = result.json()
        assert receipt["status"] == "failed" and "RuntimeError" in receipt["error"]
        assert "sensitive" not in result.text
        assert client.get(f"/api/research/tools/runs/{receipt['id']}").json() == receipt


@pytest.mark.parametrize(
    "pnl,fees,trades",
    [
        (None, "0", 1),
        ("NaN", "0", 1),
        ("Infinity", "0", 1),
        ("bad", "0", 1),
        ("0", "-1", 1),
        ("0", None, 1),
        ("0", "0", -1),
        ("0", "0", None),
        ("1", "0", 0),
    ],
)
def test_unknown_or_invalid_cost_cohort_never_gets_a_positive_status(pnl, fees, trades):
    with pytest.raises(ValueError, match="accounting totals"):
        cost_diagnosis({"market_totals": {"trades": trades, "net_pnl": pnl, "fees": fees}})
