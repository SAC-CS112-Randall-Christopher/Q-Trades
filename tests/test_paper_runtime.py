import asyncio
import time

import httpx
import pytest

from trading.paper_engine import initial_state
from trading.paper_runtime import PaperRuntime
from trading.venue import FeedError, PublicVenue


class ReadOnlyStub:
    def __init__(self):
        self.state = initial_state(time.time())

    def read(self):
        return self.state

    def recent(self):
        return []


def instrument(base):
    return {
        "base": base,
        "quote": "USD",
        "venue_status": "TRADING",
        "spot_allowed": True,
        "minimum_notional": "1",
        "filters": [
            {
                "filterType": "LOT_SIZE",
                "stepSize": "0.00001",
                "minQty": "0.00001",
                "maxQty": "1000",
            },
            {
                "filterType": "PRICE_FILTER",
                "tickSize": "0.01",
                "minPrice": "0.01",
                "maxPrice": "1000000",
            },
        ],
    }


class CandleOutage:
    async def candles(self, symbol, limit):
        raise FeedError("Candle service temporarily unavailable")

    async def depth(self, symbol, limit):
        return {"lastUpdateId": 20, "bids": [["100", "100"]], "asks": [["100.1", "100"]]}


def test_candle_failure_does_not_stop_fresh_depth_for_position_management():
    runtime = PaperRuntime(ReadOnlyStub(), CandleOutage())
    runtime.instruments = {base + "USD": instrument(base) for base in ("BTC", "ETH")}
    runtime.metadata_at = time.time()
    frames, study, added = asyncio.run(runtime.collect())
    assert len(frames) == 2 and added == 0
    assert not study["BTCUSD"]["breakout-v1"]["eligible"]
    assert "temporarily" in study["BTCUSD"]["breakout-v1"]["reason"]


def test_persisted_sequence_rejects_regression_after_runtime_restart():
    storage = ReadOnlyStub()
    storage.state["book_sequences"] = {"BTCUSD": [21, "previous-hash"]}
    runtime = PaperRuntime(storage, CandleOutage())
    runtime.instruments = {base + "USD": instrument(base) for base in ("BTC", "ETH")}
    runtime.metadata_at = time.time()
    frames, _, _ = asyncio.run(runtime.collect())
    assert "BTCUSD" not in frames and "ETHUSD" in frames
    assert "regressed" in runtime.feed_errors["BTCUSD"]


def test_candle_adapter_is_public_get_and_rate_limit_respected():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"}, json={})

    async def scenario():
        venue = PublicVenue(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(FeedError) as error:
                await venue.candles("BTCUSD", 600)
            assert error.value.retry_after == 120
            assert requests[0].method == "GET"
            assert requests[0].url.path == "/api/v3/klines"
            assert "x-mbx-apikey" not in requests[0].headers
        finally:
            await venue.close()

    asyncio.run(scenario())
