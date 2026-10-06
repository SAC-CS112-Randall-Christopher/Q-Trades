"""Deterministic cash-only simulator. Every mutation is committed with its evidence."""

import hashlib
import json
import math
import time
from copy import deepcopy
from decimal import Decimal
from typing import Any

from trading.account_purpose import PERFORMANCE_DIAGNOSTIC_PURPOSE, is_performance_diagnostic
from trading.execution_profiles import LEGACY_EXECUTION, PROFILES, execution
from trading.execution_profiles import floor_step as floor_step
from trading.execution_profiles import walk_book as walk_book
from trading.market import Book
from trading.paper_economics import observe as observe_economics
from trading.paper_strategy import VARIANTS

D = Decimal
FEE = D("0.001")
SLIPPAGE = D("0.0002")
PARTICIPATION = D("0.10")
REVIEW_SECONDS = 4 * 3600
SYMBOLS = ("BTCUSD", "ETHUSD")
MODEL_VERSION = "paper-rest-ioc-v1"
HARD_STOP_POLICY = "cash-spot-hard-stop-v1"
LEGACY_POLICY = "legacy-paper-review-v1"


def policy(a: dict[str, Any]) -> str:
    # An absent field identifies pre-CP1 history; unknown explicit values fail closed.
    return str(a.get("risk_policy", LEGACY_POLICY))


def fresh_frame(frame: dict[str, Any] | None, now: float) -> bool:
    if not frame:
        return False
    stamp = frame.get("observed")
    return (
        isinstance(stamp, (int, float))
        and not isinstance(stamp, bool)
        and math.isfinite(stamp)
        and 0 <= now - stamp <= 5
    )


def recovery_reason(a: dict[str, Any], now: float) -> str | None:
    if policy(a) != HARD_STOP_POLICY:
        return "Recovery requires the explicit hard-stop policy."
    if not a["drawdown_pause"]:
        return "There is no hard drawdown stop to resume."
    if not a["valuation_fresh"] or not fresh_frame({"observed": a.get("valuation_at")}, now):
        return "Wait for a fresh, complete portfolio valuation."
    if a["failure_pending"] or a["attempt"]["outcome"] == "failed":
        return "This failed attempt stays stopped; no top-up or loss-budget reset is permitted."
    if D(a["equity"]) <= D(a["risk_peak"]) * D("0.65"):
        return "Equity must recover above the existing 35% loss limit; the reference is unchanged."
    if a["daily_pause"]:
        return "The daily loss pause still applies until the next UTC day."
    if now < a["cooldown_until"]:
        return "Wait for the existing entry cooldown."
    return None


def entry_reason(a: dict[str, Any], paused: bool, now: float) -> str | None:
    if policy(a) not in {LEGACY_POLICY, HARD_STOP_POLICY}:
        return "Unknown risk policy; entries require inspection."
    if paused:
        return "Operator paused entries; position exits remain enabled."
    if a.get("fault"):
        return "Account processing stopped; inspect its recovery panel. Sibling accounts continue."
    if a.get("entries_paused"):
        return "Operator paused this account's entries; position exits remain enabled."
    if not a["valuation_fresh"] or not fresh_frame({"observed": a.get("valuation_at")}, now):
        issues = a.get("valuation_issues", {})
        detail = "; ".join(f"{symbol}: {reason}" for symbol, reason in issues.items())
        return "Portfolio valuation unavailable" + (": " + detail if detail else ".")
    if a["failure_pending"]:
        if a["attempt"]["outcome"] == "failed":
            return "Attempt failed; history retained. No automatic top-up or restart."
        return "Account below $5; managing remaining exits."
    if a["drawdown_pause"]:
        return (
            "Hard drawdown stop; operator recovery required."
            if policy(a) == HARD_STOP_POLICY
            else "Historical drawdown pause; legacy scheduled review governs recovery."
        )
    if a["daily_pause"]:
        return "Daily loss pause until the next UTC day."
    if now < a["cooldown_until"]:
        return "Entry cooldown is still active."
    return None


def risk_summary(a: dict[str, Any], paused: bool, now: float) -> dict[str, Any]:
    reason = entry_reason(a, paused, now)
    recovery = recovery_reason(a, now)
    controls_blocked = paused or bool(a.get("entries_paused")) or bool(a.get("fault"))
    return {
        "policy": policy(a),
        "legacy": policy(a) == LEGACY_POLICY,
        "blocked": reason is not None,
        "reason": reason or "Entries permitted when the strategy and cash checks qualify.",
        "valuation_issues": dict(a.get("valuation_issues", {})),
        "stop_id": a.get("risk_stop_id", 0),
        "recoverable": recovery is None and not controls_blocked,
        "recovery_reason": (reason if controls_blocked else recovery),
        "last_recovery": a.get("risk_recovery"),
        "risk_reference": a["risk_peak"],
        "stop_equity": str(D(a["risk_peak"]) * D("0.65")),
    }


def observation_evidence(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        key: frame.get(key)
        for key in (
            "source",
            "observed",
            "exchange_event_ms",
            "event_age_ms",
            "clock_uncertainty_ms",
            "request_sent_at",
            "round_trip_ms",
            "raw_update",
            "futures_context",
        )
    }


def filters(instrument: dict[str, Any]) -> dict[str, Decimal]:
    if (
        instrument.get("quote") != "USD"
        or instrument.get("venue_status") != "TRADING"
        or not instrument.get("spot_allowed")
    ):
        raise ValueError("USD spot market is not trading")
    items = {f["filterType"]: f for f in instrument["filters"]}
    lot, price = items["LOT_SIZE"], items["PRICE_FILTER"]
    result = {
        "step": D(lot["stepSize"]),
        "min_qty": D(lot["minQty"]),
        "max_qty": D(lot["maxQty"]),
        "tick": D(price["tickSize"]),
        "min_notional": D(instrument["minimum_notional"]),
        "min_price": D(price["minPrice"]),
        "max_price": D(price["maxPrice"]),
    }
    if any(not v.is_finite() or v < 0 for v in result.values()):
        raise ValueError("Invalid instrument filter")
    if result["step"] <= 0 or result["tick"] <= 0 or result["max_qty"] <= 0:
        raise ValueError("Incomplete instrument filter")
    # Dynamic percent-price restrictions cannot be reconstructed from a 20-level book.
    # The deliberately tight price cap is modeled; live eligibility is not claimed.
    return result


def account(
    version: str, now: float, starting_cash: str = "100", execution_profile: str = LEGACY_EXECUTION
) -> dict[str, Any]:
    if starting_cash not in {"50", "100"} or execution_profile not in PROFILES:
        raise ValueError("Declare $50 or $100 with a supported paper execution profile")
    return {
        "version": version,
        "risk_policy": HARD_STOP_POLICY,
        "starting_capital": starting_cash,
        "execution_profile": execution_profile,
        "economics_settings_version": 0,
        "execution_drag_usd": "0",
        "risk_stop_id": 0,
        "risk_recovery": None,
        "cash": starting_cash,
        "funding": starting_cash,
        "fees": "0",
        "positions": {},
        "pending": {},
        "cooldowns": {},
        "closed": 0,
        "wins": 0,
        "realized": "0",
        "recent_trades": [],
        "equity": starting_cash,
        "valuation_fresh": False,
        "risk_peak": starting_cash,
        "units": starting_cash,
        "nav_peak": "1",
        "max_drawdown": "0",
        "drawdown_pause": False,
        "day": int(now // 86400),
        "day_start": starting_cash,
        "day_turnover": "0",
        "daily_pause": False,
        "cooldown_until": 0,
        "attempt": {"number": 1, "started_at": now, "outcome": "open"},
        "attempt_wins": 0,
        "attempt_failures": 0,
        "replenishments": 0,
        "failure_pending": False,
        "last_decision": {},
        "last_exit": None,
        "last_fill_sequence": {},
    }


def initial_state(
    now: float, starting_cash: str = "100", execution_profile: str = LEGACY_EXECUTION
) -> dict[str, Any]:
    return {
        "schema": 1,
        "model": MODEL_VERSION,
        "started_at": now,
        "last_tick": now,
        "evidence_kind": "observed_public_feed",
        "last_review": now,
        "next_review": now + REVIEW_SECONDS,
        "paused": False,
        "accounts": {
            "primary": account("breakout-v1", now, starting_cash, execution_profile),
            **{
                version: account(version, now, starting_cash, execution_profile)
                for version in VARIANTS
            },
        },
        "features": {},
        "review_count": 0,
        "promotion_count": 0,
        "last_promotion": now,
        "review_history": [],
        "gaps": 0,
        "study_bars": 0,
        "last_error": None,
        "last_snapshot_minute": -1,
        "book_sequences": {},
    }


class PaperEngine:
    def __init__(self, state: dict[str, Any], now: float):
        self.state = state
        self.now = now
        self.events: list[dict[str, Any]] = []
        self.diagnostic_allowed = True
        self.evidence_trace: list[dict[str, Any]] | None = None

    def emit(
        self, kind: str, owner: str, body: dict[str, Any], lines: list[dict[str, str]] | None = None
    ) -> None:
        if lines:
            totals: dict[str, Decimal] = {}
            for row in lines:
                totals[row["asset"]] = totals.get(row["asset"], D(0)) + D(row["amount"])
            if any(v != 0 for v in totals.values()):
                raise ValueError("Unbalanced asset journal")
        event = {"at": self.now, "kind": kind, "account": owner, "body": body, "lines": lines or []}
        a = self.state["accounts"].get(owner)
        if a is not None and is_performance_diagnostic(a, owner):
            # The SQL journal persists body; in-memory/full capture also preserves
            # the explicit top-level purpose. Baseline event shapes stay unchanged.
            event["purpose"] = PERFORMANCE_DIAGNOSTIC_PURPOSE
            event["body"] = {**body, "purpose": PERFORMANCE_DIAGNOSTIC_PURPOSE}
            diagnostic = a.get("diagnostic", {})
            run = diagnostic.get("runs", {}).get(diagnostic.get("active_request_id"))
            counter = {"order_intent": "intents", "fill": "fills", "order_cancelled": "cancels",
                       "account_fault": "errors", "trade_closed": "completed"}.get(kind)
            if run and counter:
                run[counter] += 1
        self.events.append(event)
        if self.evidence_trace is not None:
            self.evidence_trace.append(
                {
                    "phase": "reservation_ready" if kind == "order_intent" else "event_emitted",
                    "kind": kind,
                    "account": owner,
                    "mono": time.monotonic(),
                    "event_index": len(self.events) - 1,
                    "_event": self.events[-1],
                }
            )

    @staticmethod
    def line(asset: str, name: str, amount: Decimal) -> dict[str, str]:
        return {"asset": asset, "bucket": name, "amount": str(amount)}

    def record_futures_context(self, observation: dict[str, Any]) -> None:
        """Journal already-validated context without changing trading/risk decisions."""
        self.emit("futures_context", "system", observation)
        self.state["futures_context"] = {
            k: v for k, v in observation.items() if k not in ("receipts",)
        }
        window = self.state.setdefault(
            "futures_context_window",
            {"started_at": self.now, "snapshots": 0, "unavailable": 0, "omitted": 0, "markets": {}},
        )
        window["snapshots"] += 1
        window["last_observed_at"] = observation["observed_at"]
        for symbol, row in observation["markets"].items():
            if row["status"] != "observed":
                window["unavailable"] += 1
                continue
            key = row["contract"]
            if key not in window["markets"] and len(window["markets"]) >= 64:
                window["omitted"] += 1
                continue
            values = window["markets"].setdefault(
                key,
                {
                    "spot_symbol": symbol,
                    "base": row["base"],
                    "samples": 0,
                    "first_at": row["observed_at"],
                    "first_open_interest_base": row["open_interest_base"],
                    "premium_min_bps": row["premium_bps"],
                    "premium_max_bps": row["premium_bps"],
                    "longs_pay_samples": 0,
                    "shorts_pay_samples": 0,
                    "zero_funding_samples": 0,
                },
            )
            values["samples"] += 1
            values["last_at"] = row["observed_at"]
            values["last_open_interest_base"] = row["open_interest_base"]
            values["premium_min_bps"] = str(
                min(D(values["premium_min_bps"]), D(row["premium_bps"]))
            )
            values["premium_max_bps"] = str(
                max(D(values["premium_max_bps"]), D(row["premium_bps"]))
            )
            direction = D(row["funding_usd_per_base_hour"])
            values[
                "longs_pay_samples"
                if direction > 0
                else "shorts_pay_samples"
                if direction < 0
                else "zero_funding_samples"
            ] += 1

    def seed(self) -> None:
        for name, saved in self.state["accounts"].items():
            amount = D(saved["funding"])
            self.emit(
                "initial_funding",
                name,
                {
                    "amount": str(amount),
                    "currency": "USD",
                    "risk_policy": policy(saved),
                    "execution_profile": execution(saved).id,
                },
                [
                    self.line("USD", "cash", amount),
                    self.line("USD", "fake_funding", -amount),
                ],
            )

    def universe_experiment(self, symbols: list[str]) -> None:
        """A concurrent, separately funded control and challenger; never reset the primary."""
        primary = self.state["accounts"]["primary"]
        capital = primary.get("starting_capital", "100")
        profile = primary.get("execution_profile", LEGACY_EXECUTION)
        if capital not in {"50", "100"} or profile not in PROFILES:
            return  # Unknown account assumptions cannot create a new comparison.
        for name in ("universe-control-v1", "universe-wide-v1"):
            if name not in self.state["accounts"]:
                self.state["accounts"][name] = account("breakout-v1", self.now, capital, profile)
                self.emit(
                    "research_account_created",
                    name,
                    {
                        "amount": capital,
                        "execution_profile": profile,
                        "currency": "USD",
                        "strategy": "breakout-v1",
                        "comparison": "Paired forward universe comparison; balances never pooled",
                    },
                    [
                        self.line("USD", "cash", D(capital)),
                        self.line("USD", "fake_funding", -D(capital)),
                    ],
                )
        self.state["accounts"]["universe-control-v1"]["symbols"] = list(SYMBOLS)
        wide = self.state["accounts"]["universe-wide-v1"]
        membership = sorted(set(symbols) | set(SYMBOLS))
        if membership != wide.get("symbols"):
            self.emit(
                "universe_membership",
                "universe-wide-v1",
                {"previous": wide.get("symbols", []), "selected": membership},
            )
            wide["symbols"] = membership

    def cancel(self, name: str, a: dict[str, Any], symbol: str, reason: str) -> None:
        order = a["pending"].pop(symbol, None)
        if order is None:
            return
        reserve = D(order["reserved"])
        self.emit(
            "order_cancelled",
            name,
            {**order, "reason": reason},
            [self.line("USD", "reserved", -reserve), self.line("USD", "cash", reserve)]
            if reserve
            else [],
        )

    def value(self, a: dict[str, Any], frames: dict[str, dict[str, Any]]) -> bool:
        equity = D(a["cash"])
        liquidation_fee, liquidation_drag = D(0), D(0)
        issues: dict[str, str] = {}
        try:
            profile = execution(a)
        except ValueError:
            a.update(
                valuation_fresh=False, valuation_issues={"execution": "Unknown execution profile"}
            )
            return False
        for symbol, pos in a["positions"].items():
            frame = frames.get(symbol)
            if not fresh_frame(frame, self.now):
                issues[symbol] = "fresh price missing"
                continue
            assert frame is not None
            book: Book = frame["book"]
            rules = frame["rules"]
            qty = D(pos["quantity"])
            filled, gross = walk_book(book, "sell", qty, D(0), rules, profile)
            if filled < qty or qty < rules["min_qty"] or gross < rules["min_notional"]:
                issues[symbol] = "insufficient executable depth or quantity below venue minimum"
                continue
            fee = gross * profile.fee(symbol)
            equity += gross - fee
            liquidation_fee += fee
            liquidation_drag += qty * (book.bids[0][0] + book.asks[0][0]) / 2 - gross
        a["valuation_issues"] = issues
        a["valuation_fresh"] = not issues
        if issues:
            return False  # Keep the last complete value, never a misleading partial sum.
        # A fresh tick cannot rejuvenate an older held-asset quote for recovery.
        a["valuation_at"] = min([self.now, *(frames[s]["observed"] for s in a["positions"])])
        a["equity"] = str(equity)
        a["liquidation_fee_usd"] = str(liquidation_fee)
        a["liquidation_drag_usd"] = str(liquidation_drag)
        a["valuation_fresh"] = True
        a["risk_peak"] = str(max(D(a["risk_peak"]), equity))
        nav = equity / D(a["units"])
        peak = max(D(a["nav_peak"]), nav)
        a["nav_peak"] = str(peak)
        a["max_drawdown"] = str(max(D(a["max_drawdown"]), 1 - nav / peak))
        if equity <= D(a["risk_peak"]) * D("0.65") and not a["drawdown_pause"]:
            a["drawdown_pause"] = True
            a["risk_stop_id"] = a.get("risk_stop_id", 0) + 1
            a["risk_stopped_at"] = self.now
            a["risk_stopped_equity"] = a["equity"]
            a["risk_stopped_reference"] = a["risk_peak"]
        if int(self.now // 86400) != a["day"]:
            a.update(
                day=int(self.now // 86400),
                day_start=str(equity),
                day_turnover="0",
                daily_pause=False,
            )
        if equity <= D(a["day_start"]) * D("0.85"):
            a["daily_pause"] = True
        return True

    def fill(
        self,
        name: str,
        a: dict[str, Any],
        symbol: str,
        frame: dict[str, Any],
        frames: dict[str, dict[str, Any]],
    ) -> None:
        order = a["pending"].get(symbol)
        if order is None:
            return  # A serial cancel/expired order cannot be filled later or release funds twice.
        try:
            profile = execution(order)
            fee_rate = profile.fee(symbol)
            if order.get("fee_asset", "USD") != "USD":
                raise ValueError("Unsupported fee asset; no conversion was invented")
        except ValueError as exc:
            self.cancel(name, a, symbol, str(exc))
            return
        if order["side"] == "buy":
            # Revalue at acceptance with the complete observation set, not a cached flag.
            self.value(a, frames)
            reason = entry_reason(a, self.state["paused"], self.now)
            if reason or not frame.get("entry_allowed", True):
                self.cancel(name, a, symbol, reason or "Market metadata is stale; entries paused")
                return
        if not fresh_frame(frame, self.now):
            return
        if (
            self.now < order["created_at"] + profile.latency_seconds
            or frame["observed"] <= order["created_at"]
        ):
            return
        if self.now - order["created_at"] > profile.expiry_seconds:
            self.cancel(name, a, symbol, "IOC observation window expired; no retrospective fill")
            return
        rules = frame["rules"]
        qty = D(order["quantity"])
        if qty != floor_step(qty, rules["step"]) or not rules["min_qty"] <= qty <= rules["max_qty"]:
            self.cancel(name, a, symbol, "Quantity filters changed")
            return
        price_limit = D(order["limit"])
        if (
            price_limit != floor_step(price_limit, rules["tick"])
            or qty * price_limit < rules["min_notional"]
            or not rules["min_price"] <= price_limit <= rules["max_price"]
        ):
            self.cancel(name, a, symbol, "Price or notional filters changed")
            return
        if frame["book"].update_id <= a["last_fill_sequence"].get(symbol, -1):
            return  # Do not repeatedly consume unchanged displayed liquidity.
        filled, gross = walk_book(frame["book"], order["side"], qty, price_limit, rules, profile)
        if filled <= 0:
            self.cancel(name, a, symbol, "No displayed liquidity inside the price cap")
            return
        fee = gross * fee_rate
        lines = []
        base = frame["base"]
        if order["side"] == "buy":
            cost = gross + fee
            reserve = D(order["reserved"])
            if cost > reserve or cost > D(a["cash"]):
                raise ValueError("Fill exceeds reserved cash")
            entry = gross / filled
            stop_distance = D(order["stop_distance"])
            a["cash"] = str(D(a["cash"]) - cost)
            a["positions"][symbol] = {
                "base": base,
                "quantity": str(filled),
                "cost": str(cost),
                "entry": str(entry),
                "stop": str(max(D(0), entry - stop_distance)),
                "risk": str(stop_distance),
                "opened_at": self.now,
                "version": order["version"],
                "one_r": False,
                "entry_features": order["features"],
                "total_cost": str(cost),
                "exit_proceeds": "0",
                "entry_fee": str(fee),
                "exit_fees": "0",
                "planned_unit_risk": order["planned_unit_risk"],
            }
            lines = [
                self.line("USD", "reserved", -reserve),
                self.line("USD", "cash", reserve - cost),
                self.line("USD", "simulated_market", gross),
                self.line("USD", "fees", fee),
                self.line(base, "inventory", filled),
                self.line(base, "simulated_market", -filled),
            ]
        else:
            pos = a["positions"][symbol]
            old_qty = D(pos["quantity"])
            if filled > old_qty:
                raise ValueError("Cannot sell unowned inventory")
            proceeds = gross - fee
            cost = D(pos["cost"]) * filled / old_qty
            a["cash"] = str(D(a["cash"]) + proceeds)
            a["realized"] = str(D(a["realized"]) + proceeds - cost)
            pos["quantity"] = str(old_qty - filled)
            pos["cost"] = str(D(pos["cost"]) - cost)
            pos["exit_proceeds"] = str(D(pos["exit_proceeds"]) + proceeds)
            pos["exit_fees"] = str(D(pos["exit_fees"]) + fee)
            if filled == old_qty:
                pnl = D(pos["exit_proceeds"]) - D(pos["total_cost"])
                trade = {
                    "symbol": symbol,
                    "opened_at": pos["opened_at"],
                    "closed_at": self.now,
                    "version": pos["version"],
                    "pnl": str(pnl),
                    "reason": order["reason"],
                    "entry_features": pos["entry_features"],
                    "cost": pos["total_cost"],
                    "proceeds": pos["exit_proceeds"],
                    "fees": str(D(pos["entry_fee"]) + D(pos["exit_fees"])),
                }
                a["closed"] += 1
                a["wins"] += int(pnl > 0)
                a["recent_trades"] = (a["recent_trades"] + [trade])[-1000:]
                a["last_exit"] = trade
                cooldown = 600
                if is_performance_diagnostic(a, name):
                    from trading.paper_diagnostics import CONTRACT

                    cooldown = CONTRACT["symbol_cooldown_seconds"]
                a["cooldowns"][symbol] = self.now + cooldown
                self.emit("trade_closed", name, trade)
                del a["positions"][symbol]
            lines = [
                self.line("USD", "cash", proceeds),
                self.line("USD", "simulated_market", -gross),
                self.line("USD", "fees", fee),
                self.line(base, "inventory", -filled),
                self.line(base, "simulated_market", filled),
            ]
        mid_notional = filled * (frame["book"].bids[0][0] + frame["book"].asks[0][0]) / 2
        drag = gross - mid_notional if order["side"] == "buy" else mid_notional - gross
        a["execution_drag_usd"] = str(D(a.get("execution_drag_usd", "0")) + drag)
        a["fees"] = str(D(a["fees"]) + fee)
        a["day_turnover"] = str(D(a["day_turnover"]) + gross)
        del a["pending"][symbol]
        a["last_fill_sequence"][symbol] = frame["book"].update_id
        self.emit(
            "fill",
            name,
            {
                **order,
                "filled_quantity": str(filled),
                "gross": str(gross),
                "fee": str(fee),
                "fee_asset": "USD",
                "execution_profile": profile.id,
                "liquidity_role": "taker",
                "embedded_execution_drag_usd": str(drag),
                "vwap": str(gross / filled),
                "model": order.get("model", MODEL_VERSION),
                "observation": observation_evidence(frame),
                "partial": filled < qty,
                "unfilled_cancelled": str(qty - filled),
                "book": frame["raw"],
                "observed_at": frame["observed"],
                "instrument": frame["instrument"],
            },
            lines,
        )

    def enter(
        self,
        name: str,
        a: dict[str, Any],
        symbol: str,
        frame: dict[str, Any],
        feature: dict[str, Any],
    ) -> str:
        if (
            is_performance_diagnostic(a, name)
            and frame.get("diagnostic_risk_input_valid") is not True
        ):
            return "Protected current diagnostic market/risk inputs unavailable"
        if not frame.get("entry_allowed", True):
            return "Market metadata is stale; entries paused"
        reason = entry_reason(a, self.state["paused"], self.now)
        if reason:
            return reason
        if symbol in a["positions"] or symbol in a["pending"]:
            return "Position or pending order already exists"
        if self.now < a["cooldowns"].get(symbol, 0):
            return "Ten-minute symbol cooldown"
        if a.get("rule_spec"):
            available = feature.get("input_available_at")
            if (
                not isinstance(available, (int, float))
                or isinstance(available, bool)
                or not math.isfinite(available)
                or not a["admitted_at"] < available <= self.now
                or self.now - available > 90
            ):
                return "Awaiting a fresh subsequent closed candle for this trial"
        if not feature["eligible"]:
            return str(feature["reason"])
        profile = execution(a)
        fee_rate = profile.fee(symbol)
        book: Book = frame["book"]
        rules = frame["rules"]
        if D(book.metrics()["spread_bps"]) > D(25):
            return "Spread exceeds 25 bps"
        limit = floor_step(book.asks[0][0] * D("1.001"), rules["tick"])
        if not rules["min_price"] <= limit <= rules["max_price"]:
            return "Limit outside venue price range"
        distance = D(feature["atr"]) * D("1.5")
        equity = D(a["equity"])
        reserved = sum((D(o["reserved"]) for o in a["pending"].values()), D(0))
        exposure = max(D(0), (equity - D(a["cash"])) / (1 - fee_rate))
        existing_risk = sum(
            (D(p["quantity"]) * D(p["planned_unit_risk"]) for p in a["positions"].values()), D(0)
        )
        pending_risk = sum(
            (
                D(o["quantity"]) * D(o.get("planned_unit_risk", "0"))
                for o in a["pending"].values()
                if o["side"] == "buy"
            ),
            D(0),
        )
        budget = min(
            D(a["cash"]) - reserved,
            equity * D("0.5"),
            equity * D("0.9") - exposure - reserved,
            D(a["day_start"]) * 30 - D(a["day_turnover"]) - reserved,
        )
        if is_performance_diagnostic(a, name):
            from trading.paper_diagnostics import NOTIONAL_CAP

            requested = D(feature["diagnostic_notional_usd"])
            if not requested.is_finite() or requested <= 0:
                return "Invalid diagnostic notional; no order created"
            budget = min(budget, requested, NOTIONAL_CAP)
        risk = min(equity * D("0.025"), equity * D("0.05") - existing_risk - pending_risk)
        if budget <= 0 or risk <= 0 or distance <= 0:
            return "Cash, turnover, exposure, or risk capacity exhausted"
        # Include adverse execution and both fees in the planned risk denominator.
        unit_risk = distance + limit * (2 * fee_rate + 2 * D(profile.slippage))
        qty = floor_step(
            min(budget / (limit * (1 + fee_rate)), risk / unit_risk, rules["max_qty"]),
            rules["step"],
        )
        if qty < rules["min_qty"] or qty * limit < rules["min_notional"]:
            return "Order below venue minimum after sizing"
        visible, _ = walk_book(book, "buy", qty, limit, rules, profile)
        if visible < qty:
            return "Insufficient conservative displayed depth"
        reserve = qty * limit * (1 + fee_rate)
        order = {
            "symbol": symbol,
            "side": "buy",
            "quantity": str(qty),
            "limit": str(limit),
            "reserved": str(reserve),
            "stop_distance": str(distance),
            "planned_unit_risk": str(unit_risk),
            "version": a["version"],
            "created_at": self.now,
            "features": feature,
            "reason": (
                "Frozen numerical signal"
                if a.get("numerical_artifact")
                else "Reviewed range excursion"
                if a.get("rule_spec", {}).get("family") == "range_reversion"
                else "Seeded performance-only entry"
                if is_performance_diagnostic(a, name)
                else "Closed-bar breakout"
            ),
            "risk_policy": policy(a),
            "execution_profile": profile.id,
            "fee_asset": "USD",
            "book": frame["raw"],
            "model": self.state["model"],
            "observation": observation_evidence(frame),
        }
        a["pending"][symbol] = order
        self.emit(
            "order_intent",
            name,
            order,
            [self.line("USD", "cash", -reserve), self.line("USD", "reserved", reserve)],
        )
        return "Paper entry reserved; waiting for a later book"

    def exit_position(
        self,
        name: str,
        a: dict[str, Any],
        symbol: str,
        frame: dict[str, Any],
        feature: dict[str, Any],
    ) -> None:
        pos = a["positions"][symbol]
        if is_performance_diagnostic(a, name) and a.get("execution_uncertain"):
            pos["exit_blocked"] = "Diagnostic execution uncertain; no new order created"
            return
        if symbol in a["pending"]:
            return
        bid = frame["book"].bids[0][0]
        entry, risk = D(pos["entry"]), D(pos["risk"])
        if bid >= entry + risk:
            pos["one_r"] = True
        if pos["one_r"] and "atr" in feature:
            pos["stop"] = str(max(D(pos["stop"]), bid - D(feature["atr"])))
        elapsed = self.now - pos["opened_at"]
        artifact = a.get("numerical_artifact")
        invalid_artifact = False
        maximum_hold, progress_seconds = 2700, 600
        if a.get("rule_spec"):
            from trading.autonomous_spec import RuleSpec

            timing = RuleSpec.model_validate(a["rule_spec"]).timing
            maximum_hold, progress_seconds = timing["maximum_hold"], timing["progress"]
        if artifact:
            from trading.numerical_candidates import validate_artifact

            try:
                validate_artifact(artifact)
                maximum_hold, progress_seconds = (
                    artifact["maximum_hold_seconds"],
                    artifact["progress_seconds"],
                )
            except (ValueError, KeyError, TypeError, ArithmeticError):
                # Missing optional memory supplies no entry signal. Position management
                # keeps the baseline stop/progress/hold policy, without a model-driven exit.
                invalid_artifact = a.get("memory_entry_contract") != "memory-entry-v1"
        reason = ""
        if a["failure_pending"]:
            reason = "Account below $5: failure liquidation"
        elif a.get("lab_retiring"):
            reason = "Lab retirement: reduce remaining owned inventory"
        elif bid <= D(pos["stop"]):
            reason = "ATR stop" if not pos["one_r"] else "Trailing stop"
        elif is_performance_diagnostic(a, name):
            from trading.paper_diagnostics import current_run

            run = current_run(a)
            if not run or run["status"] != "running":
                reason = "Performance Diagnostic drain"
            elif pos.get("diagnostic_exit_requested"):
                reason = "Seeded Performance Diagnostic exit"
            elif elapsed >= pos["entry_features"]["diagnostic_hold_seconds"]:
                reason = "Frozen Performance Diagnostic brief hold"
        elif invalid_artifact:
            reason = "Invalid frozen numerical artifact; risk reduction"
        elif elapsed >= maximum_hold:
            reason = (
                "Frozen maximum hold"
                if a.get("numerical_artifact") or a.get("rule_spec")
                else "45-minute maximum hold"
            )
        elif elapsed >= progress_seconds and not pos["one_r"]:
            reason = (
                "No 1R progress by frozen horizon checkpoint"
                if a.get("rule_spec")
                else "No 1R progress after ten minutes"
            )
        if not reason:
            return
        rules = frame["rules"]
        qty = D(pos["quantity"])
        limit = max(rules["min_price"], floor_step(bid * D("0.995"), rules["tick"]))
        if qty < rules["min_qty"] or qty * limit < rules["min_notional"]:
            pos["exit_blocked"] = "Remaining inventory below venue minimum; no invented fill"
            return
        pos.pop("exit_blocked", None)
        order = {
            "symbol": symbol,
            "side": "sell",
            "execution_profile": execution(a).id,
            "fee_asset": "USD",
            "quantity": str(qty),
            "limit": str(limit),
            "reserved": "0",
            "version": pos["version"],
            "created_at": self.now,
            "reason": reason,
            "book": frame["raw"],
            "model": self.state["model"],
            "observation": observation_evidence(frame),
        }
        a["pending"][symbol] = order
        self.emit("order_intent", name, order)

    def failure_review(self, name: str, a: dict[str, Any]) -> None:
        equity = D(a["equity"])
        if not a["valuation_fresh"] or equity >= 5 or a["positions"] or a["pending"]:
            return
        if policy(a) != LEGACY_POLICY:
            if a["attempt"]["outcome"] == "open":
                a["attempt"].update(outcome="failed", ended_at=self.now)
                a["attempt_failures"] += 1
                self.emit("attempt_failed", name, dict(a["attempt"]))
                self.emit(
                    "failure_review",
                    name,
                    {
                        "attempt": dict(a["attempt"]),
                        "risk_policy": policy(a),
                        "equity_before": a["equity"],
                        "funding": a["funding"],
                        "action": "Attempt ended; losses retained. No top-up or new loss budget.",
                    },
                )
            return
        recent = a["recent_trades"][-50:]
        reasons: dict[str, int] = {}
        for trade in recent:
            reasons[trade["reason"]] = reasons.get(trade["reason"], 0) + 1
        review = {
            "attempt": a["attempt"],
            "equity_before": str(equity),
            "net_pnl_lifetime": str(equity - D(a["funding"])),
            "fees_lifetime": a["fees"],
            "recent_trade_count": len(recent),
            "exit_reasons": reasons,
            "observations": "Capital fell below $5 after costs. Losses and funding retained.",
            "hypothesis": "Repeated failed breakouts or execution costs may be contributing; "
            "this observation alone does not establish a cause.",
            "action": "Use selective-v1 in primary; pause entries for one hour; "
            "continue forward candidate evaluation without increasing risk.",
            "previous_version": a["version"],
            "data_gaps": self.state["gaps"],
            "last_futures_context": self.state.get("futures_context", {}),
            "context_caveat": "Last recorded venue sample; inspect timestamps. No causal finding.",
        }
        self.emit("failure_review", name, review)
        if a["attempt"]["outcome"] == "open":
            a["attempt_failures"] += 1
            self.emit("attempt_failed", name, {**a["attempt"], "ended_at": self.now})
        injection = D(100) - equity
        # Unitized drawdown retains the effect of prior losses across cash injections.
        nav = equity / D(a["units"])
        if nav > 0:
            a["units"] = str(D(a["units"]) + injection / nav)
        else:
            a["max_drawdown"] = "1"
            a["economics_nav_unavailable"] = True
        a["cash"] = "100"
        a["funding"] = str(D(a["funding"]) + injection)
        a["equity"] = "100"
        a["replenishments"] += 1
        a["risk_peak"] = "100"
        a["day_start"] = "100"
        a["day_turnover"] = "0"
        a["drawdown_pause"] = False
        a["daily_pause"] = False
        a["failure_pending"] = False
        a["cooldown_until"] = self.now + 3600
        a["attempt"] = {
            "number": a["attempt"]["number"] + 1,
            "started_at": self.now,
            "outcome": "open",
        }
        if name == "primary":
            a["version"] = "selective-v1"
        self.emit(
            "replenishment",
            name,
            {
                "amount": str(injection),
                "equity_before": str(equity),
                "equity_after": "100",
                "total_funding": a["funding"],
                "attempt": a["attempt"]["number"],
                "review_completed": True,
                "cooldown_until": a["cooldown_until"],
            },
            [self.line("USD", "cash", injection), self.line("USD", "fake_funding", -injection)],
        )

    def review(self) -> None:
        """Two nonoverlapping, fully observed windows; frozen challengers and no forced changes."""
        # Only prospective, already closed account windows; old reviews stay immutable.
        windows = self.state.get("economics", {}).get("completed", [])[-2:]
        primary = self.state["accounts"]["primary"]
        incumbent = primary["version"]
        candidates = []
        rejections = {}
        for version in VARIANTS:
            if version == incumbent:
                continue
            reason = "Two complete aligned account windows are required"
            if len(windows) == 2 and windows[0]["start"] >= self.state["last_promotion"]:
                reason = ""
                for window in windows:
                    score = window["scores"].get(version)
                    base = window["scores"].get(incumbent)
                    if not score or not base or not score["eligible"] or not base["eligible"]:
                        reason = "Account/benchmark coverage is incomplete; retain version"
                        break
                    if any(
                        score[k] != base[k]
                        for k in (
                            "execution_profile",
                            "starting_capital",
                            "funding_basis",
                            "risk_policy",
                            "operating_daily_usd",
                        )
                    ):
                        reason = "Capital, cost or risk assumptions do not match"
                        break
                    if (
                        score["execution_profile"]
                        != primary.get("execution_profile", LEGACY_EXECUTION)
                        or score["starting_capital"] != primary.get("starting_capital", "100")
                        or score["funding_basis"] != primary["funding"]
                        or score["risk_policy"] != policy(primary)
                        or score["operating_daily_usd"] != primary.get("operating_daily_usd")
                    ):
                        reason = "Primary account assumptions do not match the comparison"
                        break
                    if score["total_pnl"] is None or base["total_pnl"] is None:
                        reason = "Set operating-cost assumptions; total economics are unknown"
                        break
                    if D(score["funding_change"]) or D(base["funding_change"]):
                        reason = (
                            "Funding-adjusted results retained; funding changed, so no promotion"
                        )
                        break
                    if not (
                        D(score["total_pnl"]) > 0
                        and D(score["total_return"])
                        > max(
                            D(base["total_return"]) + D("0.001"),
                            D(score["cash_total_return"]),
                            D(score["exposure_total_return"]),
                        )
                        and D(score["max_drawdown"]) <= min(D("0.35"), D(base["max_drawdown"]))
                    ):
                        reason = "No whole-account advantage after costs and benchmarks"
                        break
                if not reason:
                    candidates.append(version)
            rejections[version] = reason or "Passed both observed windows; not profitability proof"
        selected = incumbent
        reason = "Retain version; no matched whole-account challenger qualified"
        if candidates and not primary["positions"] and not primary["pending"]:
            selected = max(
                candidates,
                key=lambda v: math.prod(
                    (1 + D(w["scores"][v]["total_return"]) for w in windows), start=D(1)
                ),
            )
            primary["version"] = selected
            self.state["last_promotion"] = self.now
            self.state["promotion_count"] += 1
            reason = "Challenger passed two whole-account windows; paper-only change while flat"
        risk_resumed = []
        for name, a in self.state["accounts"].items():
            if (
                policy(a) == LEGACY_POLICY
                and a["drawdown_pause"]
                and a["valuation_fresh"]
                and not a["failure_pending"]
            ):
                risk_resumed.append(
                    {
                        "account": name,
                        "old_peak": a["risk_peak"],
                        "new_peak": a["equity"],
                        "lifetime_dd": a["max_drawdown"],
                    }
                )
                a["risk_peak"] = a["equity"]
                a["drawdown_pause"] = False
                a["cooldown_until"] = max(a["cooldown_until"], self.now + 600)
        result = {
            "at": self.now,
            "reason": reason,
            "incumbent": incumbent,
            "selected": selected,
            "windows": windows,
            "evaluation": "whole-account-v1",
            "candidate_reasons": rejections,
            "risk_segments_reviewed": risk_resumed,
            "primary_closed_trades": primary["closed"],
            "primary_net_pnl": str(D(primary["equity"]) - D(primary["funding"])),
            "missed_intervals": max(
                0, int((self.now - self.state["next_review"]) // REVIEW_SECONDS)
            ),
            "limitation": "Correlated shadow runs; selection is not repeatability proof",
        }
        result["universe_comparison"] = {
            name: {
                "started_at": a["attempt"]["started_at"],
                "equity": a["equity"],
                "net_pnl": str(D(a["equity"]) - D(a["funding"])),
                "closed": a["closed"],
                "funding": a["funding"],
                "won": a["attempt_wins"],
                "failed": a["attempt_failures"],
                "max_drawdown": a["max_drawdown"],
            }
            for name, a in self.state["accounts"].items()
            if name.startswith("universe-")
        }
        result["futures_context"] = {
            "window": self.state.get("futures_context_window", {}),
            "coverage": "Kraken linear perpetuals only; liquidation feed not connected",
            "conclusion": (
                "Descriptive observations only; no proven predictive effect or strategy change"
            ),
        }
        self.state.pop("futures_context_window", None)
        self.emit("scheduled_review", "primary", result)
        self.state["review_count"] += 1
        self.state["last_review"] = self.now
        self.state["next_review"] = self.now + REVIEW_SECONDS
        self.state["review_history"] = (self.state["review_history"] + [result])[-12:]

    def campaign_frames(self, frames: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """One durable causal gate also protects CP2's shared comparison controls."""
        marks = self.state.setdefault("campaign_observation_watermarks", {})
        accepted = dict(frames)
        for symbol in SYMBOLS:
            frame = frames.get(symbol)
            if not frame or not fresh_frame(frame, self.now):
                accepted.pop(symbol, None)
                continue
            stamp, sequence = frame["observed"], frame["book"].update_id
            digest = hashlib.sha256(json.dumps(frame["raw"], sort_keys=True).encode()).hexdigest()
            previous = marks.get(symbol)
            if previous and (
                stamp < previous["observed"]
                or sequence < previous["sequence"]
                or (sequence == previous["sequence"] and digest != previous["sha256"])
            ):
                accepted.pop(symbol, None)
                continue
            marks[symbol] = {"observed": stamp, "sequence": sequence, "sha256": digest}
        return accepted

    def tick_account(
        self, name: str, a: dict[str, Any], frames: dict[str, dict[str, Any]], study: dict[str, Any]
    ) -> None:
        diagnostic = is_performance_diagnostic(a, name)
        if diagnostic:
            from trading.paper_diagnostics import prepare_tick

            prepare_tick(self, a)
        stop_before = a.get("risk_stop_id", 0)
        self.value(a, frames)
        for symbol in list(a["pending"]):
            if a["pending"][symbol].get("uncertain") or a.get("execution_uncertain"):
                continue  # Unknown execution cannot become cancelled/free capacity.
            frame = frames.get(symbol)
            reason = entry_reason(a, self.state["paused"], self.now)
            if a["pending"][symbol]["side"] == "buy" and reason:
                self.cancel(name, a, symbol, reason)
                continue
            if self.now - a["pending"][symbol]["created_at"] > 15:
                self.cancel(name, a, symbol, "Expired across data gap or restart")
            elif frame and fresh_frame(frame, self.now):
                self.fill(name, a, symbol, frame, frames)
        fresh = self.value(a, frames)
        if fresh and D(a["equity"]) < 5:
            a["failure_pending"] = True
            for symbol, order in list(a["pending"].items()):
                if order["side"] == "buy":
                    self.cancel(name, a, symbol, "Account failure; entry cancelled")
        if (
            not diagnostic and fresh and D(a["equity"]) >= 1000
            and a["attempt"]["outcome"] == "open"
        ):
            a["attempt"]["outcome"] = "won"
            a["attempt"]["ended_at"] = self.now
            a["attempt_wins"] += 1
            self.emit(
                "attempt_won", name, {**a["attempt"], "equity": a["equity"], "target": "1000"}
            )
        for symbol in list(a["positions"]):
            frame = frames.get(symbol)
            if frame and fresh_frame(frame, self.now):
                feature = study.get(symbol, {}).get(a["positions"][symbol]["version"], {})
                self.exit_position(name, a, symbol, frame, feature)
        if a["failure_pending"] and not diagnostic:
            self.failure_review(name, a)
        if a.get("risk_stop_id", 0) != stop_before:
            self.emit(
                "drawdown_stop",
                name,
                {
                    "stop_id": a["risk_stop_id"],
                    "risk_policy": policy(a),
                    "equity": a["risk_stopped_equity"],
                    "risk_reference": a["risk_stopped_reference"],
                },
            )
        if diagnostic:
            from trading.paper_diagnostics import tick_diagnostic

            tick_diagnostic(self, a, frames, study)
            return
        if not fresh:
            return
        for symbol in a.get("symbols", SYMBOLS):
            frame = frames.get(symbol)
            feature = study.get(symbol, {}).get(a["version"])
            if not frame or not feature or not fresh_frame(frame, self.now):
                continue
            bar_id = feature.get("bar_open_ms")
            last_bar = a["last_decision"].get(symbol, {}).get("bar")
            if bar_id is None or (last_bar is not None and bar_id <= last_bar):
                continue
            if self.evidence_trace is not None:
                self.evidence_trace.append(
                    {
                        "phase": "decision_evaluation_start",
                        "account": name,
                        "symbol": symbol,
                        "mono": time.monotonic(),
                    }
                )
            reason = self.enter(name, a, symbol, frame, feature)
            decision = {
                "symbol": symbol,
                "bar": bar_id,
                "at": self.now,
                "version": a["version"],
                "reason": reason,
                "features": feature,
            }
            a["last_decision"][symbol] = decision
            self.emit("decision", name, decision)

    def tick(
        self, frames: dict[str, dict[str, Any]], study: dict[str, Any], *,
        diagnostic_allowed: bool = True,
    ) -> None:
        self.diagnostic_allowed = diagnostic_allowed
        if self.now < self.state["last_tick"]:
            return  # A delayed dispatcher cannot rewind the durable financial clock.
        if self.state.get("campaigns"):
            frames = self.campaign_frames(frames)
        gap = self.now - self.state["last_tick"]
        if gap > 30:
            self.state["gaps"] += 1
            self.emit(
                "observation_gap",
                "system",
                {"seconds": gap, "note": "No simulated fills invented inside the gap"},
            )
        self.state["last_tick"] = self.now
        self.state["features"] = study
        for name, a in self.state["accounts"].items():
            if not a.get("campaign_id") and not is_performance_diagnostic(a, name):
                self.tick_account(name, a, frames, study)
                continue
            # Existing financial corruption must still stop the writer. Only the
            # proposed work of a valid account can be rolled back independently.
            self.assert_account(a)
            if a.get("fault"):
                continue
            saved, offset = deepcopy(a), len(self.events)
            try:
                self.tick_account(name, a, frames, study)
                self.assert_account(a)
            except (ValueError, KeyError, ArithmeticError) as exc:
                self.events[offset:] = []
                saved["fault"] = {
                    "at": self.now,
                    "code": type(exc).__name__,
                    "reason": "Account step rolled back. Inspect data and retry recovery.",
                }
                saved["valuation_fresh"] = False
                saved["control_version"] = saved.get("control_version", 0) + 1
                saved.pop("last_control", None)
                if is_performance_diagnostic(saved, name):
                    diagnostic = saved.get("diagnostic", {})
                    run = diagnostic.get("runs", {}).get(diagnostic.get("active_request_id"))
                    if run:
                        run.update(
                            status="faulted", reason="Diagnostic step rolled back; inspect recovery"
                        )
                self.state["accounts"][name] = saved
                self.emit("account_fault", name, dict(saved["fault"]))
        for observation in observe_economics(self.state, frames, self.now):
            self.emit(observation["kind"], "system", observation["body"])
        if self.state.get("autonomous_lab"):
            from trading.autonomous_finance import observe

            observe(self, frames)
        if self.now >= self.state["next_review"]:
            self.review()
        minute = int(self.now // 60)
        if minute != self.state["last_snapshot_minute"]:
            self.state["last_snapshot_minute"] = minute
            for name, a in self.state["accounts"].items():
                self.emit(
                    "equity",
                    name,
                    {
                        k: a[k]
                        for k in (
                            "equity",
                            "cash",
                            "funding",
                            "max_drawdown",
                            "valuation_fresh",
                            "version",
                        )
                    },
                )
        self.assert_invariants()

    def set_economics(
        self, name: str, profile: str, daily_usd: str | None, expected_version: int
    ) -> dict[str, Any]:
        a = self.state["accounts"][name]
        if a.get("campaign_id"):
            raise ValueError("Campaign strategy and cost assumptions are frozen at launch")
        if profile not in PROFILES:
            raise ValueError("Select a supported paper fee scenario")
        if daily_usd is not None:
            rate = D(daily_usd)
            if not rate.is_finite() or rate < 0 or rate > 10000:
                raise ValueError("Daily operating allocation must be between 0 and 10000 USD")
            daily_usd = format(rate.normalize(), "f")
        if execution(a).id == profile and a.get("operating_daily_usd") == daily_usd:
            return {"status": "already_applied"}
        if a.get("economics_settings_version", 0) != expected_version:
            raise ValueError("Cost assumptions changed; refresh before saving")
        if execution(a).id != profile and (a["positions"] or a["pending"]):
            raise ValueError(
                "A new execution profile requires a flat account with no pending orders"
            )
        previous = {
            "execution_profile": execution(a).id,
            "operating_daily_usd": a.get("operating_daily_usd"),
        }
        a["execution_profile"] = profile
        a["operating_daily_usd"] = daily_usd
        a["economics_settings_version"] = expected_version + 1
        self.emit(
            "economics_settings",
            name,
            {
                "previous": previous,
                "selected": {"execution_profile": profile, "operating_daily_usd": daily_usd},
                "version": expected_version + 1,
                "reason": "Prospective paper assumptions only; no historical fees or funds changed",
            },
        )
        return {"status": "applied", "version": expected_version + 1}

    def adopt_hard_stop(self, name: str) -> dict[str, Any]:
        a = self.state["accounts"][name]
        if policy(a) == HARD_STOP_POLICY:
            return {"status": "already_applied"}
        if policy(a) != LEGACY_POLICY:
            raise ValueError("Unknown policy; no risk permission was changed.")
        for symbol, order in list(a["pending"].items()):
            if order["side"] == "buy":
                self.cancel(name, a, symbol, "Operator adopted hard-stop policy; re-evaluate entry")
        a["risk_policy"] = HARD_STOP_POLICY
        if a["drawdown_pause"] and not a.get("risk_stop_id"):
            a["risk_stop_id"] = 1
            a["risk_stopped_at"] = self.now
        self.emit(
            "risk_policy_changed",
            name,
            {
                "previous": LEGACY_POLICY,
                "selected": HARD_STOP_POLICY,
                "risk_reference": a["risk_peak"],
                "funding": a["funding"],
                "reason": "Operator selected hard stops and no top-ups; history retained.",
            },
        )
        return {"status": "applied"}

    def recover_hard_stop(self, name: str, stop_id: int) -> dict[str, Any]:
        a = self.state["accounts"][name]
        if stop_id < 1 or stop_id != a.get("risk_stop_id"):
            raise ValueError("The stop changed; refresh the account before recovering.")
        last = a.get("risk_recovery")
        if not a["drawdown_pause"] and last and last["stop_id"] == stop_id:
            return {"status": "already_applied", "stop_id": stop_id}
        reason = recovery_reason(a, self.now)
        if self.state["paused"] or a.get("entries_paused") or a.get("fault"):
            reason = "Clear the operator pause first; the loss limit is unchanged."
        if reason:
            raise ValueError(reason)
        a["drawdown_pause"] = False
        a["risk_recovery"] = {
            "stop_id": stop_id,
            "at": self.now,
            "equity": a["equity"],
            "risk_reference": a["risk_peak"],
            "reason": "Operator resumed above the original loss limit; no funds or budget added.",
        }
        self.emit("risk_recovered", name, dict(a["risk_recovery"]))
        return {"status": "recovered", "stop_id": stop_id}

    @staticmethod
    def assert_account(a: dict[str, Any]) -> None:
        reserve = sum((D(o["reserved"]) for o in a["pending"].values()), D(0))
        if D(a["cash"]) < 0 or reserve < 0 or reserve > D(a["cash"]):
            raise ValueError("Cash conservation or reservation invariant failed")
        for pos in a["positions"].values():
            if D(pos["quantity"]) <= 0 or D(pos["cost"]) < 0:
                raise ValueError("Inventory invariant failed")

    def assert_invariants(self) -> None:
        for a in self.state["accounts"].values():
            self.assert_account(a)
        if self.state.get("autonomous_lab"):
            from trading.autonomous_finance import slots

            if slots(self.state)["used"] > self.state["autonomous_lab"]["policy"]["slots"]:
                raise ValueError("Concurrent managed/reserved lab capacity exceeded")
