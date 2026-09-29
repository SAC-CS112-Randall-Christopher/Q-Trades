import asyncio
import json
import time
from collections import deque
from decimal import Decimal

import pytest
from test_paper_runtime import ReadOnlyStub, instrument

from trading.engine_diagnostics import EngineWorkDiagnostics
from trading.stream_book import DepthBook, StreamGap
from trading.stream_capture import StreamCapture
from trading.stream_feed import ExchangeClock, StreamFeed
from trading.tiered_runtime import TieredPaperRuntime
from trading.universe import Universe


def test_resource_guard_ignores_isolated_jitter_but_demotes_sustained_or_severe_stalls():
    runtime = object.__new__(TieredPaperRuntime)
    runtime._loop_ms = deque(maxlen=1000)
    runtime._constrained_until = 0
    runtime._work_diagnostics = EngineWorkDiagnostics()
    runtime._notice_queue = []
    for duration in [20] * 19 + [150]:
        runtime.observe_engine_work(duration, 1000)
    assert runtime._constrained_until == 0
    for duration in [150] * 3:
        runtime.observe_engine_work(duration, 1001)
    assert runtime._constrained_until == 1301
    runtime._loop_ms.clear()
    runtime.observe_engine_work(1000, 2000)
    assert runtime._constrained_until == 2300


def snapshot(sequence=100, levels=30):
    return {
        "lastUpdateId": sequence,
        "bids": [[str(Decimal("100") - Decimal(i) / 10), "10"] for i in range(levels)],
        "asks": [[str(Decimal("101") + Decimal(i) / 10), "10"] for i in range(levels)],
    }


def event(first=101, last=101, stamp=1000, bids=None, asks=None):
    return {
        "e": "depthUpdate",
        "s": "BTCUSD",
        "U": first,
        "u": last,
        "E": stamp,
        "b": bids or [],
        "a": asks or [],
    }


def test_book_applies_absolute_quantities_and_zero_removals_and_ignores_old_events():
    local = DepthBook(snapshot())
    book = local.apply(event(bids=[["100", "2"], ["99.9", "0"]]))
    assert book.bids[0] == (Decimal("100"), Decimal("2"))
    assert len(book.bids) == 20 and Decimal("99.9") not in dict(book.bids)
    assert local.apply(event()) is None
    with pytest.raises(StreamGap, match="Missing depth"):
        local.apply(event(103, 104))


def test_book_accepts_overlap_with_snapshot_but_never_unknown_deep_levels():
    local = DepthBook(snapshot())
    assert local.apply(event(99, 102, bids=[["1", "5000"]]))
    assert Decimal("1") not in local.bids
    with pytest.raises(StreamGap, match="coverage"):
        local.apply(
            event(103, 103, bids=[[str(Decimal(100) - Decimal(i) / 10), "0"] for i in range(11)])
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"U": True},
        {"E": "1000"},
        {"u": 99, "U": 101},
        {"b": [["100", "NaN"]]},
        {"b": [["100", "1"], ["100", "2"]]},
        {"b": [["102", "1"]]},
    ],
)
def test_corrupt_or_crossed_depth_never_becomes_an_executable_book(patch):
    local = DepthBook(snapshot())
    with pytest.raises(ValueError):
        local.apply({**event(), **patch})


def clock_at(wall, mono):
    clock = ExchangeClock()
    clock.checked_mono = mono
    clock.wall_minus_mono = wall - mono
    clock.offset_ms = 10
    clock.uncertainty_ms = 25
    return clock


def test_clock_uncertainty_staleness_and_wall_clock_jump_fail_closed():
    wall, mono = 10000.0, 200.0
    clock = clock_at(wall, mono)
    assert clock.age(int(wall * 1000) - 40, wall, mono) == 50
    with pytest.raises(StreamGap, match="delayed"):
        clock.age(int(wall * 1000) - 980, wall, mono)
    with pytest.raises(StreamGap, match="future"):
        clock.age(int(wall * 1000) + 1000, wall, mono)
    with pytest.raises(StreamGap, match="clock"):
        clock.age(int(wall * 1000), wall + 1, mono)
    assert not clock.valid(wall + 181, mono + 181)


def test_raw_capture_is_bounded_and_retains_newest_with_pruning_accounted(tmp_path):
    capture = StreamCapture(tmp_path / "raw.sqlite", max_bytes=600, max_rows=4)
    try:
        for i in range(10):
            result = capture.append(
                [
                    {
                        "kind": "message",
                        "received_at": i,
                        "raw": "x" * 100,
                        "exchange_event_ms": i * 1000,
                    }
                ]
            )
        assert result["retained"] <= 4 and result["bytes"] <= 600
        assert result["captured"] == result["retained"] + result["pruned"] == 10
        newest = json.loads(
            capture.connection.execute(
                "SELECT body FROM observations ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        )
        assert newest["received_at"] == 9
        assert result["physical_bytes"] > 0
    finally:
        capture.close()


def ticker(symbol, now, *, spread="100.1", change="5"):
    return {
        "symbol": symbol,
        "bidPrice": "100",
        "askPrice": spread,
        "quoteVolume": "500000",
        "lowPrice": "90",
        "highPrice": "110",
        "priceChangePercent": change,
        "count": 500,
        "closeTime": int(now * 1000),
    }


def test_universe_confirmed_promotion_demotion_capacity_and_held_protection():
    universe = Universe()
    universe.instruments = {
        s + "USD": instrument(s) for s in ("BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "ADA", "AVAX")
    }
    now = 1000.0
    universe.metadata_at = now
    ticks = [ticker(s, now) for s in universe.instruments]
    universe.screen(ticks, now, set())
    assert not universe.selected
    universe.screen(ticks, now + 60, set())
    assert len(universe.selected) == 4
    held = {universe.selected[0]}
    study = {s: {"v": {"eligible": True}} for s in universe.selected}
    plan = universe.plan(study, held, constrained=False)
    assert len(plan) == 6 and plan[next(iter(held))] == 100
    for tick in ticks:
        tick["askPrice"] = "150"  # Disqualifies observations, not existing position management.
    universe.screen(ticks, now + 61, held)
    assert universe.selected == sorted(held)
    assert set(universe.plan(study, held, constrained=True)) == {"BTCUSD", "ETHUSD"} | held


def test_missing_ticker_breaks_qualification_streak():
    universe = Universe()
    universe.instruments = {"SOLUSD": instrument("SOL")}
    universe.metadata_at = 1000
    universe.screen([ticker("SOLUSD", 1000)], 1000, set())
    universe.screen([], 1060, set())
    universe.screen([ticker("SOLUSD", 1120)], 1120, set())
    assert not universe.selected


class FallbackVenue:
    async def depth(self, symbol, limit):
        return snapshot()


def test_fallback_records_request_timing_without_fabricating_exchange_timestamp(tmp_path):
    runtime = TieredPaperRuntime(ReadOnlyStub(), FallbackVenue(), tmp_path / "raw.sqlite")
    runtime.stream.plan = {"BTCUSD": 100}
    runtime.instruments = {"BTCUSD": instrument("BTC")}
    runtime.metadata_at = time.time()

    # REST returns twenty levels, unlike the synchronization snapshot.
    async def depth(symbol, limit):
        return snapshot(levels=20)

    runtime.venue.depth = depth
    asyncio.run(runtime._rest_book("BTCUSD"))
    frames, _ = runtime.current_frames()
    assert frames["BTCUSD"]["source"] == "binance.us-rest-fallback"
    assert frames["BTCUSD"]["exchange_event_ms"] is None
    assert frames["BTCUSD"]["round_trip_ms"] >= 0
    runtime._fallback["BTCUSD"]["received_mono"] -= 2
    assert not runtime.current_frames()[0]


def test_minute_summary_preserves_observed_depth_and_avoids_duplicate_sample(tmp_path):
    runtime = TieredPaperRuntime(ReadOnlyStub(), FallbackVenue(), tmp_path / "raw.sqlite")
    from trading.market import parse_book

    frames = {
        "BTCUSD": {
            "book": parse_book(snapshot(levels=20), 20),
            "observed": 120,
            "source": "binance.us-rest-fallback",
        }
    }
    runtime.summarize_books(frames, 120)
    runtime.summarize_books(frames, 120.1)
    runtime.summarize_books({}, 180)
    summary = runtime._notice_queue[-1]
    assert summary["kind"] == "market_minute" and summary["body"]["samples"] == 1
    assert Decimal(summary["body"]["mean_spread_bps"]) > 0
    assert "bid_depth_quote" in summary["body"]["last_depth"]


def test_stream_plan_rejects_arbitrary_hosts_and_unbounded_subscriptions():
    async def scenario():
        stream = StreamFeed(FallbackVenue())
        with pytest.raises(ValueError):
            await stream.configure({"http://elsewhereUSD": 100})
        with pytest.raises(ValueError):
            await stream.configure({str(i) + "USD": 100 for i in range(9)})

    asyncio.run(scenario())


def test_stream_gap_reconnects_and_requires_new_snapshot_before_reusing_books(monkeypatch):
    class Venue:
        calls = 0

        async def server_time(self):
            return {"serverTime": int(time.time() * 1000)}

        async def depth(self, symbol, limit):
            self.calls += 1
            return snapshot(sequence=self.calls * 100)

    class Socket:
        connections = 0

        def __init__(self):
            Socket.connections += 1
            self.number = Socket.connections
            self.count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def recv(self):
            self.count += 1
            await asyncio.sleep(0.01)
            if self.count > 2 or (self.number > 1 and self.count > 1):
                await asyncio.Future()
            sequence = 101 if self.count == 1 else 103
            if self.number > 1:
                sequence = 201
            return json.dumps(
                {
                    "stream": "btcusd@depth@100ms",
                    "data": event(sequence, sequence, int(time.time() * 1000)),
                }
            )

    monkeypatch.setattr("trading.stream_feed.connect", lambda *args, **kwargs: Socket())

    async def scenario():
        venue = Venue()
        feed = StreamFeed(venue)
        try:
            await feed.configure({"BTCUSD": 100})
            deadline = time.monotonic() + 3
            witnessed_gap = False
            while time.monotonic() < deadline:
                stats = feed.stats.get("BTCUSD", {})
                if stats.get("reconnects", 0):
                    witnessed_gap |= "BTCUSD" not in feed.books
                if stats.get("books", 0) == 2:
                    break
                await asyncio.sleep(0.01)
            assert witnessed_gap and venue.calls == 2
            assert feed.fresh_books()["BTCUSD"]["book"].update_id == 201
            assert any(r["kind"] == "stream_gap" for r in feed.records)
            assert feed.fresh_books()["BTCUSD"]["exchange_event_ms"] > 0
        finally:
            await feed.close()
        assert not feed.books

    asyncio.run(scenario())
