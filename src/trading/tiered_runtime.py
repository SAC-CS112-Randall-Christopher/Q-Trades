"""Bounded discovery, push updates, explicit REST fallback and durable paper evidence."""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
from collections import deque
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.engine_diagnostics import EngineWorkDiagnostics
from trading.futures_context import POLL_SECONDS, FuturesContext, FuturesPublicData
from trading.live_quotes import quote_snapshot
from trading.market import parse_book
from trading.paper_engine import SYMBOLS, PaperEngine, filters
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore
from trading.paper_strategy import VARIANTS, features, parse_bars
from trading.stream_capture import StreamCapture
from trading.stream_feed import StreamFeed
from trading.universe import POLICY, Universe
from trading.venue import FeedError, PublicVenue

logger = logging.getLogger(__name__)
FEED_MODEL = "paper-tiered-feed-ioc-v2"


class TieredPaperRuntime(PaperRuntime):
    def __init__(self, store: PaperStore, venue: PublicVenue, capture_path: Path):
        super().__init__(store, venue)
        self.capture_path = capture_path
        self.stream = StreamFeed(venue)
        self.stream._previous = {s: value[0] for s, value in self._previous_books.items()}
        self.universe = Universe()
        self.study: dict[str, Any] = {}
        self._studied: dict[str, int] = {}
        self._fallback: dict[str, dict[str, Any]] = {}
        self._fallback_at: dict[str, float] = {}
        self._rest_retry_at = 0.0
        self._bars_added = 0
        self._notice_queue: list[dict[str, Any]] = []
        self._last_sources: dict[str, str] = {}
        self._last_commit = 0.0
        self._last_study_key = ""
        self._last_status_key = ""
        self._next_research_scan = 0.0
        self._constrained_until = 0.0
        self._loop_ms: deque[float] = deque(maxlen=1000)
        self._commit_ms: deque[float] = deque(maxlen=1000)
        self._work_diagnostics = EngineWorkDiagnostics()
        self._captured_bytes = 0
        self._started_mono = time.monotonic()
        self._started_cpu = time.process_time()
        self.capture_status: dict[str, Any] = {}
        self.disk_free = shutil.disk_usage(capture_path.parent).free
        self._capture_failure: str | None = None
        self._capture_discarded = 0
        self._market_minutes: dict[str, dict[str, Any]] = {}
        self.database_usage: dict[str, int] = {}
        self.futures = FuturesContext(self.state.get("futures_context"))

    def held(self) -> set[str]:
        return {
            s
            for a in self.state["accounts"].values()
            for s in set(a["positions"]) | set(a["pending"])
        }

    def constrained(self) -> bool:
        return (
            time.monotonic() < self._constrained_until
            or self.disk_free < 5 * 1024**3
            or self._capture_failure is not None
        )

    def observe_engine_work(
        self, elapsed_ms: float, now_mono: float, details: dict[str, Any] | None = None
    ) -> None:
        self._loop_ms.append(elapsed_ms)
        recent = list(self._loop_ms)[-20:]
        # A single Windows disk/scheduling outlier is not sustained saturation.
        # Demote research after repeated slow work, or one severe one-second stall.
        repeated = len(recent) == 20 and sum(value > 100 for value in recent) >= 4
        if repeated or elapsed_ms >= 1000:
            self._constrained_until = now_mono + 300
        notice = self._work_diagnostics.record(
            {"at": time.time(), "elapsed_ms": elapsed_ms, **(details or {})},
            now_mono,
            repeated=repeated,
            severe=elapsed_ms >= 1000,
        )
        if notice is not None:
            self._notice_queue.append({"kind": "engine_resource_guard", "body": notice})

    def update_features(self, symbol: str, now: float) -> None:
        bars = self.history.get(symbol, [])
        stamp = bars[-1].open_ms if bars else -1
        if self._studied.get(symbol) == stamp:
            return
        self._studied[symbol] = stamp
        result = {v: features(bars, now, v) for v in VARIANTS}
        for feature in result.values():
            if feature.get("bar_open_ms", 0) + 60000 < self.ready_at * 1000:
                feature.update(eligible=False, reason="Bootstrap only; awaiting new closed bar")
        self.study[symbol] = result
        self.stream.changed.set()

    def closed_stream_candle(self, symbol: str, observation: dict[str, Any]) -> None:
        candle = observation["raw"]["k"]
        raw = [[candle[k] for k in ("t", "o", "h", "l", "c", "v", "T", "q", "n", "V", "Q")] + ["0"]]
        now = observation["observed"]
        # The stream validated E against the synchronized exchange clock. Preserve
        # local receipt time separately: a slightly slow local clock must not drop
        # an exchange-confirmed closed bar from permanent storage.
        exchange_ms = observation["raw"]["E"]
        bars = parse_bars(raw, exchange_ms / 1000)
        merged = {b.open_ms: b for b in self.history.get(symbol, [])}
        for bar in bars:
            if bar.open_ms in merged and merged[bar.open_ms] != bar:
                raise ValueError("Stream disagrees with a retained closed candle")
            merged[bar.open_ms] = bar
        self._bars_added += self.store.bars(symbol, raw, now, False, closed_before_ms=exchange_ms)
        self.history[symbol] = sorted(merged.values(), key=lambda b: b.open_ms)[-600:]
        self.update_features(symbol, now)

    async def _references(self) -> None:
        while True:
            now = time.time()
            if now >= self._rest_retry_at:
                try:
                    if now >= self._next_research_scan:
                        if now - self.universe.metadata_at >= 900:
                            self.universe.metadata(await self.venue.universe(), time.time())
                        before = self.universe.selected[:]
                        ticks = await self.venue.tickers()
                        self.universe.screen(ticks, time.time(), self.held())
                        self.instruments = self.universe.instruments
                        self.metadata_at = self.universe.metadata_at
                        self.stream.record(
                            "universe_scan",
                            {
                                "policy": POLICY,
                                "selected": self.universe.selected,
                                "raw": ticks,
                                "rows": self.universe.rows,
                            },
                        )
                        self._notice_queue.append(
                            {
                                "kind": "universe_scan",
                                "body": {
                                    "policy": POLICY,
                                    "selected": self.universe.selected,
                                    "previous": before,
                                    "rows": self.universe.rows,
                                    "observed_at": self.universe.scanned_at,
                                },
                            }
                        )
                        self._next_research_scan = time.time() + 60
                        self.feed_errors.pop("discovery", None)
                    selected = set(SYMBOLS) | set(self.universe.selected) | self.held()
                    for symbol in sorted(selected):
                        observed = self.stream.candles.pop(symbol, None)
                        if observed and symbol in self.history:
                            self.closed_stream_candle(symbol, observed)
                            self._candle_errors.pop(symbol, None)
                        # Bootstrap/backfill only. Live closed candles arrive on the push feed.
                        bars = self.history.get(symbol, [])
                        if not bars or now * 1000 - bars[-1].close_ms > 75000:
                            try:
                                self._bars_added += await self.collect_candles(symbol)
                                self._candle_errors.pop(symbol, None)
                            except (ValueError, KeyError, ArithmeticError) as exc:
                                self._candle_errors[symbol] = str(exc)
                        self.update_features(symbol, time.time())
                    for symbol in set(self.history) - selected:
                        self.history.pop(symbol, None)
                        self.study.pop(symbol, None)
                        self._studied.pop(symbol, None)
                    plan = self.universe.plan(
                        self.study, self.held(), constrained=self.constrained()
                    )
                    if plan != self.stream.plan:
                        self._notice_queue.append(
                            {
                                "kind": "feed_tiers",
                                "body": {
                                    "previous": dict(self.stream.plan),
                                    "selected": plan,
                                    "constrained": self.constrained(),
                                },
                            }
                        )
                        await self.stream.configure(plan)
                except FeedError as exc:
                    self.feed_errors["discovery"] = exc.reason
                    self._rest_retry_at = time.time() + max(10, exc.retry_after)
                except (ValueError, KeyError, ArithmeticError) as exc:
                    self.feed_errors["discovery"] = str(exc)
                    self._rest_retry_at = time.time() + 30
            await asyncio.sleep(0.25)

    async def _rest_book(self, symbol: str) -> None:
        try:
            sent, mono = time.time(), time.monotonic()
            raw = await self.venue.depth(symbol, 20)
            now, arrived = time.time(), time.monotonic()
            if arrived - mono > 1:
                raise ValueError("REST fallback round trip exceeded one second")
            book = parse_book(raw, 20)
            digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
            previous = self._previous_books.get(symbol)
            if previous and (
                book.update_id < previous[0]
                or (book.update_id == previous[0] and digest != previous[1])
            ):
                raise ValueError("REST sequence regressed or changed without a new sequence")
            self._previous_books[symbol] = [book.update_id, digest]
            self._fallback[symbol] = {
                "book": book,
                "raw": raw,
                "observed": now,
                "received_mono": arrived,
                "request_sent_at": sent,
                "round_trip_ms": (arrived - mono) * 1000,
                "exchange_event_ms": None,
                "source": "binance.us-rest-fallback",
            }
            self.stream.record(
                "rest_depth",
                {
                    "symbol": symbol,
                    "raw": raw,
                    "request_sent_at": sent,
                    "round_trip_ms": (arrived - mono) * 1000,
                    "exchange_event_ms": None,
                },
                now,
            )
            self.feed_errors.pop(symbol, None)
            self.stream.changed.set()
        except FeedError as exc:
            self.feed_errors[symbol] = exc.reason
            self._rest_retry_at = time.time() + max(5, exc.retry_after)
        except (ValueError, KeyError, ArithmeticError) as exc:
            self.feed_errors[symbol] = str(exc)
        finally:
            # REST is capped: no attempt to imitate a 100ms stream with HTTP bursts.
            interval = 0.5 if self.stream.plan.get(symbol) == 100 else 5.0
            self._fallback_at[symbol] = time.monotonic() + interval

    async def _fallback_loop(self) -> None:
        while True:
            fresh = self.stream.fresh_books()
            if time.time() >= self._rest_retry_at:
                due = [
                    symbol
                    for symbol in self.stream.plan
                    if symbol not in fresh and time.monotonic() >= self._fallback_at.get(symbol, 0)
                ]
                if due:
                    await asyncio.gather(*(self._rest_book(symbol) for symbol in due))
            await asyncio.sleep(0.05)

    def quotes(self) -> dict[str, Any]:
        return quote_snapshot(
            self.stream, self._fallback, self._previous_books, self.running, self.error
        )

    def current_frames(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        now, mono = time.time(), time.monotonic()
        books = self.stream.fresh_books()
        for symbol, frame in self._fallback.items():
            if (
                symbol not in books
                and symbol in self.stream.plan
                and mono - frame["received_mono"] <= 1
            ):
                books[symbol] = frame
        frames = {}
        study = {}
        for symbol, observed in books.items():
            if observed["source"] == "binance.us-depth-websocket":
                previous = self._previous_books.get(symbol)
                if previous and observed["book"].update_id < previous[0]:
                    continue
                digest = hashlib.sha256(
                    json.dumps(observed["raw"], sort_keys=True).encode()
                ).hexdigest()
                self._previous_books[symbol] = [observed["book"].update_id, digest]
                self.feed_errors.pop(symbol, None)
            instrument = self.instruments.get(symbol)
            if instrument is None:
                continue
            try:
                rules = filters(instrument)
            except (ValueError, KeyError, ArithmeticError):
                continue
            frame = {
                **observed,
                "rules": rules,
                "instrument": instrument,
                "base": instrument["base"],
                "entry_allowed": now - self.metadata_at <= 900 and self.stream.plan[symbol] == 100,
            }
            frames[symbol] = frame
            study[symbol] = {v: dict(f) for v, f in self.study.get(symbol, {}).items()}
            for feature in study[symbol].values():
                if now * 1000 - feature.get("bar_open_ms", 0) - 59999 > 90000:
                    feature.update(eligible=False, reason="Closed candle is stale")
                if symbol in self._candle_errors:
                    feature.update(eligible=False, reason=self._candle_errors[symbol])
        return frames, study

    def summarize_books(self, frames: dict[str, dict[str, Any]], now: float) -> None:
        minute = int(now // 60)
        for symbol, summary in list(self._market_minutes.items()):
            if summary["minute"] != minute:
                summary["mean_spread_bps"] = str(
                    Decimal(summary.pop("spread_sum")) / summary["samples"]
                )
                self._notice_queue.append({"kind": "market_minute", "body": summary})
                del self._market_minutes[symbol]
        for symbol, frame in frames.items():
            metrics = frame["book"].metrics()
            spread = Decimal(metrics["spread_bps"])
            summary = self._market_minutes.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "minute": minute,
                    "samples": 0,
                    "last_sequence": -1,
                    "spread_sum": "0",
                    "min_spread_bps": str(spread),
                    "max_spread_bps": str(spread),
                    "first_observed_at": frame["observed"],
                    "sources": [],
                    "note": "Observed samples only; not a complete exchange replay",
                },
            )
            if frame["book"].update_id <= summary["last_sequence"]:
                continue
            summary["samples"] += 1
            summary["last_sequence"] = frame["book"].update_id
            summary["last_observed_at"] = frame["observed"]
            summary["spread_sum"] = str(Decimal(summary["spread_sum"]) + spread)
            summary["min_spread_bps"] = str(min(Decimal(summary["min_spread_bps"]), spread))
            summary["max_spread_bps"] = str(max(Decimal(summary["max_spread_bps"]), spread))
            summary["last_depth"] = metrics
            if frame["source"] not in summary["sources"]:
                summary["sources"].append(frame["source"])

    async def _capture_loop(self) -> None:
        capture = StreamCapture(self.capture_path)
        try:
            while True:
                self.disk_free = shutil.disk_usage(self.capture_path.parent).free
                records: list[dict[str, Any]] = []
                while self.stream.records and len(records) < 1000:
                    records.append(self.stream.records.popleft())
                self._captured_bytes += sum(len(json.dumps(r).encode()) for r in records)
                if self.disk_free < 5 * 1024**3:
                    self._capture_failure = "Raw capture paused: less than 5 GiB disk space"
                    self._capture_discarded += len(records)
                else:
                    try:
                        work = asyncio.create_task(asyncio.to_thread(capture.append, records))
                        try:
                            self.capture_status = await asyncio.shield(work)
                        except asyncio.CancelledError:
                            await work
                            raise
                        self._capture_failure = None
                    except Exception:
                        self._capture_discarded += len(records)
                        self._capture_failure = (
                            "Raw capture unavailable; candidate expansion paused"
                        )
                await asyncio.sleep(1)
        finally:
            capture.close()

    async def _futures_loop(self) -> None:
        client = FuturesPublicData()
        try:
            while True:
                targets = {
                    symbol: self.instruments.get(symbol, {}).get("base", symbol[:-3])
                    for symbol in dict.fromkeys((*SYMBOLS, *self.stream.plan))
                }
                try:
                    report = await self.futures.collect(client, targets)
                    if self.futures.metadata_wire:
                        self.stream.record(
                            "futures_metadata",
                            {"source": "Kraken public", "wire": self.futures.metadata_wire},
                        )
                    self._notice_queue.append({"kind": "futures_context", "body": report})
                except Exception as exc:
                    # Optional research failures cannot stop spot exits/accounting.
                    reason = "Futures context worker error: " + type(exc).__name__
                    self.futures.last_failure = reason
                    self.futures.markets = {
                        s: {"status": "unavailable", "reason": reason} for s in targets
                    }
                    self._notice_queue.append(
                        {"kind": "futures_context_error", "body": {"reason": reason}}
                    )
                self.stream.changed.set()
                await asyncio.sleep(POLL_SECONDS)
        finally:
            await client.close()

    async def run(self) -> None:
        self.running = True
        await self.stream.configure(dict.fromkeys(SYMBOLS, 100))
        tasks = [
            asyncio.create_task(self._references()),
            asyncio.create_task(self._fallback_loop()),
            asyncio.create_task(self._capture_loop()),
            asyncio.create_task(self._futures_loop()),
        ]
        try:
            while True:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.stream.changed.wait(), 0.25)
                self.stream.changed.clear()
                started = time.monotonic()
                measured_start, cpu_start = time.perf_counter(), time.thread_time()
                stage_ms: dict[str, float] = {}
                for task in tasks:
                    if task.done():
                        task.result()
                        raise RuntimeError("Market maintenance worker stopped")
                frames, study = self.current_frames()
                now = time.time()
                for symbol, frame in frames.items():
                    frame["futures_context"] = self.futures.context_for(
                        symbol, now, time.monotonic()
                    )
                self.summarize_books(frames, now)
                sources = {s: f["source"] for s, f in frames.items()}
                current_error = {**self.feed_errors, **self._candle_errors}
                missing = sorted((set(SYMBOLS) | self.held()) - set(frames))
                if missing:
                    current_error["missing_books"] = ", ".join(missing)
                status_key = json.dumps(
                    {"errors": current_error, "sources": sources}, sort_keys=True
                )
                study_key = json.dumps(study, sort_keys=True)
                active = any(
                    a["positions"] or a["pending"] for a in self.state["accounts"].values()
                )
                # Flat portfolios cannot react to a bar that hasn't changed. Avoid idle WAL churn.
                if (
                    not active
                    and now - self._last_commit < 1
                    and study_key == self._last_study_key
                    and status_key == self._last_status_key
                    and not self._notice_queue
                ):
                    continue
                added, notices = self._bars_added, self._notice_queue
                self._bars_added, self._notice_queue = 0, []

                def apply(
                    engine: PaperEngine,
                    status_key: str = status_key,
                    current_error: dict[str, str] = current_error,
                    sources: dict[str, str] = sources,
                    notices: list[dict[str, Any]] = notices,
                    added: int = added,
                    frames: dict[str, dict[str, Any]] = frames,
                    study: dict[str, Any] = study,
                ) -> None:
                    if engine.state["model"] != FEED_MODEL:
                        previous = engine.state["model"]
                        for name, a in engine.state["accounts"].items():
                            for symbol, order in list(a["pending"].items()):
                                order.setdefault("model", previous)
                                if order["side"] == "buy":
                                    engine.cancel(
                                        name, a, symbol, "Feed model upgraded; re-evaluate"
                                    )
                        engine.state["model"] = FEED_MODEL
                        engine.emit(
                            "feed_model_changed",
                            "primary",
                            {
                                "previous": previous,
                                "selected": FEED_MODEL,
                                "note": "Risk, fees and one-second fill delay unchanged",
                            },
                        )
                    if status_key != self._last_status_key:
                        engine.emit(
                            "feed_status", "system", {"errors": current_error, "sources": sources}
                        )
                    for notice in notices:
                        if notice["kind"] == "futures_context":
                            engine.record_futures_context(notice["body"])
                        else:
                            engine.emit(notice["kind"], "system", notice["body"])
                    engine.universe_experiment(list(self.stream.plan))
                    engine.state["study_bars"] += added
                    engine.state["book_sequences"] = self._previous_books
                    engine.tick(frames, study)

                commit_started = time.monotonic()
                measured_commit = time.perf_counter()
                stage_ms["prepare"] = (measured_commit - measured_start) * 1000
                self.state = self.store.transact(now, apply)
                self._commit_ms.append((time.monotonic() - commit_started) * 1000)
                stage_ms["transaction"] = (time.perf_counter() - measured_commit) * 1000
                self._last_commit, self._last_study_key = now, study_key
                self._last_status_key, self._last_sources = status_key, sources
                self.error = None
                if now - self._last_audit >= 60:
                    stage_started = time.perf_counter()
                    self.receipts = self.store.reconcile()
                    stage_ms["reconcile"] = (time.perf_counter() - stage_started) * 1000
                    stage_started = time.perf_counter()
                    self.database_usage = self.store.storage_usage()
                    stage_ms["storage_usage"] = (time.perf_counter() - stage_started) * 1000
                    self._last_audit = now
                    if not self.receipts["balanced"]:
                        raise RuntimeError("Paper journal reconciliation failed; engine stopped")
                if now - self._last_receipts >= 5:
                    stage_started = time.perf_counter()
                    self.recent = self.store.recent()
                    stage_ms["recent"] = (time.perf_counter() - stage_started) * 1000
                    self._last_receipts = now
                elapsed = (time.monotonic() - started) * 1000
                self.observe_engine_work(
                    elapsed,
                    time.monotonic(),
                    {
                        "measured_elapsed_ms": round(
                            (time.perf_counter() - measured_start) * 1000, 3
                        ),
                        "thread_cpu_ms": round((time.thread_time() - cpu_start) * 1000, 3),
                        "stages_ms": {name: round(value, 3) for name, value in stage_ms.items()},
                        "active_portfolios": active,
                        "frames": len(frames),
                        "notices": len(notices),
                        "bars_added": added,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = (
                "Paper engine stopped after a storage or invariant error; inspect local logs"
            )
            logger.exception("Tiered paper engine stopped")
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task
            await self.stream.close()
            self.running = False

    def snapshot(self) -> dict[str, Any]:
        result = super().snapshot()
        elapsed = max(1, time.monotonic() - self._started_mono)
        rate = self._captured_bytes / elapsed
        frames, _ = self.current_frames()
        feed = self.stream.snapshot()
        for symbol, row in feed["markets"].items():
            frame = frames.get(symbol)
            row["source"] = frame["source"] if frame else "unavailable"
            row["usable"] = frame is not None
            row["round_trip_ms"] = round(frame.get("round_trip_ms", 0), 2) if frame else None
            row["received_age_ms"] = (
                round((time.monotonic() - frame["received_mono"]) * 1000, 2) if frame else None
            )
        result.update(
            {
                "feed": feed,
                "futures_context": self.futures.snapshot(),
                "universe": self.universe.snapshot(),
                "sampling": "100ms fast / 1s watch WebSocket target; explicit capped REST fallback",
                "research_constrained": self.constrained(),
                "performance": {
                    "average_cpu_percent_of_machine": round(
                        (time.process_time() - self._started_cpu)
                        / elapsed
                        / (os.cpu_count() or 1)
                        * 100,
                        2,
                    ),
                    "engine_p95_ms": self._percentile(self._loop_ms),
                    "commit_p95_ms": self._percentile(self._commit_ms),
                    "resource_guard": self._work_diagnostics.snapshot(
                        time.monotonic(), self._constrained_until
                    ),
                },
                "storage": {
                    **self.capture_status,
                    "raw_bytes_per_second": round(rate, 2),
                    "projected_uncapped_raw_gib_per_day": round(rate * 86400 / 1024**3, 3),
                    "disk_free_gib": round(self.disk_free / 1024**3, 2),
                    "capture_error": self._capture_failure,
                    "capture_discarded": self._capture_discarded,
                    "postgres": self.database_usage,
                    "raw_retention": "20,000 records / 64 MiB payload cap; older raw data pruned",
                    "permanent_retention": "Trades, decisions, reviews and candles retained",
                    "database": "Dedicated local PostgreSQL; raw capture in separate local SQLite",
                },
            }
        )
        result["feed_errors"].update(
            {
                "book " + s: "No fresh executable book"
                for s in set(SYMBOLS) | self.held()
                if s not in frames
            }
        )
        return result

    @staticmethod
    def _percentile(values: deque[float]) -> float | None:
        ordered = sorted(values)
        return (
            round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2) if ordered else None
        )
