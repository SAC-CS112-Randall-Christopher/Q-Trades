"""Isolated long-options historical simulation and bounded, prospective learning."""

from collections import Counter
from datetime import datetime
from decimal import Decimal as D
from typing import Any

from trading.options_policy import (
    FEE,
    MODEL,
    REVIEW_SECONDS,
    RISK,
    SOURCE,
    VARIANTS,
    dec,
    qualify,
    quote_valid,
    signal,
)
from trading.paper_engine import PaperEngine


def account(version: str) -> dict[str, Any]:
    return {
        "version": version,
        "cash": "100",
        "funding": "100",
        "fees": "0",
        "equity": "100",
        "peak": "100",
        "max_drawdown": "0",
        "valuation_fresh": True,
        "positions": {},
        "pending": {},
        "unsettled": [],
        "closed": 0,
        "wins": 0,
        "realized": "0",
        "trades": [],
        "attempt_wins": 0,
        "attempt_failures": 0,
        "attempt": 1,
        "attempt_outcome": "open",
        "replenishments": 0,
        "risk_peak": "100",
        "risk_pause": False,
        "cooldown_sessions": 0,
        "last_decision": "Waiting for the first historical session",
    }


def initial_state(now: float) -> dict[str, Any]:
    return {
        "schema": 1,
        "kind": "cash_options_research",
        "model": MODEL,
        "source": SOURCE,
        "mode": "historical_eod_replay",
        "started_at": now,
        "next_review": now + REVIEW_SECONDS,
        "last_review": now,
        "review_count": 0,
        "reviews": [],
        "last_promotion": now,
        "promotions": 0,
        "market_day": None,
        "sessions": 0,
        "contracts_studied": 0,
        "history": [],
        "paused": False,
        "feed_status": "Waiting for free historical data",
        "accounts": {
            "primary": account("options-momentum-v1"),
            **{v: account(v) for v in VARIANTS},
        },
        "rejections": {},
        "last_study": None,
        "data_gaps": 0,
        "request_budget": {"day": "", "used": 0, "limit": 60},
    }


def reserved(a: dict[str, Any]) -> D:
    return sum((D(o.get("reserved", "0")) for o in a["pending"].values()), D(0)) + sum(
        (D(p["exit_reserve"]) for p in a["positions"].values()), D(0)
    )


class OptionsEngine(PaperEngine):
    # Only emit/line mechanics are shared; no spot strategy, account or tick is invoked.
    def seed(self) -> None:
        for name in self.state["accounts"]:
            self.emit(
                "initial_funding",
                name,
                {"amount": "100", "currency": "USD", "mode": "historical_eod_replay"},
                [self.line("USD", "cash", D(100)), self.line("USD", "fake_funding", D(-100))],
            )

    def set_paused(self, paused: bool) -> None:
        self.state["paused"] = paused
        self.emit("entry_control", "primary", {"paused": paused})
        if paused:
            for name, a in self.state["accounts"].items():
                for symbol, order in list(a["pending"].items()):
                    if order["side"] == "buy":
                        self.cancel_order(name, a, symbol, "Operator paused new entries")

    def cancel_order(self, name: str, a: dict[str, Any], symbol: str, reason: str) -> None:
        order = a["pending"].pop(symbol)
        amount = D(order.get("reserved", "0"))
        self.emit(
            "order_cancelled",
            name,
            {"symbol": symbol, "reason": reason, "order": order},
            [self.line("USD", "reserved", -amount), self.line("USD", "cash", amount)]
            if amount
            else [],
        )

    def mark_account(self, a: dict[str, Any], quotes: dict[str, Any], day: str) -> None:
        value = D(a["cash"]) + sum((D(x["amount"]) for x in a["unsettled"]), D(0))
        fresh = True
        for symbol, p in a["positions"].items():
            q = quotes.get(symbol, {})
            if quote_valid(q, day) and dec(q["bid"]) > 0 and dec(q["bid_size"]) >= 10:
                p["last_value"] = str(dec(q["bid"]) * 100 - FEE)
                p["mark_day"] = day
            else:
                fresh = False
            value += D(p["last_value"])
        a["equity"], a["valuation_fresh"] = str(value), fresh
        if fresh:
            a["peak"] = str(max(D(a["peak"]), value))
            a["risk_peak"] = str(max(D(a["risk_peak"]), value))
            drawdown = 1 - value / D(a["peak"])
            a["max_drawdown"] = str(max(D(a["max_drawdown"]), drawdown))
            if value <= D(a["risk_peak"]) * D("0.65"):
                a["risk_pause"] = True

    def settle_cash(self, name: str, a: dict[str, Any], day: str) -> None:
        remaining = []
        for item in a["unsettled"]:
            if item["trade_day"] < day:
                amount = D(item["amount"])
                a["cash"] = str(D(a["cash"]) + amount)
                self.emit(
                    "cash_settled",
                    name,
                    {
                        **item,
                        "settled_on": day,
                        "model": "Next observed trading session; no T+0 reuse",
                    },
                    [self.line("USD", "unsettled", -amount), self.line("USD", "cash", amount)],
                )
            else:
                remaining.append(item)
        a["unsettled"] = remaining

    def fill_pending(self, name: str, a: dict[str, Any], quotes: dict[str, Any], day: str) -> None:
        for symbol, order in list(a["pending"].items()):
            if day <= order["created_day"]:
                continue
            q = quotes.get(symbol, {})
            # One chance at the NEXT replayed session. No retroactive fill on an old snapshot.
            if not quote_valid(q, day) or day >= q["expiration_date"]:
                self.cancel_order(name, a, symbol, "Next-session executable quote unavailable")
                continue
            if order["side"] == "buy":
                price = dec(q["ask"])
                risk = price * 100 + 2 * FEE
                if (
                    price > D(order["limit"])
                    or dec(q["ask_size"]) < 10
                    or qualify(q, day, order["version"]) is not None
                    or risk > D(order["risk_budget"])
                    or risk > D(a["equity"]) * RISK
                    or self.state["paused"]
                    or a["risk_pause"]
                    or a["cooldown_sessions"]
                ):
                    self.cancel_order(
                        name, a, symbol, "Price, liquidity or risk changed before fill"
                    )
                    continue
                cost = price * 100 + FEE
                reserve = D(order["reserved"])
                a["cash"] = str(D(a["cash"]) - cost)
                a["fees"] = str(D(a["fees"]) + FEE)
                a["positions"][symbol] = {
                    "quantity": "1",
                    "cost": str(cost),
                    "entry": str(price),
                    "entry_day": day,
                    "entry_sequence": self.state["sessions"],
                    "expiry": q["expiration_date"],
                    "side": q["side"],
                    "version": order["version"],
                    "exit_reserve": str(FEE),
                    "last_value": str(dec(q["bid"]) * 100 - FEE),
                    "mark_day": day,
                    "entry_evidence": q,
                }
                self.emit(
                    "fill",
                    name,
                    {
                        "side": "buy",
                        "symbol": symbol,
                        "quantity": "1",
                        "price": str(price),
                        "fee": str(FEE),
                        "market_day": day,
                        "observation": q,
                        "order": order,
                    },
                    [
                        self.line("USD", "reserved", -reserve),
                        self.line("USD", "reserved", FEE),
                        self.line("USD", "cash", reserve - cost - FEE),
                        self.line("USD", "premium", price * 100),
                        self.line("USD", "fees", FEE),
                        self.line(symbol, "inventory", D(1)),
                        self.line(symbol, "venue", D(-1)),
                    ],
                )
                del a["pending"][symbol]
            else:
                if dec(q["bid"]) <= 0 or dec(q["bid_size"]) < 10:
                    self.cancel_order(name, a, symbol, "No visible liquidation liquidity")
                    continue
                self.close_position(name, a, symbol, day, dec(q["bid"]) * 100, order["reason"], q)

    def close_position(
        self,
        name: str,
        a: dict[str, Any],
        symbol: str,
        day: str,
        gross: D,
        reason: str,
        evidence: dict[str, Any],
    ) -> None:
        p = a["positions"].pop(symbol)
        a["pending"].pop(symbol, None)
        fee = FEE
        exit_reserve = D(p["exit_reserve"])
        a["cash"] = str(D(a["cash"]) - fee)
        a["fees"] = str(D(a["fees"]) + fee)
        if gross:
            a["unsettled"].append({"amount": str(gross), "trade_day": day, "symbol": symbol})
        pnl = gross - fee - D(p["cost"])
        a["closed"] += 1
        a["wins"] += int(pnl > 0)
        a["realized"] = str(D(a["realized"]) + pnl)
        trade = {
            "symbol": symbol,
            "opened": p["entry_day"],
            "closed": day,
            "sequence": self.state["sessions"],
            "opened_sequence": p["entry_sequence"],
            "pnl": str(pnl),
            "return": str(pnl / (D(p["cost"]) + fee)),
            "version": p["version"],
            "reason": reason,
            "fees": str(2 * FEE),
        }
        a["trades"] = (a["trades"] + [trade])[-1000:]
        self.emit(
            "trade_closed",
            name,
            {
                **trade,
                "gross": str(gross),
                "exit_evidence": evidence,
                "entry_evidence": p["entry_evidence"],
                "mode": "historical_eod_replay",
            },
            [
                self.line("USD", "reserved", -exit_reserve),
                self.line("USD", "cash", exit_reserve - fee),
                self.line("USD", "unsettled", gross),
                self.line("USD", "sale_proceeds", -gross),
                self.line("USD", "fees", fee),
                self.line(symbol, "inventory", D(-1)),
                self.line(symbol, "venue", D(1)),
            ],
        )

    def entries(
        self,
        name: str,
        a: dict[str, Any],
        quotes: dict[str, Any],
        day: str,
        feature: dict[str, Any],
    ) -> None:
        if (
            self.state["paused"]
            or a["risk_pause"]
            or a["cooldown_sessions"]
            or not a["valuation_fresh"]
        ):
            a["last_decision"] = (
                "Entries paused by operator, risk, cooldown or incomplete valuation"
            )
            return
        if a["positions"] or a["pending"]:
            a["last_decision"] = "One position at a time; managing current exposure"
            return
        if not feature["eligible"]:
            a["last_decision"] = feature["reason"]
            return
        reasons: Counter[str] = Counter()
        affordable = []
        budget = min(D(a["equity"]) * RISK, D(a["cash"]) - reserved(a))
        for q in quotes.values():
            if q.get("side") != feature["direction"]:
                continue
            reason = qualify(q, day, a["version"])
            if reason:
                reasons[reason] += 1
                continue
            cost = dec(q["ask"]) * 100 + 2 * FEE
            if cost > budget:
                reasons["Full premium plus fees exceeds the 2.5% risk/settled-cash budget"] += 1
                continue
            affordable.append(q)
        if not affordable:
            a["last_decision"] = (
                reasons.most_common(1)[0][0] if reasons else "No matching option contracts"
            )
            if name == "primary":
                totals = Counter(self.state["rejections"])
                totals.update(reasons)
                self.state["rejections"] = dict(totals)
            return
        # Fixed liquidity ranking, not fitted to the next session's return.
        q = min(
            affordable,
            key=lambda x: (
                (dec(x["ask"]) - dec(x["bid"])) / dec(x["ask"]),
                -dec(x["volume"]),
                x["symbol"],
            ),
        )
        reserve = dec(q["ask"]) * 100 + 2 * FEE
        order = {
            "side": "buy",
            "symbol": q["symbol"],
            "quantity": "1",
            "limit": q["ask"],
            "reserved": str(reserve),
            "risk_budget": str(budget),
            "created_day": day,
            "version": a["version"],
            "feature": feature,
            "observation": q,
            "model": MODEL,
        }
        a["pending"][q["symbol"]] = order
        a["last_decision"] = "Entry intent recorded; requires a later session quote"
        self.emit(
            "order_intent",
            name,
            order,
            [self.line("USD", "cash", -reserve), self.line("USD", "reserved", reserve)],
        )

    def process_session(self, packet: dict[str, Any]) -> None:
        day = packet["day"]
        if packet["source"] != SOURCE or not packet["receipts"]:
            raise ValueError("Historical source evidence required")
        datetime.fromisoformat(day)
        if self.state["market_day"] and day <= self.state["market_day"]:
            raise ValueError("Historical replay cannot repeat or move backward")
        quotes = packet["quotes"]
        if not quotes or len(quotes) > 1000:
            raise ValueError("Missing or oversized historical session")
        self.state["sessions"] += 1
        self.state["contracts_studied"] += len(quotes)
        self.state["market_day"] = day
        self.state["history"] = (
            self.state["history"]
            + [{"day": day, "close": str(dec(packet["underlying_close"], "0.01"))}]
        )[-64:]
        features = {v: signal(self.state["history"], v) for v in VARIANTS}
        self.state["feed_status"] = "Studying actual historical end-of-day quotes; not a live feed"
        for name, a in self.state["accounts"].items():
            before = D(a["equity"])
            self.settle_cash(name, a, day)
            self.mark_account(a, quotes, day)
            self.fill_pending(name, a, quotes, day)
            for symbol, p in list(a["positions"].items()):
                # Expiry is NOT treated as an affordable automatic stock exercise.
                # Unknown exercise/settlement remains unresolved; never invent a cash payout.
                if day >= p["expiry"]:
                    p["exit_blocked"] = "Expiry requires verified disposition; account frozen"
                    a["risk_pause"] = True
                    continue
                days_left = (datetime.fromisoformat(p["expiry"]) - datetime.fromisoformat(day)).days
                held = self.state["sessions"] - p["entry_sequence"]
                q = quotes.get(symbol, {})
                reason = None
                if days_left <= 5:
                    reason = "Exit ahead of expiry"
                elif held >= 5:
                    reason = "Five-session holding limit"
                elif quote_valid(q, day):
                    ratio = (dec(q["bid"]) * 100 - FEE) / D(p["cost"])
                    if ratio <= D("0.60"):
                        reason = "End-of-day loss threshold"
                    elif ratio >= D("1.80"):
                        reason = "End-of-day profit threshold"
                if reason and symbol not in a["pending"]:
                    order = {
                        "side": "sell",
                        "symbol": symbol,
                        "created_day": day,
                        "reserved": "0",
                        "reason": reason,
                        "version": p["version"],
                    }
                    a["pending"][symbol] = order
                    self.emit("order_intent", name, order)
            self.mark_account(a, quotes, day)
            if any(p.get("exit_blocked") for p in a["positions"].values()):
                a["valuation_fresh"] = False
            if a["valuation_fresh"] and D(a["equity"]) <= before * D("0.85"):
                a["cooldown_sessions"] = max(1, a["cooldown_sessions"])
            self.attempts(name, a)
            self.entries(name, a, quotes, day, features[a["version"]])
            if a["cooldown_sessions"]:
                a["cooldown_sessions"] -= 1
        summary = {
            "day": day,
            "contracts": len(quotes),
            "features": features,
            "primary_decision": self.state["accounts"]["primary"]["last_decision"],
            "greeks": "Historical Greeks/IV absent; no fabricated estimates",
            "source": SOURCE,
        }
        self.state["last_study"] = summary
        self.emit("historical_session", "system", {**summary, "receipts": packet["receipts"]})

    def attempts(self, name: str, a: dict[str, Any]) -> None:
        if not a["valuation_fresh"]:
            return
        equity = D(a["equity"])
        if equity >= 1000 and a["attempt_outcome"] == "open":
            a["attempt_wins"] += 1
            a["attempt_outcome"] = "won"
            self.emit(
                "attempt_won",
                name,
                {"attempt": a["attempt"], "equity": str(equity), "mode": "historical_replay_only"},
            )
        if equity >= 5 or a["positions"] or a["pending"] or a["unsettled"]:
            return
        self.emit(
            "failure_review",
            name,
            {
                "attempt": a["attempt"],
                "equity": str(equity),
                "funding": a["funding"],
                "fees": a["fees"],
                "recent_trades": a["trades"][-20:],
                "action": "Retain losses; use the fixed selective policy and skip one session",
                "causality": "Observed outcomes, not proof that a cause has been identified",
            },
        )
        a["attempt_failures"] += int(a["attempt_outcome"] != "won")
        amount = 100 - equity
        a["cash"], a["equity"], a["risk_peak"] = "100", "100", "100"
        a["funding"] = str(D(a["funding"]) + amount)
        a["replenishments"] += 1
        a["attempt"] += 1
        a["attempt_outcome"] = "open"
        a["risk_pause"] = False
        a["cooldown_sessions"] = 1
        if name == "primary":
            a["version"] = "options-selective-v1"
        self.emit(
            "replenishment",
            name,
            {"amount": str(amount), "total_funding": a["funding"]},
            [self.line("USD", "cash", amount), self.line("USD", "fake_funding", -amount)],
        )

    def review(self) -> None:
        primary = self.state["accounts"]["primary"]
        selected = primary["version"]
        reason = "Insufficient distinct forward replay outcomes; retain current policy"
        evidence: dict[str, Any] = {}
        boundary = self.state["sessions"]
        for version in VARIANTS:
            trades = self.state["accounts"][version]["trades"]
            windows = [
                [t for t in trades if low < t["opened_sequence"] <= t["sequence"] <= high]
                for low, high in ((boundary - 40, boundary - 20), (boundary - 20, boundary))
            ]
            evidence[version] = [
                {
                    "trades": len(w),
                    "net": str(sum((D(t["pnl"]) for t in w), D(0))),
                    "stressed_net": str(sum((D(t["pnl"]) - D("0.50") for t in w), D(0))),
                    "mean_return": str(sum((D(t["return"]) for t in w), D(0)) / len(w))
                    if w
                    else None,
                }
                for w in windows
            ]
        incumbent = evidence[selected]
        if (
            self.now - self.state["last_promotion"] >= 2 * REVIEW_SECONDS
            and not primary["positions"]
            and not primary["pending"]
        ):
            for challenger in VARIANTS:
                tests = evidence[challenger]
                if challenger != selected and all(
                    a["trades"] >= 10
                    and b["trades"] >= 10
                    and D(a["stressed_net"]) > 0
                    and D(a["mean_return"]) > D(b["mean_return"])
                    for a, b in zip(tests, incumbent, strict=True)
                ):
                    candidate = self.state["accounts"][challenger]
                    if D(candidate["max_drawdown"]) <= min(D("0.35"), D(primary["max_drawdown"])):
                        selected = challenger
                        self.state["last_promotion"] = self.now
                        self.state["promotions"] += 1
                        reason = "Two prior replay windows passed; apply to later unseen sessions"
                        break
        primary["version"] = selected
        risk_resumed = []
        for name, a in self.state["accounts"].items():
            if (
                a["risk_pause"]
                and a["valuation_fresh"]
                and not any(p.get("exit_blocked") for p in a["positions"].values())
            ):
                risk_resumed.append(
                    {
                        "account": name,
                        "old_peak": a["risk_peak"],
                        "new_peak": a["equity"],
                        "lifetime_drawdown": a["max_drawdown"],
                    }
                )
                a["risk_peak"], a["risk_pause"], a["cooldown_sessions"] = a["equity"], False, 1
        result = {
            "at": self.now,
            "market_day": self.state["market_day"],
            "sessions": boundary,
            "selected": selected,
            "reason": reason,
            "windows": evidence,
            "risk_segments_reviewed": risk_resumed,
            "rejections": dict(self.state["rejections"]),
            "data_gaps": self.state["data_gaps"],
            "scope": "AAPL end-of-day replay; no live execution or independent-attempt proof",
        }
        self.emit("scheduled_review", "primary", result)
        self.state["reviews"] = (self.state["reviews"] + [result])[-12:]
        self.state["review_count"] += 1
        self.state["last_review"], self.state["next_review"] = self.now, self.now + REVIEW_SECONDS

    def assert_invariants(self) -> None:
        for a in self.state["accounts"].values():
            if D(a["cash"]) < reserved(a) or D(a["funding"]) < 100:
                raise ValueError("Options cash/reservation invariant failed")
            if len(a["positions"]) > 1:
                raise ValueError("Options position limit exceeded")
            for p in a["positions"].values():
                if p["quantity"] != "1" or D(p["exit_reserve"]) != FEE:
                    raise ValueError("Only fully paid long single contracts are supported")
            if any(D(x["amount"]) < 0 for x in a["unsettled"]):
                raise ValueError("Negative unsettled proceeds")
