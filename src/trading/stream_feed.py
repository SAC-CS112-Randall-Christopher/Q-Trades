"""Public push feed: bounded subscriptions, timestamp checks and fresh-book recovery."""

import asyncio
import json
import math
import time
from collections import deque
from contextlib import suppress
from typing import Any

from websockets.asyncio.client import connect

from trading.market import decimal_string
from trading.stream_book import DepthBook, StreamGap, book_payload
from trading.venue import FeedError, PublicVenue

STREAM_ORIGIN = "wss://stream.binance.us:9443"
MAX_EVENT_AGE_MS = 1000


class ExchangeClock:
    def __init__(self) -> None:
        self.offset_ms = 0.0
        self.uncertainty_ms = math.inf
        self.checked_mono = 0.0
        self.wall_minus_mono = 0.0

    async def sync(self, venue: PublicVenue) -> None:
        before, wall = time.monotonic(), time.time()
        raw = await venue.server_time()
        after = time.monotonic()
        stamp = raw.get("serverTime")
        if type(stamp) is not int or after - before > 2:
            raise FeedError("Exchange clock sample is invalid or too slow")
        if abs((time.time() - wall) - (after - before)) > 0.1:
            raise FeedError("Local wall clock changed during time synchronization")
        self.offset_ms = stamp - (wall + (after - before) / 2) * 1000
        self.uncertainty_ms = (after - before) * 500
        self.checked_mono = after
        self.wall_minus_mono = time.time() - after

    def valid(self, wall: float, mono: float) -> bool:
        return (
            self.checked_mono > 0
            and mono - self.checked_mono <= 180
            and abs(wall - mono - self.wall_minus_mono) <= 0.1
        )

    def age(self, stamp: Any, wall: float, mono: float) -> float:
        if type(stamp) is not int or stamp <= 0 or not self.valid(wall, mono):
            raise StreamGap("Exchange clock unavailable or local clock changed")
        age = wall * 1000 + self.offset_ms - stamp
        if age < -self.uncertainty_ms - 100 or age + self.uncertainty_ms > MAX_EVENT_AGE_MS:
            raise StreamGap("Exchange update is delayed or has a future timestamp")
        return age


class StreamFeed:
    def __init__(self, venue: PublicVenue):
        self.venue = venue
        self.clock = ExchangeClock()
        self.plan: dict[str, int] = {}
        self.books: dict[str, dict[str, Any]] = {}
        self.candles: dict[str, dict[str, Any]] = {}
        self.trade_tape: dict[str, deque[dict[str, Any]]] = {}
        self.errors: dict[str, str] = {}
        self.stats: dict[str, dict[str, Any]] = {}
        self.changed = asyncio.Event()
        self.records: deque[dict[str, Any]] = deque()
        self.dropped_capture = 0
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._clock_task: asyncio.Task[None] | None = None
        self._previous: dict[str, int] = {}
        self._trade_ids: dict[str, int] = {}

    def record(self, kind: str, body: dict[str, Any], received: float | None = None) -> None:
        if len(self.records) >= 2000:
            self.records.popleft()
            self.dropped_capture += 1
        self.records.append({"kind": kind, "received_at": received or time.time(), **body})

    async def _clock_loop(self) -> None:
        while True:
            try:
                await self.clock.sync(self.venue)
                self.errors.pop("clock", None)
            except FeedError as exc:
                self.errors["clock"] = exc.reason
            self.changed.set()
            await asyncio.sleep(60)

    async def configure(self, plan: dict[str, int]) -> None:
        if len(plan) > 8 or any(
            not s.isascii()
            or not s.isalnum()
            or not s.endswith("USD")
            or len(s) > 24
            or interval not in (100, 1000)
            for s, interval in plan.items()
        ):
            raise ValueError("Invalid or oversized public stream plan")
        if self._clock_task is None:
            self._clock_task = asyncio.create_task(self._clock_loop())
        for symbol in list(self._workers):
            if plan.get(symbol) != self.plan.get(symbol):
                task = self._workers.pop(symbol)
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                self.books.pop(symbol, None)
                self.trade_tape.pop(symbol, None)
                self.errors.pop(symbol, None)
        old = self.plan
        self.plan = dict(plan)
        for symbol, interval in plan.items():
            if symbol not in self._workers:
                self.record(
                    "subscription",
                    {
                        "symbol": symbol,
                        "interval_ms": interval,
                        "previous_interval_ms": old.get(symbol),
                    },
                )
                self._workers[symbol] = asyncio.create_task(self._symbol_loop(symbol, interval))
        self.changed.set()

    async def close(self) -> None:
        tasks = list(self._workers.values()) + ([self._clock_task] if self._clock_task else [])
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self.books.clear()

    def publish(
        self, symbol: str, local: DepthBook, event: dict[str, Any], wall: float, mono: float
    ) -> None:
        book = local.apply(event)
        if book is None:
            return
        previous = self._previous.get(symbol, -1)
        if book.update_id <= previous:
            raise StreamGap("Depth sequence did not advance across reconnection")
        self._previous[symbol] = book.update_id
        age = self.clock.age(event["E"], wall, mono)
        elapsed = (time.monotonic() - mono) * 1000
        if age + self.clock.uncertainty_ms + elapsed > MAX_EVENT_AGE_MS:
            raise StreamGap("Buffered depth is too old to use")
        self.books[symbol] = {
            "book": book,
            "raw": book_payload(book),
            "observed": wall,
            "received_mono": mono,
            "exchange_event_ms": event["E"],
            "event_age_ms": age,
            "clock_uncertainty_ms": self.clock.uncertainty_ms,
            "raw_update": event,
            "source": "binance.us-depth-websocket",
        }
        stat = self.stats[symbol]
        previous_mono = stat.get("last_book_mono")
        if previous_mono is not None:
            stat["intervals_ms"].append((mono - previous_mono) * 1000)
        stat["last_book_mono"] = mono
        stat["books"] += 1
        stat["ages_ms"].append(age)
        self.errors.pop(symbol, None)
        self.changed.set()

    def accept_aux(self, symbol: str, raw: dict[str, Any], wall: float, mono: float) -> None:
        if raw.get("e") == "trade":
            trade_id = raw.get("t")
            if type(trade_id) is not int or type(raw.get("T")) is not int:
                raise StreamGap("Invalid trade identity or timestamp")
            decimal_string(raw.get("p"))
            decimal_string(raw.get("q"))
            previous = self._trade_ids.get(symbol)
            if previous is not None and trade_id <= previous:
                return
            if previous is not None and trade_id != previous + 1:
                self.stats[symbol]["trade_gaps"] += 1
                self.record("trade_gap", {"symbol": symbol, "previous": previous, "next": trade_id})
            self._trade_ids[symbol] = trade_id
            self.stats[symbol]["trades"] += 1
            self.trade_tape.setdefault(symbol, deque(maxlen=40)).append(
                {
                    "id": trade_id,
                    "price": raw["p"],
                    "quantity": raw["q"],
                    "exchange_ms": raw["T"],
                    "received_at": wall,
                }
            )
        elif raw.get("e") == "kline":
            candle = raw.get("k", {})
            if candle.get("i") != "1m" or candle.get("s") != symbol:
                raise StreamGap("Unexpected candle identity or interval")
            if candle.get("x") is True:
                # Candle timestamps describe the interval; E describes message publication.
                self.clock.age(raw.get("E"), wall, mono)
                self.candles[symbol] = {"raw": raw, "observed": wall}
                self.changed.set()

    async def _symbol_loop(self, symbol: str, interval: int) -> None:
        depth = f"{symbol.lower()}@depth" + ("@100ms" if interval == 100 else "")
        streams = [depth, f"{symbol.lower()}@trade", f"{symbol.lower()}@kline_1m"]
        uri = STREAM_ORIGIN + "/stream?streams=" + "/".join(streams)
        stat = self.stats.setdefault(
            symbol,
            {
                "books": 0,
                "trades": 0,
                "reconnects": 0,
                "trade_gaps": 0,
                "intervals_ms": deque(maxlen=1000),
                "ages_ms": deque(maxlen=1000),
            },
        )
        delay = 1.0
        while True:
            bootstrap: asyncio.Task[dict[str, Any]] | None = None
            self.errors[symbol] = "Connecting and synchronizing depth"
            self.books.pop(symbol, None)
            self.changed.set()
            try:
                # Public subscriptions only. No credentials, order methods or redirects.
                async with connect(
                    uri,
                    proxy=None,
                    compression=None,
                    max_size=262_144,
                    max_queue=32,
                    open_timeout=8,
                    close_timeout=2,
                    ping_interval=20,
                    ping_timeout=10,
                ) as socket:
                    bootstrap = asyncio.create_task(self.venue.depth(symbol, 1000))
                    local = None
                    pending: list[tuple[dict[str, Any], float, float]] = []
                    opened = time.monotonic()
                    while True:
                        if time.monotonic() - opened > 23 * 3600 + 50 * 60:
                            raise StreamGap("Scheduled renewal before venue connection expiry")
                        message = await asyncio.wait_for(socket.recv(), timeout=15)
                        wall, mono = time.time(), time.monotonic()
                        envelope = json.loads(message)
                        if not isinstance(envelope, dict):
                            raise StreamGap("Malformed stream envelope")
                        raw = envelope.get("data", envelope)
                        if not isinstance(raw, dict) or raw.get("e") == "serverShutdown":
                            raise StreamGap("Exchange shutdown or malformed payload")
                        if envelope.get("stream") not in streams or raw.get("s") != symbol:
                            raise StreamGap("Unexpected stream identity")
                        self.record(
                            "message",
                            {
                                "stream": envelope["stream"],
                                "exchange_event_ms": raw.get("E"),
                                "trade_time_ms": raw.get("T"),
                                "received_mono": mono,
                                "raw": envelope,
                            },
                            wall,
                        )
                        if raw.get("e") != "depthUpdate":
                            self.accept_aux(symbol, raw, wall, mono)
                            continue
                        if local is None:
                            pending.append((raw, wall, mono))
                            if len(pending) > 200:
                                raise StreamGap("Depth bootstrap buffer exceeded capacity")
                            if not bootstrap.done():
                                continue
                            snapshot = bootstrap.result()
                            self.record("depth_snapshot", {"symbol": symbol, "raw": snapshot})
                            local = DepthBook(snapshot)
                            for event, received, arrival in pending:
                                self.publish(symbol, local, event, received, arrival)
                            pending.clear()
                        else:
                            self.publish(symbol, local, raw, wall, mono)
                        delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Do not let failed research feeds crash the independent risk/ledger loop.
                reason = str(exc) if isinstance(exc, (StreamGap, FeedError)) else type(exc).__name__
                self.errors[symbol] = "Stream unavailable: " + reason
                self.record("stream_gap", {"symbol": symbol, "reason": reason})
                stat["reconnects"] += 1
                if isinstance(exc, FeedError):
                    delay = max(delay, exc.retry_after)
            finally:
                self.books.pop(symbol, None)
                self.changed.set()
                if bootstrap is not None:
                    bootstrap.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await bootstrap
            await asyncio.sleep(delay)
            delay = min(60.0, delay * 2)

    def fresh_books(self) -> dict[str, dict[str, Any]]:
        now, mono = time.time(), time.monotonic()
        result: dict[str, dict[str, Any]] = {}
        if not self.clock.valid(now, mono):
            return result
        for symbol, frame in self.books.items():
            elapsed = (mono - frame["received_mono"]) * 1000
            # The slower observation tier can remain visible for two seconds, but may not fill.
            threshold = 1000 if self.plan[symbol] == 100 else 2500
            if frame["event_age_ms"] + frame["clock_uncertainty_ms"] + elapsed <= threshold:
                result[symbol] = frame
        return result

    def snapshot(self) -> dict[str, Any]:
        def percentile(values: Any, p: float) -> float | None:
            ordered = sorted(values)
            return (
                round(ordered[min(len(ordered) - 1, int(len(ordered) * p))], 2) if ordered else None
            )

        fresh = self.fresh_books()
        return {
            "transport": "Public WebSocket",
            "clock_offset_ms": round(self.clock.offset_ms, 2),
            "clock_uncertainty_ms": round(self.clock.uncertainty_ms, 2)
            if math.isfinite(self.clock.uncertainty_ms)
            else None,
            "capture_dropped": self.dropped_capture,
            "markets": {
                symbol: {
                    "interval_ms": interval,
                    "fresh": symbol in fresh,
                    "received_age_ms": round(
                        (time.monotonic() - self.books[symbol]["received_mono"]) * 1000, 2
                    )
                    if symbol in self.books
                    else None,
                    "exchange_event_ms": self.books.get(symbol, {}).get("exchange_event_ms"),
                    "books": self.stats.get(symbol, {}).get("books", 0),
                    "trades": self.stats.get(symbol, {}).get("trades", 0),
                    "reconnects": self.stats.get(symbol, {}).get("reconnects", 0),
                    "trade_gaps": self.stats.get(symbol, {}).get("trade_gaps", 0),
                    "interval_p50_ms": percentile(
                        self.stats.get(symbol, {}).get("intervals_ms", []), 0.5
                    ),
                    "event_age_p95_ms": percentile(
                        self.stats.get(symbol, {}).get("ages_ms", []), 0.95
                    ),
                    "error": self.errors.get(symbol),
                }
                for symbol, interval in self.plan.items()
            },
        }
