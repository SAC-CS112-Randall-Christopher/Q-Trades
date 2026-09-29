"""Prospective, aligned whole-account observations in existing paper state/journal."""

import copy
import math
from decimal import Decimal as D
from typing import Any

from trading.execution_profiles import LEGACY_EXECUTION, execution, floor_step, walk_book

VERSION = "whole-account-v1"
WINDOW_SECONDS = 4 * 3600
MAX_GAP = 30
BENCHMARK_SYMBOLS = ("BTCUSD", "ETHUSD")


def fresh(at: Any, now: float) -> bool:
    return (
        isinstance(at, (float, int))
        and not isinstance(at, bool)
        and math.isfinite(at)
        and 0 <= now - at <= 5
    )


def sample(a: dict[str, Any], now: float) -> dict[str, Any]:
    valid = a.get("valuation_fresh") is True and fresh(a.get("valuation_at"), now)
    reserve = sum((D(o["reserved"]) for o in a["pending"].values()), D(0))
    basis = sum((D(p["cost"]) for p in a["positions"].values()), D(0))
    equity, cash = D(a["equity"]), D(a["cash"])
    return {
        "equity": str(equity),
        "cash": str(cash),
        "reserved": str(reserve),
        "available_cash": str(cash - reserve),
        "funding": a["funding"],
        "units": a["units"],
        "fees": a["fees"],
        "realized": a["realized"],
        "unrealized": str(equity - cash - basis) if valid else None,
        "net_pnl": str(equity - D(a["funding"])) if valid else None,
        "nav": str(equity / D(a["units"]))
        if valid and D(a["units"]) > 0 and not a.get("economics_nav_unavailable")
        else None,
        "fresh": valid,
        "valuation_at": a.get("valuation_at"),
        "execution_drag": a.get("execution_drag_usd", "0"),
        "liquidation_fee": a.get("liquidation_fee_usd", "0"),
        "liquidation_drag": a.get("liquidation_drag_usd", "0"),
        "execution_profile": a.get("execution_profile", LEGACY_EXECUTION),
        "risk_policy": a.get("risk_policy", "legacy-paper-review-v1"),
        "strategy_version": a["version"],
        "settings_version": a.get("economics_settings_version", 0),
        "operating_daily_usd": a.get("operating_daily_usd"),
        "starting_capital": a.get("starting_capital", "100"),
        "flat": not a["positions"] and not a["pending"],
        "closed": a["closed"],
        "wins": a["wins"],
        "valuation_issues": dict(a.get("valuation_issues", {})),
    }


def new_benchmark(capital: str, profile: str, now: float) -> dict[str, Any]:
    return {
        "capital": capital,
        "cash": capital,
        "execution_profile": profile,
        "start": now,
        "fees": "0",
        "legs": {s: {"status": "waiting"} for s in BENCHMARK_SYMBOLS},
        "equity": capital,
        "fresh": True,
        "coverage": True,
        "peak": capital,
        "drawdown": "0",
    }


def benchmark_tick(b: dict[str, Any], frames: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """50/50 BTC/ETH buy-once control; no spendable funds or financial accounts created."""
    receipts = []
    profile = execution(b)
    for symbol, leg in b["legs"].items():
        f = frames.get(symbol)
        usable = f is not None and fresh(f.get("observed"), now)
        if leg["status"] in {"waiting", "pending"}:
            if now - b["start"] > profile.expiry_seconds:
                leg["status"] = "expired without fill"
                b["coverage"] = False
                continue
            if f is None or not usable or not f.get("entry_allowed", True):
                continue
            rules, book = f["rules"], f["book"]
            fee = profile.fee(symbol)
            if leg["status"] == "waiting":
                limit = floor_step(book.asks[0][0] * D("1.001"), rules["tick"])
                qty = floor_step(
                    min(D(b["capital"]) / 2 / (limit * (1 + fee)), rules["max_qty"]), rules["step"]
                )
                if qty < rules["min_qty"] or qty * limit < rules["min_notional"]:
                    leg["status"] = "cash: below minimum"
                elif not rules["min_price"] <= limit <= rules["max_price"]:
                    leg["status"] = "cash: invalid price"
                else:
                    leg.update(
                        status="pending", created_at=now, limit=str(limit), quantity=str(qty)
                    )
                continue  # No same-observation intent and fill.
            if (
                now < leg["created_at"] + profile.latency_seconds
                or f["observed"] <= leg["created_at"]
            ):
                continue
            qty, limit = D(leg["quantity"]), D(leg["limit"])
            if (
                qty != floor_step(qty, rules["step"])
                or not rules["min_qty"] <= qty <= rules["max_qty"]
                or limit != floor_step(limit, rules["tick"])
                or qty * limit < rules["min_notional"]
                or not rules["min_price"] <= limit <= rules["max_price"]
            ):
                leg["status"] = "cash: filters changed"
                continue
            filled, gross = walk_book(book, "buy", qty, limit, rules, profile)
            cost = gross * (1 + fee)
            if cost > D(b["cash"]):
                raise ValueError("Benchmark cannot exceed its own hypothetical cash")
            b["cash"] = str(D(b["cash"]) - cost)
            b["fees"] = str(D(b["fees"]) + gross * fee)
            leg.update(status="held" if filled else "cash: no fill", quantity=str(filled))
            receipts.append(
                {
                    "symbol": symbol,
                    "quantity": str(filled),
                    "fee": str(gross * fee),
                    "unfilled_cancelled": str(qty - filled),
                    "gross": str(gross),
                    "observed_at": f["observed"],
                    "book": f["raw"],
                    "instrument": f["instrument"],
                    "execution_profile": profile.id,
                    "fee_asset": "USD",
                    "role": "taker",
                }
            )
    equity = D(b["cash"])
    valid = True
    for symbol, leg in b["legs"].items():
        if leg["status"] != "held":
            continue
        f = frames.get(symbol)
        if f is None or not fresh(f.get("observed"), now):
            valid = False
            continue
        qty, rules = D(leg["quantity"]), f["rules"]
        filled, gross = walk_book(f["book"], "sell", qty, D(0), rules, profile)
        if filled < qty or qty < rules["min_qty"] or gross < rules["min_notional"]:
            valid = False
            continue
        equity += gross * (1 - profile.fee(symbol))
    b["fresh"] = valid
    b["coverage"] = b["coverage"] and valid
    b["observed_at"] = now
    if valid:
        b["equity"] = str(equity)
        b["peak"] = str(max(equity, D(b["peak"])))
        b["drawdown"] = str(max(D(b["drawdown"]), 1 - equity / D(b["peak"])))
    return receipts


def begin(state: dict[str, Any], now: float) -> dict[str, Any]:
    window: dict[str, Any] = {
        "start": now,
        "due": now + WINDOW_SECONDS,
        "last_at": now,
        "gaps": 0,
        "accounts": {},
        "benchmarks": {},
    }
    for name, a in state["accounts"].items():
        s = sample(a, now)
        key = f"{s['execution_profile']}:{s['equity']}"
        if s["fresh"] and D(s["equity"]) > 0:
            window["benchmarks"].setdefault(
                key, new_benchmark(s["equity"], s["execution_profile"], now)
            )
        window["accounts"][name] = {
            "first": s,
            "last": s,
            "valid": s["fresh"],
            "peak_nav": s["nav"],
            "drawdown": "0",
            "benchmark": key,
            "changed_settings": False,
            "observations": 1,
        }
    return window


def scores(window: dict[str, Any], end: float, *, complete: bool) -> dict[str, Any]:
    rows = {}
    for name, row in window["accounts"].items():
        first, last = row["first"], row["last"]
        marked = first["fresh"] and last["fresh"]
        net = D(last["equity"]) - D(first["equity"]) - (D(last["funding"]) - D(first["funding"]))
        flow_return = (
            D(last["nav"]) / D(first["nav"]) - 1
            if marked
            and first["nav"] is not None
            and D(first["nav"]) > 0
            and last["nav"] is not None
            else None
        )
        paid = D(last["fees"]) - D(first["fees"])
        execution_cost = paid + sum(
            (
                D(last[k]) - D(first[k])
                for k in ("execution_drag", "liquidation_fee", "liquidation_drag")
            ),
            D(0),
        )
        daily = first["operating_daily_usd"]
        operating = (
            D(daily) * D(str(max(0, end - window["start"]))) / 86400
            if daily is not None and not row["changed_settings"]
            else None
        )
        bench = window["benchmarks"].get(row["benchmark"])
        bench_return = (
            D(bench["equity"]) / D(bench["capital"]) - 1 if bench and bench["fresh"] else None
        )
        operating_return = (
            operating / D(first["equity"])
            if operating is not None and D(first["equity"]) > 0
            else None
        )
        unchanged_funding = D(last["funding"]) == D(first["funding"])
        total_return = (
            flow_return - operating_return
            if flow_return is not None and operating_return is not None and unchanged_funding
            else None
        )
        reasons = []
        if operating is None:
            reasons.append(
                "Operating allocation is unspecified or changed; total economics are unknown"
            )
        if not complete:
            reasons.append("Window still collecting")
        if not row["valid"] or not marked:
            reasons.append("Missing or uncertain holding marks")
        if flow_return is None:
            reasons.append("Funding-adjusted return unavailable at a zero/unknown unit value")
        if window["gaps"]:
            reasons.append("Observation gap; no unobserved path was invented")
        if D(last["funding"]) != D(first["funding"]):
            reasons.append("External funding changed; unitized return retained, not ranked")
        if row["changed_settings"]:
            reasons.append("Cost, risk or strategy settings changed inside the window")
        if (
            not bench
            or not bench["coverage"]
            or any(v["status"] in {"waiting", "pending"} for v in bench["legs"].values())
        ):
            reasons.append("Simple-exposure benchmark has incomplete observations")
        rows[name] = {
            "available": bool(marked),
            "eligible": not reasons,
            "reasons": reasons,
            "start_equity": first["equity"],
            "end_equity": last["equity"] if last["fresh"] else None,
            "net_pnl": str(net) if marked else None,
            "return": str(flow_return) if flow_return is not None else None,
            "gross_reference_pnl": str(net + execution_cost) if marked else None,
            "execution_cost": str(execution_cost) if marked else None,
            "fees_paid": str(paid),
            "operating_cost": str(operating) if operating is not None else None,
            "total_pnl": str(net - operating) if marked and operating is not None else None,
            "total_return": str(total_return) if total_return is not None else None,
            "cash_total_return": str(-operating_return) if operating_return is not None else None,
            "exposure_total_return": str(bench_return - operating_return)
            if bench_return is not None and operating_return is not None
            else None,
            "cash_return": "0",
            "exposure_return": str(bench_return) if bench_return is not None else None,
            "benchmark_status": {s: v["status"] for s, v in bench["legs"].items()} if bench else {},
            "max_drawdown": row["drawdown"],
            "trades": last["closed"] - first["closed"],
            "wins": last["wins"] - first["wins"],
            "funding_change": str(D(last["funding"]) - D(first["funding"])),
            "funding_basis": first["funding"],
            "starting_capital": first["starting_capital"],
            "execution_profile": first["execution_profile"],
            "risk_policy": first["risk_policy"],
            "operating_daily_usd": daily,
            "cohort": (
                f"{first['starting_capital']} USD / {first['execution_profile']} / "
                f"{first['risk_policy']} / funding {first['funding']} / daily {daily}"
            ),
            "rank": None,
        }
    groups: dict[str, list[dict[str, Any]]] = {}
    for result in rows.values():
        if result["eligible"]:
            groups.setdefault(result["cohort"], []).append(result)
    for group in groups.values():
        for result in group:
            result["rank"] = 1 + sum(
                D(other["total_return"]) > D(result["total_return"]) for other in group
            )
    return {
        "version": VERSION,
        "start": window["start"],
        "end": end,
        "complete": complete,
        "scores": rows,
    }


def observe(state: dict[str, Any], frames: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """Keep current plus two finished windows; full results remain journal events."""
    e = state.setdefault("economics", {"version": VERSION, "started_at": now, "completed": []})
    window = e.get("active")
    if window is None:
        window = e["active"] = begin(state, now)
    gap = now - window["last_at"]
    if gap < 0:
        raise ValueError("Economic observations cannot move backward in time")
    if gap > MAX_GAP:
        window["gaps"] += 1
    window["last_at"] = now
    for name, row in window["accounts"].items():
        if name not in state["accounts"]:
            row["valid"] = False
            continue
        s = sample(state["accounts"][name], now)
        row["last"] = s
        row["observations"] += 1
        row["valid"] = row["valid"] and s["fresh"]
        row["changed_settings"] = row["changed_settings"] or any(
            s[k] != row["first"][k]
            for k in (
                "settings_version",
                "execution_profile",
                "risk_policy",
                "operating_daily_usd",
                "strategy_version",
            )
        )
        if (
            s["nav"] is not None
            and D(s["nav"]) >= 0
            and row["peak_nav"] is not None
            and D(row["peak_nav"]) > 0
        ):
            row["peak_nav"] = str(max(D(s["nav"]), D(row["peak_nav"])))
            row["drawdown"] = str(max(D(row["drawdown"]), 1 - D(s["nav"]) / D(row["peak_nav"])))
    events = []
    for key, b in window["benchmarks"].items():
        for receipt in benchmark_tick(b, frames, now):
            events.append(
                {
                    "kind": "benchmark_fill",
                    "body": {
                        "control": "50/50 BTC/ETH buy-once",
                        "window_start": window["start"],
                        "group": key,
                        **receipt,
                    },
                }
            )
    if now >= window["due"]:
        finished = scores(window, now, complete=True)
        e["completed"] = (e["completed"] + [finished])[-2:]
        events.append({"kind": "economics_window", "body": copy.deepcopy(finished)})
        e["active"] = begin(state, now)
        for b in e["active"]["benchmarks"].values():
            benchmark_tick(b, frames, now)  # New intents only, never same-boundary fills.
    return events


def report(state: dict[str, Any], now: float, running: bool) -> dict[str, Any]:
    e = state.get("economics", {})
    accounts = {name: sample(a, now) for name, a in state["accounts"].items()}
    for name, row in accounts.items():
        row["campaign_id"] = state["accounts"][name].get("campaign_id")
        row["label"] = state["accounts"][name].get("label", name)
    for row in accounts.values():
        if not running:
            row.update(fresh=False, unrealized=None, net_pnl=None, nav=None)
    current = (
        scores(e["active"], e["active"]["last_at"], complete=False) if e.get("active") else None
    )
    if current:
        for row in current["scores"].values():
            if not running or not fresh(e["active"]["last_at"], now):
                row["exposure_return"] = None
                row["exposure_total_return"] = None
        for name, row in current["scores"].items():
            if not accounts.get(name, {}).get("fresh"):
                for field in (
                    "end_equity",
                    "net_pnl",
                    "return",
                    "gross_reference_pnl",
                    "execution_cost",
                    "total_pnl",
                    "total_return",
                ):
                    row[field] = None
                row["available"] = False
                row["reasons"].append("Current marks unavailable")
    return {
        "version": VERSION,
        "started_at": e.get("started_at"),
        "current": current,
        "completed": copy.deepcopy(e.get("completed", [])),
        "accounts": accounts,
        "method": "Unitized liquidation-equity return; external funding is not profit",
        "retention": "Current plus two completed windows; all completions retained in journal",
        "benchmark": "Cash and fresh 50/50 BTC/ETH allocation each window, with later-book fills",
        "operating_basis": "Estimated USD/day per hypothetical account; not a debit or bill",
        "cost_basis": (
            "Gross reference minus change in execution-cost accrual equals net trading. "
            "Spread/slippage and estimated exits are embedded, not deducted twice. "
            "Accrual may reverse when an opening estimate settles."
        ),
    }
