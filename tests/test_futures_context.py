import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_paper_engine import START, frame, study

from trading.futures_context import FuturesContext, FuturesPublicData
from trading.paper_engine import PaperEngine, initial_state
from trading.venue import FeedError


def metadata():
    return {
        "symbol": "PF_XBTUSD",
        "base": "BTC",
        "quote": "USD",
        "type": "flexible_futures",
        "contractSize": 1,
        "tradeable": True,
        "isExpired": False,
        "tradfi": False,
    }


def ticker():
    return {
        "symbol": "PF_XBTUSD",
        "pair": "XBT:USD",
        "tag": "perpetual",
        "suspended": False,
        "markPrice": "101",
        "indexPrice": "100",
        "openInterest": "10",
        "fundingRate": "0.02",
        "fundingRatePrediction": "-0.01",
        "lastTime": "2020-01-01T00:00:00Z",  # Last trade time is not quote snapshot time.
    }


def receipt(now=1000, mono=500, raw=None):
    return {
        "raw": {"ticker": raw or ticker()},
        "received_at": now,
        "server_at": now - 0.1,
        "received_mono": mono,
        "round_trip_ms": 200,
        "sha256": "fixture-hash",
    }


def test_units_funding_sign_and_open_interest_changes_are_contract_specific():
    context = FuturesContext()
    row = context.accept("BTCUSD", "BTC", metadata(), receipt())
    assert row["premium_bps"] == "100.00"
    assert row["funding_est_bps_hour"] == "2.0000"  # Absolute USD rate, not 2%.
    assert row["funding_direction"] == "longs pay"
    assert row["open_interest_change_pct"] is None
    raw = {**ticker(), "openInterest": "12", "fundingRate": "-0.01"}
    row = context.accept("BTCUSD", "BTC", metadata(), receipt(1060, 560, raw))
    assert row["open_interest_change_pct"] == "20.0"
    assert row["funding_direction"] == "shorts pay"
    assert row["change_interval_seconds"] == 60
    row = context.accept("BTCUSD", "BTC", metadata(), receipt(1400, 900, raw))
    assert row["open_interest_change_pct"] is None  # Do not silently compare across a gap.


@pytest.mark.parametrize(
    "patch",
    [
        {"symbol": "PI_XBTUSD"},
        {"pair": "ETH:USD"},
        {"tag": "month"},
        {"suspended": True},
        {"indexPrice": "0"},
        {"openInterest": "-1"},
        {"fundingRate": "NaN"},
        {"markPrice": True},
    ],
)
def test_bad_or_wrong_contract_observation_never_becomes_valid_context(patch):
    with pytest.raises((ValueError, ArithmeticError)):
        FuturesContext().accept("BTCUSD", "BTC", metadata(), receipt(raw={**ticker(), **patch}))


def test_stale_missing_and_clock_jump_are_unknown_not_zero():
    context = FuturesContext()
    row = context.accept("BTCUSD", "BTC", metadata(), receipt())
    row.update(capture_id="sample", received_mono=500)
    context.markets = {"BTCUSD": row}
    assert context.context_for("BTCUSD", 1001, 501)["status"] == "observed"
    assert context.context_for("BTCUSD", 1151, 651)["status"] == "stale"
    assert context.context_for("BTCUSD", 999, 501)["status"] == "stale"
    assert context.context_for("ETHUSD", 1001, 501)["status"] == "unavailable"


def test_public_client_allowlist_no_credentials_rate_limit_and_size_cap():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    async def scenario():
        client = FuturesPublicData(httpx.MockTransport(handler))
        try:
            for path in [
                "/sendorder",
                "/accounts",
                "https://example.com",
                "/tickers/../../sendorder",
            ]:
                with pytest.raises(ValueError):
                    await client.get(path)
            with pytest.raises(FeedError, match="rate limit"):
                await client.get("/tickers/PF_XBTUSD")
            with pytest.raises(FeedError, match="cooldown"):
                await client.get("/tickers/PF_XBTUSD")
            assert len(calls) == 1 and calls[0].method == "GET"
            assert "authorization" not in calls[0].headers
        finally:
            await client.close()
        client = FuturesPublicData(
            httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 65537))
        )
        try:
            with pytest.raises(FeedError, match="size limit"):
                await client.get("/tickers/PF_XBTUSD")
        finally:
            await client.close()

    asyncio.run(scenario())


def test_collector_retains_wire_evidence_and_missing_market_then_outage_is_visible():
    fail = False

    def handler(request):
        if fail:
            return httpx.Response(503)
        payload = {"result": "success", "serverTime": datetime.now(UTC).isoformat()}
        payload.update(
            {"instruments": [metadata()]}
            if request.url.path.endswith("instruments")
            else {"ticker": ticker()}
        )
        return httpx.Response(200, json=payload)

    async def scenario():
        nonlocal fail
        client = FuturesPublicData(httpx.MockTransport(handler))
        context = FuturesContext()
        try:
            report = await context.collect(client, {"BTCUSD": "BTC", "MISSINGUSD": "MISSING"})
            assert report["markets"]["BTCUSD"]["status"] == "observed"
            assert report["markets"]["MISSINGUSD"]["status"] == "unavailable"
            assert json.loads(report["receipts"][0]["wire"])["ticker"] == ticker()
            fail = True
            await context.collect(client, {"BTCUSD": "BTC"})
            assert context.snapshot()["markets"]["BTCUSD"]["status"] == "unavailable"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_context_does_not_change_cash_orders_or_signal_and_review_keeps_evidence():
    plain = PaperEngine(initial_state(START), START)
    aware = PaperEngine(initial_state(START), START)
    context = FuturesContext()
    row = context.accept("BTCUSD", "BTC", metadata(), receipt(START))
    report = {
        "version": "fixture",
        "observed_at": START,
        "capture_id": "one",
        "markets": {"BTCUSD": row},
        "receipts": [],
    }
    aware.record_futures_context(report)
    plain.tick({"BTCUSD": frame()}, study())
    aware.tick({"BTCUSD": frame()}, study())
    assert aware.state["accounts"] == plain.state["accounts"]
    assert all(not event["lines"] for event in aware.events if event["kind"] == "futures_context")
    aware.now = START + 4 * 3600
    aware.review()
    review = aware.state["review_history"][-1]
    assert review["futures_context"]["window"]["snapshots"] == 1
    saved = copy.deepcopy(review["futures_context"])
    aware.record_futures_context({**report, "observed_at": aware.now})
    assert review["futures_context"] == saved
    assert aware.state["futures_context_window"]["snapshots"] == 1


@pytest.mark.parametrize("offset", [-60, 60, None])
def test_server_time_missing_stale_or_future_is_rejected(offset):
    value = (
        (datetime.now(UTC) + timedelta(seconds=offset)).isoformat() if offset is not None else None
    )
    payload = {"result": "success", "serverTime": value, "ticker": ticker()}

    async def scenario():
        client = FuturesPublicData(httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
        try:
            with pytest.raises((ValueError, FeedError)):
                await client.get("/tickers/PF_XBTUSD")
        finally:
            await client.close()

    asyncio.run(scenario())
