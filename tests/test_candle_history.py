"""Native interval transport, bounded coverage and durable exact-input recovery."""

import asyncio
import copy
import hashlib
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_research_storage import plan_at
from test_station import runtime as runtime

from trading.api import ToolRequest, create_app
from trading.candle_history import (
    INTERVALS,
    analyze_history,
    load_history,
    native_bar,
    reopen_history,
    retain_history,
)
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry
from trading.research_storage import save_plan
from trading.tool_journal import ToolJournal, encoded
from trading.venue import PublicVenue


def row(open_ms, step, price="100", volume="10"):
    return [
        open_ms,
        price,
        "101",
        "99",
        price,
        volume,
        open_ms + step - 1,
        "1000",
        1,
        "5",
        "500",
        "0",
    ]


def transport(calls, missing=False):
    def handler(request):
        query = request.url.params
        calls.append(dict(query))
        step = INTERVALS[query["interval"]] * 1000
        start, end = int(query["startTime"]), int(query["endTime"])
        times = list(range(start, end + 1, step))[: int(query["limit"])]
        if missing:
            times = [at for at in times if at != start + step]
        return httpx.Response(200, json=[row(at, step) for at in times])

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("timeframe", INTERVALS)
def test_native_timeframes_have_exact_ohlcv_and_close_cutoff(timeframe):
    calls = []
    venue = PublicVenue(transport=transport(calls))
    now = 1_800_000_123.0
    scope, raw = asyncio.run(load_history(venue, "BTCUSD", timeframe, "recent", now))
    analysis = analyze_history(scope, raw)
    asyncio.run(venue.close())
    assert analysis["timeframe"] == timeframe
    assert len(analysis["candles"]) == 240
    assert calls[0]["interval"] == timeframe
    assert analysis["coverage"]["missing_bars"] == 0
    assert analysis["coverage"]["truncated"] is False
    assert analysis["candles"][-1]["close_ms"] < now * 1000
    assert analysis["indicators"]["points"][-1]["sma100"] == "100"
    assert analysis["financial_authority"] is False
    assert raw[0][0] == analysis["candles"][0]["open_ms"]


def test_year_four_hour_complete_and_five_minute_bounded_not_full_year():
    async def run():
        calls = []
        venue = PublicVenue(transport=transport(calls))
        year, raw = await load_history(venue, "BTCUSD", "4h", "year", 1_800_000_000)
        assert len(raw) == 2190 and year["truncated"] is False
        assert len(calls) == 3
        bounded, short = await load_history(venue, "BTCUSD", "5m", "year", 1_800_000_000)
        assert len(short) == 5000 and bounded["truncated"] is True
        assert len(calls) == 8
        await venue.close()

    asyncio.run(run())


def test_missing_native_candles_are_not_filled_and_bad_pages_are_rejected():
    async def run():
        venue = PublicVenue(transport=transport([], missing=True))
        scope, raw = await load_history(venue, "BTCUSD", "5m", "recent", 1_800_000_000)
        result = analyze_history(scope, raw)
        assert result["coverage"]["missing_bars"] > 0
        assert result["gaps"]
        await venue.close()

        async def bad(*args):
            return [row(args[2], 300000), row(args[2], 300000)]

        venue = SimpleNamespace(historical_candles=bad)
        with pytest.raises(ValueError, match="duplicated"):
            await load_history(venue, "BTCUSD", "5m", "recent", 1_800_000_000)

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value", [(0, 1), (6, 300000), (1, "NaN"), (5, "-1"), (1, "1E100000"), (5, None)]
)
def test_malformed_native_bar_is_refused(field, value):
    raw = row(0, 300000)
    raw[field] = value
    with pytest.raises(ValueError):
        native_bar(raw, 300000)


def study():
    step = 300000
    raw = [row(i * step, step) for i in range(240)]
    scope = {
        "symbol": "BTCUSD",
        "timeframe": "5m",
        "window": "recent",
        "cutoff": 240 * 300,
        "observed_at": time.time(),
        "requested_start_ms": 0,
        "bounded_start_ms": 0,
        "requested_end_ms": 240 * step - 1,
        "pages": 1,
        "truncated": False,
        "source": "synthetic-native-fixture",
    }
    from trading.research_evidence import digest

    scope["source_sha256"] = digest(raw)
    return analyze_history(scope, raw), raw


def test_exact_retained_chart_and_inputs_reopen_after_journal_restart(tmp_path):
    plan = plan_at(tmp_path)
    journal = ToolJournal(tmp_path / "tools.sqlite", plan)
    analysis, raw = study()
    original = copy.deepcopy(analysis)
    identifier = journal.start(
        "candle_patterns",
        "BTCUSD",
        request_id="original-request-123",
        query={"timeframe": "5m", "window": "recent"},
    )
    compact = retain_history(plan, journal.namespace, identifier, analysis, raw)
    assert analysis == original
    journal.finish(identifier, compact, None)
    journal.close()
    journal = ToolJournal(tmp_path / "tools.sqlite", plan)
    saved = journal.find_request("original-request-123")
    assert saved["status"] == "completed"
    assert len(saved["result"]["result"]["candles"]) == 1
    reopen_history(plan, journal.namespace, saved)
    assert saved["candle_analysis"] == original
    assert hashlib.sha256(encoded(saved["result"]).encode()).hexdigest() == saved["result_sha256"]
    saved["result"]["envelope"]["candle_analysis_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="identity"):
        reopen_history(plan, journal.namespace, saved)
    journal.close()


def test_api_native_transport_save_reopen_lost_ack_and_source_identity(
    runtime, tmp_path, monkeypatch
):
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    calls = []
    venue = PublicVenue(transport=transport(calls))
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    state_before = copy.deepcopy(runtime.state)
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite", background=False, venue=venue)
    ) as client:
        client.app.state.paper = runtime
        client.app.state.lab = SimpleNamespace(registry=registry)
        headers = {"X-Local-Operator": "1"}
        query = {
            "symbol": "BTCUSD",
            "timeframe": "4h",
            "window": "year",
            "request_id": "api-candles-request-123",
        }
        assert client.post("/api/research/candle-patterns", json=query).status_code == 403
        response = client.post("/api/research/candle-patterns", json=query, headers=headers)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["status"] == "completed", saved
        assert len(saved["candle_analysis"]["candles"]) == 2190
        assert (
            hashlib.sha256(encoded(saved["result"]).encode()).hexdigest() == saved["result_sha256"]
        )
        assert len(calls) == 3
        lookup = client.get("/api/research/candle-patterns/requests/api-candles-request-123")
        assert lookup.json() == saved
        assert client.get(f"/api/research/tools/runs/{saved['id']}").json() == saved
        client.app.state.last_tool_at = 0
        assert (
            client.post("/api/research/candle-patterns", json=query, headers=headers).json()
            == saved
        )
        assert len(calls) == 3
        client.app.state.last_tool_at = 0
        query["timeframe"] = "5m"
        assert (
            client.post("/api/research/candle-patterns", json=query, headers=headers).status_code
            == 503
        )
        assert len(calls) == 3
        client.app.state.last_tool_at = 0
        maximum_query = {**query, "request_id": "maximum-api-native-request-123"}
        maximum = client.post("/api/research/candle-patterns", json=maximum_query, headers=headers)
        assert maximum.status_code == 200, maximum.text
        maximum_saved = maximum.json()
        assert maximum_saved["status"] == "completed", maximum_saved
        assert len(maximum_saved["candle_analysis"]["candles"]) == 5000
        assert maximum_saved["candle_analysis"]["coverage"]["truncated"] is True
        assert len(calls) == 8
        assert client.get(f"/api/research/tools/runs/{maximum_saved['id']}").json() == maximum_saved
        assert (
            hashlib.sha256(encoded(maximum_saved["result"]).encode()).hexdigest()
            == maximum_saved["result_sha256"]
        )
        assert registry.db.execute("SELECT count(*) FROM evidence_windows").fetchone()[0] > 0
    assert runtime.state == state_before
    registry.close()


def test_existing_live_request_is_returned_without_refetch_even_from_another_owner(
    runtime, tmp_path
):
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    calls = []
    venue = PublicVenue(transport=transport(calls))
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite", background=False, venue=venue)
    ) as client:
        client.app.state.paper = runtime
        journal = client.app.state.tool_journal
        command = ToolRequest(
            tool="candle_patterns",
            symbol="BTCUSD",
            timeframe="5m",
            window="recent",
            request_id="unresolved-live-request-123",
        )
        identifier, created = journal.start_once(
            "candle_patterns",
            "BTCUSD",
            request_id=command.request_id,
            query=command.model_dump(exclude={"request_id"}),
        )
        assert created
        replacement = ToolJournal(tmp_path / "research-tools.sqlite3", plan)
        try:
            assert replacement.owner != journal.owner
            client.app.state.tool_journal = replacement
            response = client.post(
                "/api/research/candle-patterns",
                json={
                    key: value
                    for key, value in command.model_dump().items()
                    if key not in {"tool", "account", "start"}
                },
                headers={"X-Local-Operator": "1"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["id"] == identifier
            assert response.json()["status"] == "running"
            assert calls == []
        finally:
            client.app.state.tool_journal = journal
            replacement.close()


def test_maximum_native_study_retains_every_legal_long_decimal_and_exact_hash(tmp_path):
    from trading.research_evidence import digest

    plan = plan_at(tmp_path)
    journal = ToolJournal(tmp_path / "tools.sqlite", plan)
    raw = [row(i * 300000, 300000) for i in range(5000)]
    # Long provider decimal strings are legal observations, not a reason to drop
    # candles or raise the existing ResearchStorage packet-size policy.
    for item in raw:
        item[1:6] = [
            "100." + "1" * 60,
            "101." + "2" * 60,
            "99." + "3" * 61,
            "100." + "4" * 60,
            "10." + "5" * 61,
        ]
    scope = {
        "symbol": "BTCUSD",
        "timeframe": "5m",
        "window": "year",
        "cutoff": 5000 * 300,
        "observed_at": time.time(),
        "requested_start_ms": 0,
        "bounded_start_ms": 0,
        "requested_end_ms": 5000 * 300000 - 1,
        "pages": 5,
        "truncated": False,
        "source": "synthetic-native-long-decimal-fixture",
        "source_sha256": digest(raw),
    }
    analysis = analyze_history(scope, raw)
    assert len(encoded(analysis).encode()) > 2 * 1024**2
    identifier = journal.start(
        "candle_patterns",
        "BTCUSD",
        request_id="maximum-legal-study-123",
        query={"timeframe": "5m", "window": "year"},
    )
    journal.finish(
        identifier, retain_history(plan, journal.namespace, identifier, analysis, raw), None
    )
    saved = journal.get(identifier)
    assert saved["status"] == "completed"
    reopen_history(plan, journal.namespace, saved)
    assert saved["candle_analysis"] == analysis
    assert len(saved["candle_analysis"]["candles"]) == 5000
    assert hashlib.sha256(encoded(saved["result"]).encode()).hexdigest() == saved["result_sha256"]
    journal.close()


def test_many_actual_gap_observations_keep_bounded_overview_and_exact_full_history(tmp_path):
    from trading.research_evidence import digest

    plan = plan_at(tmp_path)
    journal = ToolJournal(tmp_path / "tools.sqlite", plan)
    raw = [row(i * 600000, 300000) for i in range(2500)]
    scope = {
        "symbol": "BTCUSD",
        "timeframe": "5m",
        "window": "year",
        "cutoff": 5000 * 300,
        "observed_at": time.time(),
        "requested_start_ms": 0,
        "bounded_start_ms": 0,
        "requested_end_ms": 5000 * 300000 - 1,
        "pages": 5,
        "truncated": False,
        "source": "synthetic-native-gap-fixture",
        "source_sha256": digest(raw),
    }
    analysis = analyze_history(scope, raw)
    assert len(analysis["gaps"]) == 2499
    identifier = journal.start(
        "candle_patterns",
        "BTCUSD",
        request_id="maximum-gap-study-123",
        query={"timeframe": "5m", "window": "year"},
    )
    overview = retain_history(plan, journal.namespace, identifier, analysis, raw)
    assert len(overview["result"]["gaps"]) == 1
    assert overview["result"]["coverage"]["gaps_omitted_from_overview"] == 2498
    assert len(encoded(overview).encode()) < 131072
    journal.finish(identifier, overview, None)
    saved = journal.get(identifier)
    assert saved["status"] == "completed"
    reopen_history(plan, journal.namespace, saved)
    assert saved["candle_analysis"] == analysis
    assert hashlib.sha256(encoded(saved["result"]).encode()).hexdigest() == saved["result_sha256"]
    journal.close()
