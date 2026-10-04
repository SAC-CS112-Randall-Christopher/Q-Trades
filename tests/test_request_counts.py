"""Labeled transport and scheduling fixtures; no remote calls or freshness changes."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

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


@pytest.mark.parametrize("producer", ["transport", "fallback"])
def test_concurrent_bounded_dimensions_and_coupled_updates(producer, tmp_path):
    venue = PublicVenue()
    runtime = TieredPaperRuntime(ReadOnlyStub(), FallbackVenue(), tmp_path / "raw.sqlite")

    def produce(index):
        if producer == "transport":
            row = venue._request_row("/api/v3/depth", {"symbol": f"FIXTURE{index}USD"})
            venue._add_request_counts(row, "http_error", "rate_limited")
        else:
            row = runtime._fallback_count_row(f"FIXTURE{index}USD")
            runtime._add_fallback_counts(row, "checks", "due")

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(produce, range(100)))
        snapshot = (
            venue.request_counts()
            if producer == "transport"
            else runtime.public_request_counts()["fallback"]
        )
        rows = snapshot["rows"]
        first, second = (
            ("http_error", "rate_limited") if producer == "transport" else ("checks", "due")
        )
        assert len(rows) == 65 and sum(row[first] for row in rows.values()) == 100
        assert all(row[first] == row[second] for row in rows.values())
        assert rows["overflow"][first] == 36
        other = TieredPaperRuntime(ReadOnlyStub(), FallbackVenue(), tmp_path / "other.sqlite")
        assert (
            other.public_request_counts()["fallback"]["epoch"]
            != runtime.public_request_counts()["fallback"]["epoch"]
        )
    finally:
        asyncio.run(venue.close())


def test_fallback_read_remains_available_during_io_and_cancelled_attempt_is_unknown(tmp_path):
    runtime = TieredPaperRuntime(ReadOnlyStub(), FallbackVenue(), tmp_path / "raw.sqlite")

    async def scenario():
        entered = asyncio.Event()

        async def wait(*_):
            entered.set()
            await asyncio.Event().wait()

        runtime.venue.depth = wait
        request = asyncio.create_task(runtime._rest_book("BTCUSD"))
        await entered.wait()
        row = runtime.public_request_counts()["fallback"]["rows"]["BTCUSD"]
        assert row["requested"] == 1 and row["accepted"] == 0
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        row = runtime.public_request_counts()["fallback"]["rows"]["BTCUSD"]
        assert row["cancelled_unknown"] == 1 and row["accepted"] == row["failed"] == 0

    asyncio.run(scenario())


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


class InsertingDuringSnapshot(dict):
    """Let a real producer try insertion while the reader iterates its actual items."""

    def __init__(self, rows, entered, completed):
        super().__init__(rows)
        self.entered, self.completed = entered, completed

    def items(self):
        iterator = iter(super().items())
        first = next(iterator)
        yield first
        self.entered.set()
        self.completed.wait(0.5)  # A protected producer waits until this snapshot releases.
        yield from iterator


@pytest.mark.parametrize("producer", ["transport", "fallback"])
def test_real_counter_snapshot_is_safe_during_new_market_insertion(tmp_path, producer):
    entered, completed = Event(), Event()
    venue = PublicVenue(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    runtime = TieredPaperRuntime(ReadOnlyStub(), FallbackVenue(), tmp_path / "raw.sqlite")
    if producer == "transport":
        venue._request_row("/api/v3/depth", {"symbol": "BTCUSD"})
        venue._requests = InsertingDuringSnapshot(venue._requests, entered, completed)
        snapshot_read = venue.request_counts

        def write():
            asyncio.run(venue.depth("ETHUSD", 20))
    else:
        runtime._fallback_count_row("BTCUSD")
        runtime._fallback_counts = InsertingDuringSnapshot(
            runtime._fallback_counts, entered, completed
        )
        snapshot_read = runtime.public_request_counts

        async def valid(*_):
            return snapshot(levels=20)

        runtime.venue.depth = valid

        def write():
            asyncio.run(runtime._rest_book("ETHUSD"))

    def produce():
        assert entered.wait(3)
        try:
            write()
        finally:
            completed.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(produce)
            result = snapshot_read()
            future.result(timeout=3)
        rows = result["rows"] if producer == "transport" else result["fallback"]["rows"]
        assert set(rows) == {"/api/v3/depth:BTCUSD" if producer == "transport" else "BTCUSD"}
        rows_after = snapshot_read()
        rows_after = (
            rows_after["rows"] if producer == "transport" else rows_after["fallback"]["rows"]
        )
        assert len(rows_after) == 2
    finally:
        asyncio.run(venue.close())
