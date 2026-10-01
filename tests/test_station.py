import copy
import hashlib
import json
import time
from collections import deque
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from test_paper_runtime import ReadOnlyStub, instrument

from trading.api import create_app
from trading.config import Settings
from trading.market import parse_book
from trading.paper_strategy import Bar
from trading.station import (
    TOOLS,
    cost_hurdle,
    execute_tool,
    market_detail,
    market_live,
    strategy_experiments,
)
from trading.tiered_runtime import TieredPaperRuntime
from trading.tool_journal import MAX_RESULT_BYTES, ToolJournal


@pytest.fixture
def runtime(tmp_path, book):
    runtime = TieredPaperRuntime(ReadOnlyStub(), None, tmp_path / "raw.sqlite")
    runtime.running = True
    runtime.disk_free = 10 * 1024**3  # A healthy fixture must not depend on host /tmp capacity.
    runtime.instruments = {"BTCUSD": instrument("BTC"), "ETHUSD": instrument("ETH")}
    runtime.metadata_at = time.time()
    runtime.stream.plan = {"BTCUSD": 100}
    runtime._fallback["BTCUSD"] = {
        "book": parse_book(book),
        "observed": time.time(),
        "received_mono": time.monotonic(),
        "source": "binance.us-rest-fallback",
        "exchange_event_ms": None,
    }
    runtime.stream.stats["BTCUSD"] = {"trades": 0, "trade_gaps": 0}
    runtime.stream.trade_tape["BTCUSD"] = deque(maxlen=40)
    runtime.universe.rows = [
        {"symbol": "BTCUSD", "eligible": True, "confirmed": True, "reason": "Qualified"},
        {"symbol": "ETHUSD", "eligible": False, "confirmed": False, "reason": "Unavailable"},
    ]
    runtime.history["BTCUSD"] = [
        Bar(
            n * 60000,
            Decimal(100),
            Decimal(102),
            Decimal(99),
            Decimal(101),
            Decimal(5),
            n * 60000 + 59999,
        )
        for n in range(200)
    ]
    runtime.state["accounts"]["primary"]["last_decision"]["BTCUSD"] = {
        "reason": "No closed-bar breakout",
        "at": 1,
        "bar": 0,
        "version": "breakout-v1",
    }
    return runtime


def test_tools_read_real_inputs_without_changing_account_or_sequence_state(runtime):
    before = copy.deepcopy((runtime.state, runtime._previous_books, runtime.study))
    for name in TOOLS:
        result = execute_tool(runtime, name, "BTCUSD")
        assert result["tool"] == name and result["result"]
        assert len(json.dumps(result).encode()) < 131072
    assert before == (runtime.state, runtime._previous_books, runtime.study)
    assert not runtime.stream.records
    with pytest.raises(ValueError, match="not registered"):
        execute_tool(runtime, "place_order", "BTCUSD")
    with pytest.raises(ValueError, match="known USD"):
        execute_tool(runtime, "market_evidence", "../../secrets")


def test_full_history_market_evidence_can_be_saved_and_reopened(runtime, tmp_path, monkeypatch):
    runtime.history["BTCUSD"] = [
        Bar(
            n * 60000,
            Decimal(100),
            Decimal(102),
            Decimal(99),
            Decimal("100.1234567890123456789012345") + Decimal(n % 37) / 1000,
            Decimal("5.123456789012345678901234567"),
            n * 60000 + 59999,
        )
        for n in range(600)
    ]
    quotes = runtime.quotes()
    selected_quote = next(row for row in quotes["markets"] if row["symbol"] == "BTCUSD")
    quotes["markets"] += [{**selected_quote, "symbol": f"AAA{n}USD"} for n in range(100)]
    monkeypatch.setattr(runtime, "quotes", lambda: quotes)
    runtime.universe.rows = [
        {"symbol": f"AAA{n}USD", "eligible": True, "reason": "Qualified"} for n in range(100)
    ] + [{"symbol": "BTCUSD", "eligible": True, "reason": "Qualified"}]
    runtime.stream.plan = {}
    original_detail = market_detail(runtime, "BTCUSD")
    original = {"live": market_live(runtime, "BTCUSD"), "detail": original_detail}
    assert len(json.dumps(original, separators=(",", ":")).encode()) > MAX_RESULT_BYTES
    assert all(row["symbol"] != "BTCUSD" for row in original_detail["scan"]["rows"])
    before = copy.deepcopy((runtime.state, runtime.history, runtime.study, runtime.universe.rows))

    result = execute_tool(runtime, "market_evidence", "BTCUSD")
    journal = ToolJournal(tmp_path / "tools.sqlite3")
    try:
        run_id = journal.start("market_evidence", "BTCUSD")
        journal.finish(run_id, result, None)
        saved = journal.get(run_id)
        assert saved["status"] == "completed", saved["error"]
        assert saved["result"] == result
        assert len(json.dumps(result, separators=(",", ":")).encode()) <= MAX_RESULT_BYTES
        evidence = saved["result"]["result"]
        assert [q["symbol"] for q in evidence["live"]["markets"]] == ["BTCUSD"]
        assert evidence["live"]["markets_omitted"] == len(quotes["markets"]) - 1
        detail = evidence["detail"]
        assert [row["symbol"] for row in detail["scan"]["rows"]] == ["BTCUSD"]
        assert detail["scan"]["omitted"] == 100
        assert detail["candles"] == original_detail["candles"]
        assert detail["indicators"]["points"] == original_detail["indicators"]["points"][-120:]
        assert detail["indicators"]["points_omitted"] == 480
        assert detail["indicators"]["calculation_history_bars"] == 600
        assert (
            detail["indicators"]["vwap_anchor_ms"]
            == original_detail["indicators"]["vwap_anchor_ms"]
        )
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        assert saved["result_sha256"] == hashlib.sha256(encoded).hexdigest()
    finally:
        journal.close()
    reopened = ToolJournal(tmp_path / "tools.sqlite3")
    try:
        assert reopened.get(run_id) == saved
    finally:
        reopened.close()
    assert before == (runtime.state, runtime.history, runtime.study, runtime.universe.rows)
    assert len(market_detail(runtime, "BTCUSD")["indicators"]["points"]) == 600
    assert len(market_live(runtime, "BTCUSD")["markets"]) == len(quotes["markets"])


def test_market_evidence_retains_gaps_warmup_and_missing_data(runtime):
    runtime.history["BTCUSD"].pop(-5)
    original = market_detail(runtime, "BTCUSD")
    evidence = execute_tool(runtime, "market_evidence", "BTCUSD")["result"]
    detail = evidence["detail"]
    assert detail["candle_gaps"] == original["candle_gaps"] and detail["candle_gaps"]
    assert detail["candles_stale"]
    assert detail["indicators"]["points"] == original["indicators"]["points"][-120:]
    assert detail["indicators"]["points"][-1]["ema"] is None  # Gap restarts chart warmup.
    missing = execute_tool(runtime, "market_evidence", "ETHUSD")["result"]
    assert missing["live"]["book"] is None and missing["live"]["trades"] == []
    assert missing["detail"]["candles"] == []
    assert missing["detail"]["indicators"]["points"] == []
    assert missing["detail"]["indicators"]["calculation_history_bars"] == 0
    assert missing["detail"]["indicators"]["points_omitted"] == 0
    assert missing["detail"]["strategy"]["last_decision"] is None


def test_outcome_totals_are_net_and_limited_to_the_selected_market_sample(runtime):
    account = runtime.state["accounts"]["primary"]
    account["recent_trades"] = [
        {"symbol": "BTCUSD", "pnl": "1000", "fees": "1"},
        *[{"symbol": "BTCUSD", "pnl": "-0.13", "fees": "0.10"} for _ in range(30)],
        {"symbol": "ETHUSD", "pnl": "20", "fees": "2"},
    ]
    result = execute_tool(runtime, "outcome_review", "BTCUSD")["result"]
    assert result["sample_totals"] == {"trades": 30, "net_pnl": "-3.90", "fees": "3.00"}
    assert result["retained_market_count"] == 31
    assert result["omitted_retained_market_trades"] == 1
    assert result["account_totals"]["funding"] == account["funding"]


def test_strategy_view_uses_frozen_rules_actual_accounts_and_recorded_review(runtime):
    runtime.state["accounts"]["primary"]["version"] = "selective-v1"
    runtime.state["accounts"]["responsive-v1"].update(equity="91.30", funding="200")
    runtime.state["review_history"] = [
        {
            "at": 100,
            "selected": "breakout-v1",
            "reason": "Retain version",
            "windows": [
                {"start": n, "end": n + 1, "scores": {"breakout-v1": {"trades": n}}}
                for n in range(3)
            ],
        }
    ]
    before = copy.deepcopy(runtime.state)
    result = strategy_experiments(runtime, "BTCUSD")
    assert result["active_version"] == "selective-v1"
    variants = {v["version"]: v for v in result["variants"]}
    assert variants["responsive-v1"]["rules"]["lookback"] == 7
    assert variants["selective-v1"]["rules"]["volume_multiple"] == "2.5"
    assert variants["responsive-v1"]["account"]["net_pnl"] == "-108.70"
    assert result["latest_review"]["selected"] == "breakout-v1"
    assert len(result["latest_review"]["windows"]) == 2
    assert runtime.state == before


def test_signal_display_expires_and_does_not_promote_missing_or_boundary_signals(runtime):
    runtime.study["BTCUSD"] = {
        "breakout-v1": {
            "bar_open_ms": int(time.time() // 60) * 60000 - 60000,
            "close": "100",
            "breakout": "100",
            "atr": "1",
            "trend_up": True,
            "volume_ratio": "2",
        }
    }
    baseline = strategy_experiments(runtime, "BTCUSD")["variants"][0]
    assert baseline["feature_fresh"]
    assert baseline["checks"] == {
        "trend": True,
        "breakout": False,
        "volume": False,
        "extension": True,
    }
    runtime.study["BTCUSD"]["breakout-v1"]["bar_open_ms"] -= 120000
    stale = strategy_experiments(runtime, "BTCUSD")["variants"][0]
    assert not stale["feature_fresh"] and all(v is None for v in stale["checks"].values())
    missing = strategy_experiments(runtime, "ETHUSD")["variants"][0]
    assert not missing["feature_fresh"] and missing["features"] == {}


def test_cost_hurdle_includes_spread_fees_adverse_prices_and_tick_rounding(runtime):
    result = cost_hurdle(runtime, "BTCUSD")
    assert result["fee_per_side"] == "0.001"
    assert result["adverse_price_per_side"] == "0.0002"
    assert Decimal(result["required_bid"]) > Decimal("100.10")
    # Selling at the reported bid clears the modeled entry and fee cost, after tick rounding.
    tick = Decimal(result["price_tick"])
    entry = (Decimal("100.10") * Decimal("1.0002") / tick).to_integral_value(
        rounding="ROUND_UP"
    ) * tick
    exit_price = (Decimal(result["required_bid"]) * Decimal("0.9998") / tick).to_integral_value(
        rounding="ROUND_DOWN"
    ) * tick
    assert exit_price * Decimal("0.999") >= entry * Decimal("1.001")
    runtime._fallback["BTCUSD"]["received_mono"] -= 10
    with pytest.raises(ValueError, match="fresh quote"):
        cost_hurdle(runtime, "BTCUSD")


def test_market_bounds_missing_data_and_candle_gaps_are_honest(runtime):
    detail = market_detail(runtime, "BTCUSD")
    assert len(detail["candles"]) == 120
    assert detail["candles"][0]["open_ms"] == 80 * 60000
    assert detail["candles"][0]["close"] == "101"
    runtime.history["BTCUSD"].pop(-5)
    assert len(market_detail(runtime, "BTCUSD")["candle_gaps"]) == 1
    missing = market_live(runtime, "ETHUSD")
    assert missing["book"] is None and missing["trades"] == []
    assert market_detail(runtime, "ETHUSD")["candles"] == []
    assert market_detail(runtime, "ETHUSD")["strategy"]["last_decision"] is None


def test_display_projects_event_summary_and_keeps_journal_identity(runtime):
    original = {
        "id": 123,
        "at": 100,
        "kind": "fill",
        "body": {
            "symbol": "BTCUSD",
            "quantity": "0.001",
            "reason": "ATR stop",
            "raw_observation": "x" * 50000,
        },
    }
    runtime.recent = [original]
    result = market_detail(runtime, "BTCUSD")["paper_events"][0]
    assert result["id"] == 123 and result["body"]["quantity"] == "0.001"
    assert "raw_observation" not in result["body"]
    assert runtime.recent[0] == original


def test_trade_tape_is_bounded_deduplicated_and_keeps_exchange_time(runtime):
    for n in range(60):
        runtime.stream.accept_aux(
            "BTCUSD", {"e": "trade", "t": n, "T": n * 1000, "p": "100.01", "q": "0.002"}, 100, 20
        )
    assert len(runtime.stream.trade_tape["BTCUSD"]) == 40
    result = market_live(runtime, "BTCUSD")
    assert len(result["trades"]) == 20 and result["trades"][0]["id"] == 59
    assert result["trades"][0]["exchange_ms"] == 59000
    runtime.stream.accept_aux(
        "BTCUSD", {"e": "trade", "t": 59, "T": 59000, "p": "100.01", "q": "0.002"}, 100, 20
    )
    assert runtime.stream.stats["BTCUSD"]["trades"] == 60
    runtime.stream.accept_aux(
        "BTCUSD", {"e": "trade", "t": 62, "T": 62000, "p": "100.01", "q": "0.002"}, 100, 20
    )
    assert market_live(runtime, "BTCUSD")["trade_gaps"] == 1


def test_tool_receipts_preserve_failures_results_and_interrupted_runs(tmp_path):
    path = tmp_path / "tools.sqlite3"
    journal = ToolJournal(path)
    complete = journal.start("strategy_evidence", "BTCUSD")
    receipt = {"result": {"reason": "No breakout"}}
    journal.finish(complete, receipt, None)
    failed = journal.start("place_order", "BTCUSD")
    journal.finish(failed, None, "Tool is not registered")
    interrupted = journal.start("market_evidence", "ETHUSD")
    journal.close()
    reopened = ToolJournal(path)
    try:
        assert reopened.recent()["total"] == 3
        saved = reopened.get(complete)
        assert saved["status"] == "completed" and saved["result"] == receipt
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        assert saved["result_sha256"] == hashlib.sha256(encoded).hexdigest()
        assert reopened.get(failed)["status"] == "failed"
        assert reopened.get(interrupted)["status"] == "interrupted"
        reopened.finish(complete, {"rewritten": True}, None)
        assert reopened.get(complete) == saved
    finally:
        reopened.close()


def test_tool_capacity_blocks_new_work_without_pruning_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.tool_journal.MAX_RUNS", 1)
    journal = ToolJournal(tmp_path / "tools.sqlite3")
    try:
        first = journal.start("market_evidence", "BTCUSD")
        journal.finish(first, {"large": "x" * 131072}, None)
        assert journal.get(first)["status"] == "failed"
        with pytest.raises(ValueError, match="capacity"):
            journal.start("cost_hurdle", "BTCUSD")
        assert journal.get(first)["status"] == "failed"
    finally:
        journal.close()


def test_station_api_authority_receipts_and_read_only_routes(runtime, tmp_path):
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    before = copy.deepcopy(runtime.state)
    with TestClient(app) as client:
        app.state.paper = runtime
        assert client.get("/api/station/live?symbol=BTCUSD").json()["book"]["bids"][0][0] == "99.90"
        assert (
            client.get("/api/station/detail?symbol=BTCUSD").json()["strategy"]["last_decision"][
                "reason"
            ]
            == "No closed-bar breakout"
        )
        args = {"tool": "strategy_evidence", "symbol": "BTCUSD"}
        assert client.post("/api/research/tools/run", json=args).status_code == 403
        headers = {"X-Local-Operator": "1", "Origin": "http://testserver"}
        denied = {**headers, "Origin": "https://testserver"}
        assert client.post("/api/research/tools/run", json=args, headers=denied).status_code == 403
        run = client.post("/api/research/tools/run", json=args, headers=headers).json()
        assert run["status"] == "completed"
        assert client.get(f"/api/research/tools/runs/{run['id']}").json() == run
        assert client.post("/api/research/tools/run", json=args, headers=headers).status_code == 429
        app.state.last_tool_at = 0
        market_run = client.post(
            "/api/research/tools/run",
            json={"tool": "market_evidence", "symbol": "BTCUSD"},
            headers=headers,
        ).json()
        assert market_run["status"] == "completed"
        assert market_run["result"]["version"] == "market-evidence-tools-v2"
        assert len(market_run["result"]["result"]["detail"]["indicators"]["points"]) == 120
        assert client.get(f"/api/research/tools/runs/{market_run['id']}").json() == market_run
        app.state.last_tool_at = 0
        bad = client.post(
            "/api/research/tools/run", json={**args, "tool": "place_order"}, headers=headers
        )
        assert bad.json()["status"] == "failed"
        assert client.get("/api/research/tools").json()["total"] == 3
        runtime.running = False
        assert client.post("/api/research/tools/run", json=args, headers=headers).status_code == 503
    assert runtime.state == before


def test_station_optional_tools_respect_low_disk_without_changing_accounts(runtime, tmp_path):
    runtime.disk_free = 5 * 1024**3 - 1
    before = copy.deepcopy(runtime.state)
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    with TestClient(app) as client:
        client.app.state.paper = runtime
        response = client.post(
            "/api/research/tools/run",
            json={"tool": "strategy_evidence", "symbol": "BTCUSD"},
            headers={"X-Local-Operator": "1", "Origin": "http://testserver"},
        )
        assert response.status_code == 503
        assert "free disk" in response.json()["detail"]
        assert runtime.state == before
