"""One continuous public collector, independent of any browser or LLM."""

import asyncio
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from trading.config import Settings
from trading.market import InvalidMarketData, parse_book, parse_instruments
from trading.storage import MonitorStore
from trading.venue import FeedError, PublicVenue


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Monitor:
    def __init__(self, settings: Settings, store: MonitorStore, venue: PublicVenue):
        self.settings = settings
        self.store = store
        self.venue = venue
        self.paused: bool = store.get("paused", False)
        self.wake = asyncio.Event()
        self.last_received: dict[str, float] = {}
        self.errors: dict[str, str] = {}
        stored_metadata = store.get("metadata")
        self.metadata: dict[str, dict[str, Any]] = (
            parse_instruments(stored_metadata["payload"], settings.monitored_symbols)
            if stored_metadata
            else {}
        )
        self.metadata_received: float | None = None
        self.metadata_error: str | None = None
        self.storage_error: str | None = None
        self.runtime_error: str | None = None
        self.cooldown = 0.0
        retry_until = store.get("retry_not_before")
        if retry_until:
            remaining = (datetime.fromisoformat(retry_until) - datetime.now(UTC)).total_seconds()
            self.cooldown = time.monotonic() + max(remaining, 0)
        self.failures = 0

    def set_paused(self, paused: bool) -> None:
        self.store.event(
            now_iso(),
            "Collection paused by operator" if paused else "Collection resumed by operator",
            paused=paused,
        )
        self.paused = paused
        self.wake.set()

    def _failure(self, key: str, reason: str) -> None:
        if self.errors.get(key) != reason:
            self.store.event(now_iso(), f"{key}: {reason}")
        self.errors[key] = reason

    def _recovered(self, key: str) -> None:
        if key in self.errors:
            self.store.event(now_iso(), f"{key}: public observations recovered")
            del self.errors[key]

    def _cool_down(self, delay: float) -> None:
        self.cooldown = max(self.cooldown, time.monotonic() + delay)
        self.store.set(
            "retry_not_before", (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
        )

    async def poll_once(self) -> None:
        if self.paused or time.monotonic() < self.cooldown or not self.settings.monitored_symbols:
            return
        metadata_due = (
            self.metadata_received is None
            or time.monotonic() - self.metadata_received >= self.settings.metadata_refresh_seconds
        )
        if metadata_due:
            try:
                payload = await self.venue.instruments(self.settings.monitored_symbols)
                parsed = parse_instruments(payload, self.settings.monitored_symbols)
                self.store.record(
                    "instruments", None, now_iso(), payload, self.settings.fingerprint, "metadata"
                )
                self.metadata = parsed
                self.metadata_received = time.monotonic()
                self.metadata_error = None
                self._recovered("Metadata")
            except (FeedError, InvalidMarketData) as exc:
                self.metadata_error = str(exc)
                self._failure("Metadata", str(exc))
                if isinstance(exc, FeedError) and exc.retry_after:
                    self._cool_down(exc.retry_after)
                else:
                    self._cool_down(60)
                return
        failures = 0
        for symbol in self.settings.monitored_symbols:
            if self.paused:
                break
            if symbol not in self.metadata:
                self._failure(symbol, "Symbol is absent from current venue metadata")
                failures += 1
                continue
            started = time.monotonic()
            try:
                payload = await self.venue.depth(symbol, self.settings.depth_levels)
                received = now_iso()
                # Preserve the raw response even when normalization rejects it.
                self.store.record("depth", symbol, received, payload, self.settings.fingerprint)
                book = parse_book(payload, self.settings.depth_levels)
                previous = self.store.get("book:" + symbol)
                if previous:
                    prior = parse_book(previous["payload"])
                    if book.update_id < prior.update_id:
                        raise InvalidMarketData(
                            "Book sequence moved backward; observation rejected"
                        )
                    if book.update_id == prior.update_id and book != prior:
                        raise InvalidMarketData(
                            "Book changed without a new sequence; observation rejected"
                        )
                if (
                    symbol in self.last_received
                    and started - self.last_received[symbol] > self.settings.stale_after_seconds
                ):
                    self.store.event(
                        received, f"{symbol}: collection gap; no intervening data inferred"
                    )
                self.store.set(
                    "book:" + symbol,
                    {
                        "observed_at": received,
                        "payload": payload,
                        "request_ms": round((time.monotonic() - started) * 1000),
                    },
                )
                self.last_received[symbol] = time.monotonic()
                self._recovered(symbol)
            except (FeedError, InvalidMarketData) as exc:
                failures += 1
                self._failure(symbol, str(exc))
                if isinstance(exc, FeedError) and exc.retry_after:
                    self._cool_down(exc.retry_after)
                    break
        self.failures = self.failures + 1 if failures else 0
        if failures and self.cooldown <= time.monotonic():
            self._cool_down(min(300, self.settings.poll_seconds * 2 ** min(self.failures, 5)))

    async def run(self) -> None:
        try:
            await self._run()
        except Exception:
            logging.exception("Public collector stopped unexpectedly")
            self.runtime_error = "Collector stopped unexpectedly. Restart the local service."

    async def _run(self) -> None:
        self.store.event(
            now_iso(), "Collector started; previous observations require fresh confirmation"
        )
        while True:
            self.wake.clear()
            try:
                attempted = not self.paused and time.monotonic() >= self.cooldown
                await self.poll_once()
                if attempted:
                    self.storage_error = None
            except sqlite3.Error:
                self.storage_error = (
                    "Observation storage failed; collection is suspended until storage recovers"
                )
                self.cooldown = time.monotonic() + 60
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=self.settings.poll_seconds)
            except TimeoutError:
                pass

    def snapshot(self) -> dict[str, Any]:
        markets = []
        mono = time.monotonic()
        for symbol in self.settings.monitored_symbols:
            stored = self.store.get("book:" + symbol)
            instrument = self.metadata.get(symbol)
            meta_ok = (
                self.metadata_received is not None
                and not self.metadata_error
                and mono - self.metadata_received <= self.settings.metadata_refresh_seconds * 2
            )
            age = mono - self.last_received[symbol] if symbol in self.last_received else None
            reasons = []
            if symbol in self.errors:
                reasons.append(self.errors[symbol])
            if not meta_ok or not instrument:
                reasons.append("Current instrument metadata is not confirmed")
            elif instrument["venue_status"] != "TRADING" or not instrument["spot_allowed"]:
                reasons.append("Venue does not currently report this market as spot tradable")
            if age is None:
                reasons.append("Waiting for a valid observation in this session")
            elif age > self.settings.stale_after_seconds:
                reasons.append("Public response is stale")
            if self.storage_error:
                reasons.append(self.storage_error)
            if self.runtime_error:
                reasons.append(self.runtime_error)
            state = "observed" if not reasons else "stale" if stored else "unavailable"
            book = parse_book(stored["payload"]) if stored else None
            markets.append(
                {
                    "symbol": symbol,
                    "instrument": instrument,
                    "state": state,
                    "reasons": reasons,
                    "response_age_seconds": round(age, 1) if age is not None else None,
                    "observed_at": stored["observed_at"] if stored else None,
                    "request_ms": stored.get("request_ms") if stored else None,
                    "metrics": book.metrics() if book else None,
                    "book": stored["payload"] if stored else None,
                    "entry_allowed": False,
                    "entry_reason": "Market monitor only; paper execution is not implemented",
                }
            )
        observed = sum(m["state"] == "observed" for m in markets)
        state = (
            "stopped"
            if self.runtime_error
            else "paused"
            if self.paused
            else "idle"
            if not markets
            else "monitoring"
            if observed == len(markets)
            else "degraded"
            if self.errors or any(m["book"] for m in markets)
            else "warming_up"
        )
        return {
            "mode": "paper",
            "checkpoint": "CP0 / CP1 — public market monitor",
            "runtime_state": state,
            "paused": self.paused,
            "generated_at": now_iso(),
            "poll_seconds": self.settings.poll_seconds,
            "stale_after_seconds": self.settings.stale_after_seconds,
            "retry_in_seconds": max(0, round(self.cooldown - mono)),
            "storage_error": self.storage_error or self.runtime_error,
            "ai": {"enabled": False, "daily_budget_usd": "0.00"},
            "execution": {
                "paper_available": False,
                "live_available": False,
                "approved_symbols": [],
            },
            "markets": markets,
            "capture": self.store.observation_stats(),
            "events": self.store.events(),
            "events_total": self.store.get("events_total", 0),
            "config_hash": self.settings.fingerprint,
        }
