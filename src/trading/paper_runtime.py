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
        self._lab_features: dict[str, tuple[int, dict[str, Any]]] = {}

    def memory_book(self, symbol: str) -> dict[str, Any] | None:
        return self.books.get(symbol)

    def lab_history(self, now: float, horizon: str) -> list[Bar]:
        if horizon == "short":
            return self.history.get("BTCUSD", [])
        # One shared bounded 9,000-minute history per closed minute, fetched
        # outside the financial transaction. No account duplicates or bulk loads.
        stamp = int(now // 60)
        cache = getattr(self, "_lab_history_cache", None)
        if cache is None or cache[0] != stamp:
            rows = self.store.connection.execute(
                (
                    "SELECT body FROM paper_bars WHERE symbol='BTCUSD' AND observ"
                    "ed_at<=%s AND open_ms+60000<=%s ORDER BY open_ms DESC LIMIT "
                    "9000"
                ),
                (now, now * 1000),
            ).fetchall()
            result = (
                parse_bars([r["body"] for r in reversed(rows[:1000])], now)
                if len(rows) <= 1000
                else []
            )
            if len(rows) > 1000:
                for start in range(0, len(rows), 1000):
                    result.extend(
                        parse_bars([r["body"] for r in reversed(rows[start : start + 1000])], now)
                    )
                result.sort(key=lambda b: b.open_ms)
            self._lab_history_cache = stamp, result
        return list(self._lab_history_cache[1])

    def numerical_study(self, now: float, study: dict[str, Any]) -> None:
        from trading.autonomous_spec import RuleSpec, rule_feature

        specs = {}
        for a in self.state["accounts"].values():
            if a.get("rule_spec"):
                key = a["version"] + ":" + a["execution_profile"]
                specs[key] = a
        cache = getattr(self, "_lab_features", {})
        self._lab_features = {k: v for k, v in cache.items() if k in specs}
        for key, a in specs.items():
            spec = RuleSpec.model_validate(a["rule_spec"])
            bars = self.lab_history(now, spec.holding_horizon)
            stamp = bars[-1].open_ms if bars else -1
            cached = self._lab_features.get(key)
            if cached is None or cached[0] != stamp:
                calculated = rule_feature(bars, now, spec, a["execution_profile"])
                self._lab_features[key] = stamp, calculated
            feature = dict(self._lab_features[key][1])
            if not bars or not 0 < now * 1000 - bars[-1].close_ms <= 90000:
                feature.update(eligible=False, reason="Awaiting a fresh subsequent closed candle")
            study.setdefault("BTCUSD", {})[a["version"]] = feature
        candidates = [
            a
            for a in self.state["accounts"].values()
            if a.get("numerical_artifact") or a.get("memory_entry_contract") == "memory-entry-v1"
        ]
        if not candidates:
            return
        minute = int(now // 60)
        if minute != self._numerical_minute and any(
            not a.get("memory_entry_contract") for a in candidates
        ):
            try:
                self._numerical_rows = self.store.numerical_inputs(now)
            except psycopg.Error:
                self._numerical_rows = []  # Research input loss never invents a signal.
            self._numerical_minute = minute
        for a in candidates:
            try:
                artifact = a["numerical_artifact"]
                if a.get("memory_entry_contract") == "memory-entry-v1":
                    from trading.evidence_runtime import frozen_bars
                    from trading.memory_quality import filtered_feature
                    from trading.pattern_memory import descriptor
                    from trading.research_evidence import book_features

                    base = study.get("BTCUSD", {}).get("breakout-v1", {})
                    book = self.memory_book("BTCUSD")
                    memory_input: dict[str, Any] = {
                        "bars": frozen_bars(self.history.get("BTCUSD", [])[-11:], now),
                        "cutoff": now,
                        "context": {"book": book_features(book, now) if book else None},
                        "data_mode": "forward-paper",
                    }
                    d = descriptor(
                        memory_input["bars"], now, memory_input["context"], "forward-paper"
                    )
                    started = time.perf_counter()
                    feature = filtered_feature(base, d, artifact, now)
                    completed = time.time()
                    feature["memory_evidence"].update(
                        available_at=completed,
                        earliest_action_at=completed,
                        inference_ms=(time.perf_counter() - started) * 1000,
                    )
                    if d.get("expires_at") is not None and completed > d["expires_at"]:
                        feature = {
                            **base,
                            "memory_evidence": {
                                "status": "result_too_late",
                                "action": "no_additional_signal",
                                "available_at": completed,
                                "earliest_action_at": completed,
                            },
                        }
                    feature["memory_descriptor"] = d
                    feature["memory_input"] = memory_input
                    if d.get("cutoff", now) <= a["admitted_at"]:
                        feature.update(
                            eligible=False, reason="Awaiting a subsequent memory opportunity"
                        )
                else:
                    feature = signal(self._numerical_rows, now, artifact, a["admitted_at"])
            except (ValueError, KeyError, TypeError, ArithmeticError):
                if a.get("memory_entry_contract") == "memory-entry-v1":
                    feature = {
                        **study.get("BTCUSD", {}).get("breakout-v1", {}),
                        "memory_evidence": {
                            "status": "invalid_input",
                            "action": "no_additional_signal",
                            "reason": "Optional memory unavailable; baseline rules apply",
                        },
                    }
                else:
                    feature = {
                        "eligible": False,
                        "reason": "Frozen numerical input/model needs attention",
                    }
            study.setdefault("BTCUSD", {})[a["version"]] = feature

    def forward_admit(
        self, experiment: str, artifact: dict[str, Any], cash: str, daily: str | None
    ) -> dict[str, Any]:
        self.require_healthy_control()
        result: dict[str, Any] = {}
        self.state = self.store.transact(
            time.time(), lambda e: result.update(admit(e, experiment, artifact, cash, daily))
        )
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
                now = (
                    time.time()
                )  # A completed optional calculation is never backdated to dispatch.

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
            "evidence_kind": self.state.get("evidence_kind", "observed_public_market"),
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
            "learning": self.learning_snapshot(),
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
            + " Â· 2 bps adverse price + 10% depth participation",
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

    def learning_snapshot(self) -> dict[str, Any]:
        from trading.paper_learning import snapshot

        return snapshot(self.state)

    def forward_control(self, candidate: str) -> dict[str, Any]:
        from trading.paper_learning import matched_control

        self.require_healthy_control()
        result: dict[str, Any] = {}
        self.state = self.store.transact(
            time.time(), lambda e: result.update(matched_control(e, candidate))
        )
        return result

    def learning_report(self, request_id: str, candidate: str, registry: Any) -> dict[str, Any]:
        from trading.paper_learning import comparison, retain_report

        self.require_healthy_control()
        old = self.state.get("learning", {}).get("reports", {}).get(request_id)
        if old:
            if old["candidate"] != candidate:
                raise ValueError("Report retry names a different candidate")
            retained = self.retained_learning_report(request_id)
            if retained is None:
                raise ValueError("Retained report journal unavailable")
            return dict(retained, status="already_applied")
        now = time.time()
        history = self.store.forward_windows(now)
        protected = registry.snapshot()["protected_through"]
        report = comparison(
            self.state,
            candidate,
            history["windows"],
            now,
            protected,
            truncated=history["truncated"],
        )
        report["source_event_ids"] = history["event_ids"]
        # Inspection consumes information even if subsequent journal persistence fails.
        with registry.transaction():
            registry.db.execute(
                "INSERT OR IGNORE INTO evidence_windows VALUES "
                "(?,?,?,'forward account inspection')",
                (
                    "forward-" + request_id,
                    self.state["accounts"][candidate].get("admitted_at", now),
                    now,
                ),
            )
            registry.event(
                request_id,
                "forward_inspection",
                {
                    "candidate": candidate,
                    "decision": report["decision"],
                    "consumed_through": now,
                },
            )
        result: dict[str, Any] = {}
        self.state = self.store.transact(
            now, lambda e: result.update(retain_report(e, request_id, report))
        )
        return result

    def retained_learning_report(self, request_id: str) -> dict[str, Any] | None:
        reference = self.state.get("learning", {}).get("reports", {}).get(request_id)
        if not reference:
            return None
        # Export runs in a worker thread. Never share its query/transaction with
        # the exclusive financial writer's connection.
        reader = PaperStore(self.store.connection.info.dsn)
        try:
            return reader.learning_report(request_id, reference["sha256"])
        finally:
            reader.close()

    def learning_role(
        self, action: str, version: int, report_id: str = "", sha: str = ""
    ) -> dict[str, Any]:
        from trading.paper_learning import designate, rollback

        self.require_healthy_control()
        result: dict[str, Any] = {}
        receipt = self.retained_learning_report(report_id) if action == "designate" else None
        self.state = self.store.transact(
            time.time(),
            lambda e: result.update(
                designate(e, report_id, sha, version, receipt)
                if action == "designate"
                else rollback(e, version)
            ),
        )
        return result

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
