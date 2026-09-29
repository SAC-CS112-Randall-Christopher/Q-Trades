"""Public REST observer and persistent four-hour learner; no model API dependency."""

import asyncio
import hashlib
import json
import logging
import time
from decimal import Decimal
from typing import Any

import psycopg

from trading.execution_profiles import PROFILES, execution
from trading.market import parse_book, parse_instruments
from trading.numerical_candidates import signal
from trading.paper_campaigns import CampaignSpec, control_account, create_campaign
from trading.paper_challengers import admit
from trading.paper_economics import report as economics_report
from trading.paper_engine import SYMBOLS, PaperEngine, filters, fresh_frame, risk_summary
from trading.paper_store import PaperStore
from trading.paper_strategy import VARIANTS, Bar, features, parse_bars
from trading.venue import FeedError, PublicVenue

logger = logging.getLogger(__name__)


class PaperRuntime:
    def __init__(self, store: PaperStore, venue: PublicVenue):
        self.store = store
        self.venue = venue
        self.books: dict[str, dict[str, Any]] = {}
        self.history: dict[str, list[Bar]] = {}
        self.instruments: dict[str, dict[str, Any]] = {}
        self.metadata_at = 0.0
        self.candles_at: dict[str, float] = {}
        self.ready_at = time.time()
        self.error: str | None = None
        self.feed_errors: dict[str, str] = {}
        self.running = False
        self.retry_at = 0.0
        self.state = store.read()
        self.recent = store.recent()
        self.receipts: dict[str, Any] = {}
        self._last_audit = 0.0
        self._last_receipts = 0.0
        self._previous_books: dict[str, Any] = dict(self.state.get("book_sequences", {}))
        self._candle_errors: dict[str, str] = {}
        self._numerical_minute = -1
        self._numerical_rows: list[dict[str, Any]] = []

    def numerical_study(self, now: float, study: dict[str, Any]) -> None:
        candidates = [a for a in self.state["accounts"].values() if a.get("numerical_artifact")]
        if not candidates:
            return
        minute = int(now // 60)
        if minute != self._numerical_minute:
            try:
                self._numerical_rows = self.store.numerical_inputs(now)
            except psycopg.Error:
                self._numerical_rows = []  # Research input loss never invents a signal.
            self._numerical_minute = minute
        for a in candidates:
            try:
                feature = signal(
                    self._numerical_rows, now, a["numerical_artifact"], a["admitted_at"]
                )
            except (ValueError, KeyError, TypeError, ArithmeticError):
                feature = {"eligible": False,
                           "reason": "Frozen numerical input/model needs attention"}
            study.setdefault("BTCUSD", {})[a["version"]] = feature

    def forward_admit(self, experiment: str, artifact: dict[str, Any], cash: str,
                      daily: str | None) -> dict[str, Any]:
        self.require_healthy_control()
        result: dict[str, Any] = {}
        self.state = self.store.transact(time.time(), lambda e: result.update(
            admit(e, experiment, artifact, cash, daily)
        ))
        return result

    async def collect_candles(self, symbol: str) -> int:
        now = time.time()
        if now < self.candles_at.get(symbol, 0) + 15:
            return 0
        bootstrap = symbol not in self.history
        # A missed interval is refetched, but never traded retroactively.
        old = self.history.get(symbol, [])
        missing = int((now * 1000 - old[-1].open_ms) / 60000) + 2 if old else 600
        raw = await self.venue.candles(symbol, min(600, max(10, missing)))
        received = time.time()
        bars = parse_bars(raw, received)
        merged = {b.open_ms: b for b in old}
        for bar in bars:
            previous = merged.get(bar.open_ms)
            if previous and previous != bar:
                raise ValueError("Venue revised a closed candle; study paused for review")
            merged[bar.open_ms] = bar
        added = self.store.bars(symbol, raw, received, bootstrap)
        self.history[symbol] = sorted(merged.values(), key=lambda b: b.open_ms)[-600:]
        self.candles_at[symbol] = received
        return added

    async def collect(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any], int]:
        now = time.time()
        bars_added = 0
        if now >= self.metadata_at + 300:
            try:
                self.instruments = parse_instruments(
                    await self.venue.instruments(list(SYMBOLS)), list(SYMBOLS)
                )
                self.metadata_at = time.time()
                self.feed_errors.pop("metadata", None)
            except FeedError as exc:
                if exc.retry_after:
                    raise
                self.feed_errors["metadata"] = exc.reason
        for symbol in SYMBOLS:
            try:
                bars_added += await self.collect_candles(symbol)
                self._candle_errors.pop(symbol, None)
            except FeedError as exc:
                if exc.retry_after:
                    raise
                self._candle_errors[symbol] = exc.reason
            except (ValueError, KeyError, ArithmeticError) as exc:
                self._candle_errors[symbol] = str(exc)
        frames = {}
        study = {}
        for symbol in SYMBOLS:
            try:
                sent = time.time()
                raw_book = await self.venue.depth(symbol, 20)
                received = time.time()
                if received - sent > 3:
                    raise ValueError("Depth request took more than three seconds")
                book = parse_book(raw_book, 20)
                digest = hashlib.sha256(json.dumps(raw_book, sort_keys=True).encode()).hexdigest()
                previous = self._previous_books.get(symbol)
                if previous and (
                    book.update_id < previous[0]
                    or (book.update_id == previous[0] and digest != previous[1])
                ):
                    raise ValueError("Book sequence regressed or repeated with different content")
                self._previous_books[symbol] = [book.update_id, digest]
                instrument = self.instruments[symbol]
                frame = {
                    "book": book,
                    "observed": received,
                    "raw": raw_book,
                    "rules": filters(instrument),
                    "base": instrument["base"],
                    "instrument": instrument,
                    "entry_allowed": received - self.metadata_at <= 300,
                }
                frames[symbol] = frame
                self.books[symbol] = frame
                study[symbol] = {
                    v: features(self.history.get(symbol, []), received, v) for v in VARIANTS
                }
                # Startup history is for features, never a backlog of trade opportunities.
                for feature in study[symbol].values():
                    if feature.get("bar_open_ms", 0) + 60000 < self.ready_at * 1000:
                        feature.update(
                            eligible=False, reason="Bootstrap only; awaiting new closed bar"
                        )
                    if symbol in self._candle_errors:
                        feature.update(eligible=False, reason=self._candle_errors[symbol])
                self.feed_errors.pop(symbol, None)
            except FeedError as exc:
                if exc.retry_after:
                    raise
                self.feed_errors[symbol] = exc.reason
            except (ValueError, KeyError, ArithmeticError) as exc:
                self.feed_errors[symbol] = str(exc)
        return frames, study, bars_added

    async def run(self) -> None:
        self.running = True
        try:
            while True:
                frames: dict[str, dict[str, Any]] = {}
                study: dict[str, Any] = {}
                added = 0
                try:
                    if time.time() >= self.retry_at:
                        frames, study, added = await self.collect()
                        self.error = None
                except FeedError as exc:
                    self.error = exc.reason
                    self.retry_at = time.time() + max(5, exc.retry_after)
                except (ValueError, KeyError, ArithmeticError) as exc:
                    self.error = "Market data rejected: " + str(exc)
                    self.retry_at = time.time() + 15
                now = time.time()

                self.numerical_study(now, study)

                def apply(
                    engine: PaperEngine,
                    frames: dict[str, dict[str, Any]] = frames,
                    study: dict[str, Any] = study,
                    added: int = added,
                ) -> None:
                    old_error = engine.state.get("last_error")
                    current_error = self.error or (
                        str(self.feed_errors) if self.feed_errors else None
                    )
                    if current_error != old_error:
                        engine.emit("feed_status", "system", {"error": current_error})
                    engine.state["last_error"] = current_error
                    engine.state["study_bars"] += added
                    engine.state["book_sequences"] = self._previous_books
                    engine.tick(frames, study)

                self.state = self.store.transact(now, apply)
                if now - self._last_audit >= 60:
                    self.receipts = self.store.reconcile()
                    self._last_audit = now
                    if not self.receipts["balanced"]:
                        raise RuntimeError("Paper journal reconciliation failed; engine stopped")
                if now - self._last_receipts >= 5:
                    self.recent = self.store.recent()
                    self._last_receipts = now
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = (
                "Paper engine stopped after a storage or invariant error; inspect local logs"
            )
            logger.exception("Paper engine stopped")
        finally:
            self.running = False

    def snapshot(self) -> dict[str, Any]:
        primary = self.state["accounts"]["primary"]
        now = time.time()
        stale = now - self.state["last_tick"] > 10 or not self.running
        accounts = {}
        for name, a in self.state["accounts"].items():
            accounts[name] = {k: v for k, v in a.items() if k != "recent_trades"}
            accounts[name]["net_pnl"] = str(Decimal(a["equity"]) - Decimal(a["funding"]))
            accounts[name]["valuation_fresh"] = (
                a["valuation_fresh"]
                and not stale
                and fresh_frame({"observed": a.get("valuation_at")}, now)
            )
            risk = risk_summary(a, self.state["paused"], now)
            if stale or self.error:
                risk.update(
                    blocked=True,
                    recoverable=False,
                    reason="Paper worker unavailable or stale; wait for fresh status.",
                    recovery_reason="Wait for the paper worker to recover.",
                )
            accounts[name]["risk"] = risk
        return {
            "enabled": True,
            "mode": "paper",
            "tier": 3,
            "running": self.running,
            "error": self.error,
            "feed_errors": {
                **self.feed_errors,
                **{symbol + " candles": error for symbol, error in self._candle_errors.items()},
            },
            "stale": stale,
            "paused": self.state["paused"],
            "started_at": self.state["started_at"],
            "last_tick": self.state["last_tick"],
            "next_review": self.state["next_review"],
            "review_count": self.state["review_count"],
            "reviews": self.state["review_history"],
            "promotions": self.state["promotion_count"],
            "features": self.state["features"],
            "accounts": accounts,
            "campaigns": list(self.state.get("campaigns", {}).values()),
            "economics": economics_report(
                self.state, now, self.running and not stale and self.error is None
            ),
            "execution_profiles": [p.describe() for p in PROFILES.values()],
            "events": self.recent,
            "journal": self.receipts,
            "bars_studied": self.state["study_bars"],
            "gaps": self.state["gaps"],
            "target": "1000",
            "replenish_below": "5",
            "replenish_to": "100",
            "repeatability": {
                "won": primary["attempt_wins"],
                "failed": primary["attempt_failures"],
                "open": int(primary["attempt"]["outcome"] == "open"),
                "conclusion": "Not established; open attempts and correlated shadows are not proof",
            },
            "cost_model": (
                PROFILES[execution(primary).id].label
                if primary.get("execution_profile", "paper-rest-ioc-v1") in PROFILES
                else "Unknown execution profile"
            )
            + " · 2 bps adverse price + 10% depth participation",
            "sampling": "Public REST, about 2 seconds plus request time; stops can gap",
        }

    def set_paused(self, value: bool) -> None:
        def apply(engine: PaperEngine) -> None:
            if engine.state["paused"] == value:
                return
            engine.state["paused"] = value
            engine.emit("entry_control", "primary", {"paused": value})
            if value:
                for name, a in engine.state["accounts"].items():
                    for symbol, order in list(a["pending"].items()):
                        if order["side"] == "buy":
                            engine.cancel(name, a, symbol, "Operator paused entries")

        self.state = self.store.transact(time.time(), apply)

    def control_frames(self) -> dict[str, dict[str, Any]]:
        return self.books

    def campaign_create(self, spec: CampaignSpec) -> dict[str, Any]:
        self.require_healthy_control()
        result: dict[str, Any] = {}
        self.state = self.store.transact(
            time.time(), lambda engine: result.update(create_campaign(engine, spec))
        )
        return result

    def require_healthy_control(self) -> None:
        if not self.running or self.error or not 0 <= time.time() - self.state["last_tick"] <= 10:
            raise ValueError("Paper worker unavailable or stale; wait for fresh status")

    def account_control(self, name: str, action: str, version: int) -> dict[str, Any]:
        self.require_healthy_control()
        result: dict[str, Any] = {}
        frames = self.control_frames() if action == "recover" else {}
        self.state = self.store.transact(
            time.time(),
            lambda engine: result.update(control_account(engine, name, action, version, frames)),
        )
        return {**result, "account": name}

    def risk_control(self, name: str, action: str, stop_id: int) -> dict[str, Any]:
        if not self.running or self.error or not 0 <= time.time() - self.state["last_tick"] <= 10:
            raise ValueError("Paper worker unavailable or stale; wait for fresh status.")
        result: dict[str, Any] = {}

        def apply(engine: PaperEngine) -> None:
            if action == "adopt_hard_stop":
                result.update(engine.adopt_hard_stop(name))
            elif action == "resume_hard_stop":
                result.update(engine.recover_hard_stop(name, stop_id))
            else:
                raise ValueError("Unknown risk action.")

        self.state = self.store.transact(time.time(), apply)
        return {
            **result,
            "account": name,
            "risk": risk_summary(self.state["accounts"][name], self.state["paused"], time.time()),
        }

    def economics_control(
        self, name: str, profile: str, daily_usd: str | None, expected_version: int
    ) -> dict[str, Any]:
        if not self.running or self.error or not 0 <= time.time() - self.state["last_tick"] <= 10:
            raise ValueError("Paper worker unavailable; wait for fresh status")
        result: dict[str, Any] = {}

        def apply(engine: PaperEngine) -> None:
            result.update(engine.set_economics(name, profile, daily_usd, expected_version))

        self.state = self.store.transact(time.time(), apply)
        return {**result, "account": name}
