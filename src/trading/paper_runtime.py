"""Public REST observer and persistent four-hour learner; no model API dependency."""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
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
from trading.redesign_strategy import STRATEGIES
from trading.redesign_strategy import features as replacement_features
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
        self._notice_epoch = uuid.uuid4().hex
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

    def replacement_study(self, symbol: str, now: float) -> dict[str, Any]:
        versions = {
            a["version"]
            for a in self.state["accounts"].values()
            if a["version"] in STRATEGIES and symbol in a.get("symbols", SYMBOLS)
        }
        bars = self.history.get(symbol, [])[-600:]
        return {v: replacement_features(bars, now, v) for v in sorted(versions)}

    def lab_history(self, now: float, horizon: str) -> list[Bar]:
        if horizon == "short":
            return self.history.get("BTCUSD", [])
        # One shared bounded 9,000-minute history per closed minute, fetched
        # outside the financial transaction. No account duplicates or bulk loads.
        stamp = int(now // 60)
        cache = getattr(self, "_lab_history_cache", None)
        if cache is None or cache[0] != stamp:
            with self.store.transaction_lock:
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
        from trading.autonomous_spec import RuleSpec
        from trading.rule_components import reviewed_feature

        specs = {}
        for a in self.state["accounts"].values():
            if a.get("rule_spec"):
                key = a["version"] + ":" + a["execution_profile"]
                specs[key] = a
        cache = getattr(self, "_lab_features", {})
        self._lab_features = {k: v for k, v in cache.items() if k in specs}
        for key, a in specs.items():
            spec = RuleSpec.model_validate(a["rule_spec"])
            bars = (
                self.history.get("BTCUSD", [])[-600:]
                if spec.version == "reviewed-lab-rules-v4"
                else self.lab_history(now, spec.holding_horizon)
            )
            stamp = bars[-1].open_ms if bars else -1
            cached = self._lab_features.get(key)
            if cached is None or cached[0] != stamp or spec.entry_filter is not None:
                calculated = reviewed_feature(
                    bars, now, spec, a["execution_profile"], self.memory_book("BTCUSD")
                )
                self._lab_features[key] = stamp, calculated
            feature = dict(self._lab_features[key][1])
            if spec.version == "reviewed-lab-rules-v4":
                feature["input_checked_at"] = now
                if feature.get("input_available_at", 0) <= self.ready_at:
                    feature.update(
                        eligible=False,
                        reason="Bootstrap only; awaiting a subsequent complete five-minute bar",
                    )
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
        self._transact_state(
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
                study[symbol].update(self.replacement_study(symbol, received))
                # Startup history is for features, never a backlog of trade opportunities.
                for feature in study[symbol].values():
                    bootstrap = (
                        feature.get("input_available_at", 0) <= self.ready_at
                        if feature.get("redesign_version")
                        else feature.get("bar_open_ms", 0) + 60000 < self.ready_at * 1000
                    )
                    if bootstrap:
                        feature.update(
                            eligible=False, reason="Bootstrap only; awaiting new closed bar"
                        )
                    if symbol in self._candle_errors:
                        feature.update(eligible=False, reason=self._candle_errors[symbol])
                risk_input = study[symbol].get("breakout-v1", {})
                bar_open = risk_input.get("bar_open_ms")
                frame["diagnostic_risk_input_valid"] = (
                    isinstance(bar_open, (int, float))
                    and not isinstance(bar_open, bool)
                    and 0 < received * 1000 - bar_open - 59999 <= 90000
                    and bar_open + 60000 >= self.ready_at * 1000
                    and symbol not in self._candle_errors
                    and risk_input.get("closed_bars", 0) >= 305
                )
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
                    engine.tick(frames, study, diagnostic_allowed=self.diagnostic_entries_allowed())

                self._transact_state(now, apply)
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
        state = self.state
        primary = state["accounts"]["primary"]
        now = time.time()
        stale = now - state["last_tick"] > 10 or not self.running
        accounts = {}
        for name, a in state["accounts"].items():
            accounts[name] = {k: v for k, v in a.items() if k != "recent_trades"}
            accounts[name]["net_pnl"] = str(Decimal(a["equity"]) - Decimal(a["funding"]))
            accounts[name]["valuation_fresh"] = (
                a["valuation_fresh"]
                and not stale
                and fresh_frame({"observed": a.get("valuation_at")}, now)
            )
            risk = risk_summary(a, state["paused"], now)
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
            "evidence_kind": state.get("evidence_kind", "observed_public_market"),
            "tier": 3,
            "running": self.running,
            "error": self.error,
            "feed_errors": {
                **self.feed_errors,
                **{symbol + " candles": error for symbol, error in self._candle_errors.items()},
            },
            "stale": stale,
            "paused": state["paused"],
            "started_at": state["started_at"],
            "last_tick": state["last_tick"],
            "next_review": state["next_review"],
            "review_count": state["review_count"],
            "reviews": state["review_history"],
            "promotions": state["promotion_count"],
            "features": state["features"],
            "accounts": accounts,
            "campaigns": list(state.get("campaigns", {}).values()),
            "diagnostics": self.diagnostic_snapshot(state=state),
            "learning": self.learning_snapshot(state=state),
            "economics": economics_report(
                state, now, self.running and not stale and self.error is None
            ),
            "execution_profiles": [p.describe() for p in PROFILES.values()],
            "events": self.recent,
            "journal": self.receipts,
            "bars_studied": state["study_bars"],
            "gaps": state["gaps"],
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

        self._transact_state(time.time(), apply)

    def control_frames(self) -> dict[str, dict[str, Any]]:
        return self.books

    def campaign_create(self, spec: CampaignSpec) -> dict[str, Any]:
        self.require_healthy_control()
        result: dict[str, Any] = {}
        self._transact_state(
            time.time(), lambda engine: result.update(create_campaign(engine, spec))
        )
        return result

    def require_healthy_control(self) -> None:
        if not self.running or self.error or not 0 <= time.time() - self.state["last_tick"] <= 10:
            raise ValueError("Paper worker unavailable or stale; wait for fresh status")

    def diagnostic_entries_allowed(self) -> bool:
        return (
            self.running and self.error is None and 0 <= time.time() - self.state["last_tick"] <= 10
        )

    def diagnostic_snapshot(self, *, state: dict[str, Any] | None = None) -> dict[str, Any]:
        from trading.paper_diagnostics import diagnostic_snapshot

        # The status loop uses one cached committed projection; only the dedicated
        # synchronous GET reconciles an uncertain acknowledgment through SQL.
        if state is None and getattr(self, "_diagnostic_outcome_unknown", False):
            if not self.store.transaction_lock.acquire(timeout=2):
                raise psycopg.OperationalError("Diagnostic receipt refresh is busy")
            try:
                with self.store.connection.transaction():
                    self.store.connection.execute("SET LOCAL statement_timeout = '2000ms'")
                    self.state = self.store.read()
                self._diagnostic_outcome_unknown = False
            finally:
                self.store.transaction_lock.release()
        state = self.state if state is None else state
        result = diagnostic_snapshot(state)
        if result.get("account"):
            a = result["account"]
            a["valuation_fresh"] = (
                a["valuation_fresh"]
                and self.running
                and self.error is None
                and 0 <= time.time() - state["last_tick"] <= 10
                and fresh_frame({"observed": a.get("valuation_at")}, time.time())
            )
            a["net_pnl"] = str(Decimal(a["equity"]) - Decimal(a["funding"]))
        return {
            **result,
            "entries_allowed": self.diagnostic_entries_allowed(),
            "running": self.running,
            "error": self.error,
            "stale": not 0 <= time.time() - state["last_tick"] <= 10 or not self.running,
        }

    def _transact_state(self, now: float, work: Callable[[PaperEngine], None]) -> None:
        # Publish while retaining the writer lock: a later commit cannot be
        # overwritten by an older diagnostic worker's delayed assignment.
        with self.store.transaction_lock:
            self.state = self.store.transact(now, work)

    def _diagnostic_control(self, work: Callable[[PaperEngine], None]) -> None:
        with self.store.transaction_lock:
            try:
                self._transact_state(time.time(), work)
            except psycopg.Error:
                # A missing acknowledgment is not evidence that the operation rolled
                # back. GET reconciles once through the same owned state authority.
                self._diagnostic_outcome_unknown = True
                raise
            self._diagnostic_outcome_unknown = False

    def diagnostic_create(self, request_id: str) -> dict[str, Any]:
        from trading.paper_diagnostics import create_diagnostic

        self.require_healthy_control()
        result: dict[str, Any] = {}
        self._diagnostic_control(
            lambda engine: result.update(create_diagnostic(engine, request_id))
        )
        return result

    def diagnostic_start(
        self, request_id: str, seed: int, max_actions: int = 1000, duration_seconds: int = 600
    ) -> dict[str, Any]:
        from trading.paper_diagnostics import start_diagnostic

        self.require_healthy_control()
        if not self.diagnostic_entries_allowed():
            raise ValueError("Performance load is paused by the current financial/resource guard")
        result: dict[str, Any] = {}
        self._diagnostic_control(
            lambda engine: result.update(
                start_diagnostic(engine, request_id, seed, max_actions, duration_seconds)
            ),
        )
        return result

    def diagnostic_stop(self, request_id: str) -> dict[str, Any]:
        from trading.paper_diagnostics import stop_diagnostic

        # Stop creates no new load or guessed fill. The owned transaction still
        # verifies financial invariants while fresh observations may be unavailable.
        result: dict[str, Any] = {}
        self._diagnostic_control(lambda engine: result.update(stop_diagnostic(engine, request_id)))
        return result

    def learning_snapshot(self, *, state: dict[str, Any] | None = None) -> dict[str, Any]:
        from trading.paper_learning import snapshot

        return snapshot(self.state if state is None else state)

    def forward_control(self, candidate: str) -> dict[str, Any]:
        from trading.paper_learning import matched_control

        self.require_healthy_control()
        result: dict[str, Any] = {}
        self._transact_state(time.time(), lambda e: result.update(matched_control(e, candidate)))
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
        self._transact_state(now, lambda e: result.update(retain_report(e, request_id, report)))
        return result

    def retained_learning_report(self, request_id: str) -> dict[str, Any] | None:
        reference = self.state.get("learning", {}).get("reports", {}).get(request_id)
        if not reference:
            return None
        # Export runs in a worker thread. Never share its query/transaction with
        # the exclusive financial writer's connection.
        from trading.scoped_tools import reader

        with reader(self) as view:
            return view.learning_report(request_id, reference["sha256"])

    def learning_role(
        self, action: str, version: int, report_id: str = "", sha: str = ""
    ) -> dict[str, Any]:
        from trading.paper_learning import designate, rollback

        self.require_healthy_control()
        result: dict[str, Any] = {}
        receipt = self.retained_learning_report(report_id) if action == "designate" else None
        self._transact_state(
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
        self._transact_state(
            time.time(),
            lambda engine: result.update(control_account(engine, name, action, version, frames)),
        )
        return {**result, "account": name}

    def strategy_change(self, name: str, spec: Any) -> dict[str, Any]:
        from trading.account_redesign import change_strategy

        self.require_healthy_control()
        result: dict[str, Any] = {}

        def apply(engine: PaperEngine) -> None:
            # Permanent request receipts live in the existing append-only journal.
            previous = self.store.connection.execute(
                "SELECT account,body FROM paper_events WHERE kind='account_strategy_changed' "
                "AND body->>'request_id'=%s LIMIT 2",
                (spec.request_id,),
            ).fetchall()
            if previous:
                if (
                    len(previous) != 1
                    or previous[0]["account"] != name
                    or any(
                        previous[0]["body"].get(key) != value
                        for key, value in spec.model_dump().items()
                    )
                ):
                    raise ValueError(
                        "This request already names a different account or rule change"
                    )
                result.update(status="already_applied", account=name, **previous[0]["body"])
                return
            result.update(change_strategy(engine, name, spec))

        self._transact_state(time.time(), apply)
        return result

    def strategy_receipt(self, name: str, request_id: str) -> dict[str, Any] | None:
        with self.store.transaction_lock:
            row = self.store.connection.execute(
                "SELECT body FROM paper_events WHERE kind='account_strategy_changed' "
                "AND account=%s AND body->>'request_id'=%s ORDER BY id DESC LIMIT 1",
                (name, request_id),
            ).fetchone()
        return {"status": "applied", "account": name, **row["body"]} if row else None

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

        self._transact_state(time.time(), apply)
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

        self._transact_state(time.time(), apply)
        return {**result, "account": name}
