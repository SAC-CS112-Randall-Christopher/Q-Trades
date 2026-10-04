"""Labeled transport and scheduling fixtures; no remote calls or freshness changes."""

import asyncio
import time

import httpx
import pytest
from test_paper_runtime import ReadOnlyStub
from test_streaming import FallbackVenue, snapshot

from trading.tiered_runtime import TieredPaperRuntime
from trading.venue import FeedError, PublicVenue


@pytest.mark.parametrize(
    ("response", "field"),
    [
        (httpx.Response(200, json={}), "completed"),
        (httpx.Response(500), "http_error"),
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(200, content=b"not-json"), "invalid_payload"),
        (httpx.Response(200, json=[]), "invalid_payload"),
        (httpx.Response(200, content=b"a" * 512_001), "invalid_payload"),
    ],
)
def test_original_transport_boundary_counts_success_http_and_invalid_payloads(response, field):
    async def scenario():
        venue = PublicVenue(transport=httpx.MockTransport(lambda _: response))
        try:
            if field == "completed":
                await venue.depth("BTCUSD", 20)
            else:
                with pytest.raises(FeedError):
                    await venue.depth("BTCUSD", 20)
            row = venue.request_counts()["rows"]["/api/v3/depth:BTCUSD"]
            assert row["requested"] == row["sent"] == row["responses"] == 1
            assert row[field] == 1
            assert row["completed"] == int(field == "completed")
            if field == "rate_limited":
                assert row["http_error"] == 1 and venue._cooldown_until > time.monotonic()
        finally:
            await venue.close()

    asyncio.run(scenario())


def test_transport_failure_is_not_a_known_remote_response():
    def failed(request):
        raise httpx.ConnectTimeout("fixture", request=request)

    async def scenario():
        venue = PublicVenue(transport=httpx.MockTransport(failed))
        try:
            with pytest.raises(FeedError):
                await venue.depth("ETHUSD", 20)
            row = venue.request_counts()["rows"]["/api/v3/depth:ETHUSD"]
            assert row["sent"] == row["transport_error"] == 1 and row["responses"] == 0
        finally:
            await venue.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("after_send", [False, True])
def test_cancelled_pacing_and_unknown_inflight_have_distinct_counts(after_send):
    async def scenario():
        entered = asyncio.Event()

        async def wait(*_):
            entered.set()
            await asyncio.Event().wait()

        venue = PublicVenue(transport=httpx.MockTransport(wait))
        if not after_send:
            venue._pace = wait
        try:
            request = asyncio.create_task(venue.depth("BTCUSD", 20))
            await entered.wait()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            row = venue.request_counts()["rows"]["/api/v3/depth:BTCUSD"]
            assert row["requested"] == 1 and row["responses"] == 0
            assert row["sent"] == int(after_send)
            assert row["cancelled_after_send_unknown"] == int(after_send)
            assert row["cancelled_before_send"] == int(not after_send)
        finally:
            await venue.close()

    asyncio.run(scenario())


def test_bounded_counter_dimensions_copies_and_restart_epochs():
    async def scenario():
        venue = PublicVenue(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
        other = PublicVenue()
        try:
            for n in range(100):
                venue._request_row("/api/v3/depth", {"symbol": f"FIXTURE{n}USD"})["requested"] += 1
            view = venue.request_counts()
            assert len(view["rows"]) == 65 and view["rows"]["overflow"]["requested"] == 36
            view["rows"]["overflow"]["requested"] = 0
            assert venue.request_counts()["rows"]["overflow"]["requested"] == 36
            assert other.request_counts()["epoch"] != view["epoch"]
            assert not other.request_counts()["rows"]
            with pytest.raises(ValueError):
                await venue._get("/orders", {})
            assert len(venue.request_counts()["rows"]) == 65
        finally:
            await venue.close()
            await other.close()

    asyncio.run(scenario())


def test_schedule_waits_are_not_sends_and_metrics_reads_do_not_schedule(tmp_path):
    runtime = TieredPaperRuntime(ReadOnlyStub(), FallbackVenue(), tmp_path / "raw.sqlite")
    runtime.stream.plan = {"BTCUSD": 100}
    assert runtime._fallback_due() == ["BTCUSD"]
    runtime._fallback_at["BTCUSD"] = time.monotonic() + 10
    assert runtime._fallback_due() == []
    runtime._fallback_at.clear()
    runtime._rest_requests["BTCUSD"] = {"request_sent_at": time.time()}
    assert runtime._fallback_due() == []
    runtime._rest_retry_at = time.time() + 10
    assert runtime._fallback_due() == []
    before = runtime.public_request_counts()
    rows = before["fallback"]["rows"]
    assert rows["BTCUSD"]["due"] == rows["BTCUSD"]["spacing_wait"] == 1
    assert rows["BTCUSD"]["inflight_wait"] == rows["BTCUSD"]["retry_wait"] == 1
    assert rows["BTCUSD"]["requested"] == 0 and before["transport"] is None
    assert runtime.public_request_counts()["fallback"]["rows"] == rows
    assert not runtime._fallback  # Metrics cannot create a book.


def test_original_fallback_acceptance_and_failures_stay_distinct(tmp_path):
    runtime = TieredPaperRuntime(ReadOnlyStub(), FallbackVenue(), tmp_path / "raw.sqlite")

    async def scenario():
        async def valid(*_):
            return snapshot(levels=20)

        runtime.venue.depth = valid
        await runtime._rest_book("BTCUSD")
        counts = runtime.public_request_counts()["fallback"]["rows"]["BTCUSD"]
        assert counts["requested"] == counts["accepted"] == 1

        async def invalid(*_):
            return {}

        runtime.venue.depth = invalid
        await runtime._rest_book("BTCUSD")
        counts = runtime.public_request_counts()["fallback"]["rows"]["BTCUSD"]
        assert counts["requested"] == 2 and counts["rejected"] == 1
        assert counts["accepted"] == 1  # A later rejected book does not become accepted.

    asyncio.run(scenario())
