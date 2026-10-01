"""Bounded market inspection shared by the command station and advisory tools."""

import copy
import re
import time
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any

from trading.chart_indicators import overlays
from trading.execution_profiles import LEGACY_EXECUTION, PROFILES, execution
from trading.paper_engine import filters, fresh_frame
from trading.paper_strategy import VARIANTS
from trading.tiered_runtime import TieredPaperRuntime

VERSION = "market-evidence-tools-v2"
TOOLS = {
    "market_evidence": {
        "name": "Inspect market evidence",
        "purpose": "Check quote freshness, visible liquidity, candles and observed trades.",
    },
    "cost_hurdle": {
        "name": "Calculate cost hurdle",
        "purpose": "Measure the price move needed to cover spread and modeled trading costs.",
    },
    "strategy_evidence": {
        "name": "Explain the recorded decision",
        "purpose": "Inspect the primary strategy's actual last decision and its feature values.",
    },
    "outcome_review": {
        "name": "Review paper outcomes",
        "purpose": "Inspect retained outcomes for this market with costs and account context.",
    },
}


def validate_symbol(symbol: str, runtime: TieredPaperRuntime) -> None:
    if not re.fullmatch(r"[A-Z0-9]{3,24}", symbol) or symbol not in runtime.instruments:
        raise ValueError("Select a known USD market from the scanner")


def market_live(runtime: TieredPaperRuntime, symbol: str) -> dict[str, Any]:
    quotes = runtime.quotes()
    quote = next((q for q in quotes["markets"] if q["symbol"] == symbol), None)
    frame = None
    if quote:
        frames = (
            runtime.stream.books
            if quote["source"] == "binance.us-depth-websocket"
            else runtime._fallback
        )
        frame = frames.get(symbol)
    book = frame["book"] if frame else None
    return {
        **quotes,
        "selected_symbol": symbol,
        "book": {
            "bids": [[str(p), str(q)] for p, q in book.bids[:10]],
            "asks": [[str(p), str(q)] for p, q in book.asks[:10]],
            "update_id": book.update_id,
            "state": quote["state"] if quote else "unavailable",
            "metrics": book.metrics(),
            "levels_shown": 10,
        }
        if book
        else None,
        "trades": list(reversed(runtime.stream.trade_tape.get(symbol, [])))[:20],
        "trade_gaps": runtime.stream.stats.get(symbol, {}).get("trade_gaps", 0),
        "trade_tape_limit": 20,
        "trade_tape_scope": "Recent subscription observations; incomplete across gaps/restarts",
    }


def strategy_evidence(runtime: TieredPaperRuntime, symbol: str) -> dict[str, Any]:
    primary = runtime.state["accounts"]["primary"]
    return copy.deepcopy(
        {
            "symbol": symbol,
            "version": primary["version"],
            "last_decision": primary["last_decision"].get(symbol),
            "features": runtime.study.get(symbol, {}).get(primary["version"]),
            "primary_market": symbol in primary.get("symbols", ("BTCUSD", "ETHUSD")),
            "entries_paused": runtime.state["paused"],
            "next_review": runtime.state["next_review"],
            "position": primary["positions"].get(symbol),
            "pending": primary["pending"].get(symbol),
            "note": "Recorded decisions retain their timestamps; no new entry approval is given",
        }
    )


def market_detail(runtime: TieredPaperRuntime, symbol: str) -> dict[str, Any]:
    validate_symbol(symbol, runtime)
    history = runtime.history.get(symbol, [])[-120:]
    gaps = [
        {"after_ms": a.close_ms, "before_ms": b.open_ms}
        for a, b in zip(history, history[1:], strict=False)
        if b.open_ms - a.open_ms != 60000
    ]
    scanner = sorted(
        runtime.universe.rows,
        key=lambda row: (
            row["symbol"] not in runtime.stream.plan,
            not row.get("eligible"),
            row["symbol"],
        ),
    )[:80]
    return {
        "generated_at": time.time(),
        "selected_symbol": symbol,
        "scan": {
            "observed_at": runtime.universe.scanned_at,
            "rows": scanner,
            "total": len(runtime.universe.rows),
            "omitted": max(0, len(runtime.universe.rows) - len(scanner)),
            "selected": runtime.universe.selected,
            "constrained": runtime.constrained(),
        },
        "candles": [
            {
                "open_ms": b.open_ms,
                "close_ms": b.close_ms,
                **{key: str(getattr(b, key)) for key in ("open", "high", "low", "close", "volume")},
            }
            for b in history
        ],
        "candle_gaps": gaps,
        "indicators": overlays(runtime.history.get(symbol, [])[-600:]),
        "candles_stale": bool(history and time.time() * 1000 - history[-1].close_ms > 90000),
        "history_scope": "Up to 120 closed minute candles; bootstrap history is not paper trading",
        "strategy": strategy_evidence(runtime, symbol),
        "experiments": strategy_experiments(runtime, symbol),
        "paper_events": [
            {
                "id": event["id"],
                "at": event["at"],
                "kind": event["kind"],
                "body": {
                    key: event["body"][key]
                    for key in ("symbol", "reason", "side", "price", "quantity", "pnl", "fees")
                    if key in event["body"]
                },
            }
            for event in [e for e in runtime.recent if e.get("body", {}).get("symbol") == symbol][
                :12
            ]
        ],
    }


def market_evidence(runtime: TieredPaperRuntime, symbol: str) -> dict[str, Any]:
    """Save selected-market evidence without duplicating the full chart/scanner."""
    live = market_live(runtime, symbol)
    markets = live["markets"]
    live["markets"] = [quote for quote in markets if quote["symbol"] == symbol]
    live["markets_total"] = len(markets)
    live["markets_omitted"] = len(markets) - len(live["markets"])
    live["markets_scope"] = "Selected market only; other quotes remain available in Markets"

    detail = market_detail(runtime, symbol)
    scan = detail["scan"]
    scan["rows"] = copy.deepcopy(
        [row for row in runtime.universe.rows if row["symbol"] == symbol]
    )
    scan["omitted"] = scan["total"] - len(scan["rows"])
    scan["scope"] = "Selected market only; other scanner rows remain available in Markets"

    indicators = detail["indicators"]
    points = indicators["points"]
    candle_times = {candle["open_ms"] for candle in detail["candles"]}
    # Preserve the chart's full-history values, warmup and gap resets before projection.
    indicators["points"] = [point for point in points if point["open_ms"] in candle_times]
    indicators["points_omitted"] = len(points) - len(indicators["points"])
    indicators["calculation_history_bars"] = len(runtime.history.get(symbol, [])[-600:])
    indicators["scope"] = (
        "Full chart calculation history; saved points match the latest 120-candle evidence window"
    )
    return {"live": live, "detail": detail}


def strategy_experiments(runtime: TieredPaperRuntime, symbol: str) -> dict[str, Any]:
    """Describe frozen rules and recorded outcomes; never run or approve a strategy."""
    state = runtime.state
    variants = []
    for version, rules in VARIANTS.items():
        account = state["accounts"][version]
        profile = PROFILES.get(account.get("execution_profile", LEGACY_EXECUTION))
        feature = runtime.study.get(symbol, {}).get(version, {})
        closed_at = (feature["bar_open_ms"] + 60000) / 1000 if "bar_open_ms" in feature else None
        fresh = closed_at is not None and 0 <= time.time() - closed_at <= 90
        complete = all(
            key in feature for key in ("close", "breakout", "volume_ratio", "atr", "trend_up")
        )
        checks: dict[str, bool | None] = dict.fromkeys(("trend", "breakout", "volume", "extension"))
        if fresh and complete:
            close, level, atr = (Decimal(feature[key]) for key in ("close", "breakout", "atr"))
            checks = {
                "trend": bool(feature["trend_up"]),
                "breakout": close > level,
                "volume": Decimal(feature["volume_ratio"]) > Decimal(rules["volume_multiple"]),
                "extension": atr > 0 and close - level <= Decimal("1.5") * atr,
            }
        variants.append(
            {
                "version": version,
                "rules": dict(rules),
                "features": copy.deepcopy(feature),
                "feature_closed_at": closed_at,
                "feature_fresh": fresh and complete,
                "checks": checks,
                "account": {
                    "execution_profile": profile.id if profile else "unknown",
                    "fee_per_side": str(profile.fee(symbol)) if profile else None,
                    "closed": account["closed"],
                    "net_pnl": str(Decimal(account["equity"]) - Decimal(account["funding"])),
                    "fees": account["fees"],
                    "max_drawdown": account["max_drawdown"],
                    "valuation_fresh": (
                        account["valuation_fresh"]
                        and fresh_frame({"observed": account.get("valuation_at")}, time.time())
                        and runtime.running
                        and not runtime.error
                        and time.time() - state["last_tick"] <= 10
                    ),
                },
            }
        )
    reviews = state.get("review_history", [])
    latest = reviews[-1] if reviews else None
    return {
        "active_version": state["accounts"]["primary"]["version"],
        "variants": variants,
        "next_review": state["next_review"],
        "review_count": state["review_count"],
        "latest_review": {
            "at": latest["at"],
            "evaluation": latest.get("evaluation", "historical-completed-trade-average"),
            "selected": latest["selected"],
            "reason": latest["reason"],
            "windows": [
                {
                    "start": window["start"],
                    "end": window["end"],
                    "returns": {v: score.get("return") for v, score in window["scores"].items()},
                    "trades": {
                        version: score["trades"] for version, score in window["scores"].items()
                    },
                }
                for window in latest["windows"][-2:]
            ],
        }
        if latest
        else None,
        "scope": "Separate BTC/ETH shadow accounts; correlated results, not independent attempts",
        "learning_mode": (
            "Bounded selection among frozen rules; trained-model and LLM roles inactive"
        ),
    }


def cost_hurdle(runtime: TieredPaperRuntime, symbol: str) -> dict[str, Any]:
    live = market_live(runtime, symbol)
    quote = next((q for q in live["markets"] if q["symbol"] == symbol), None)
    if not quote or quote["state"] != "fresh":
        raise ValueError("A fresh quote is required; no cost estimate was fabricated")
    if time.time() - runtime.metadata_at > 900:
        raise ValueError("Market filters are stale; wait for refreshed instrument metadata")
    profile = execution(runtime.state["accounts"]["primary"])
    fee, slippage = profile.fee(symbol), Decimal(profile.slippage)
    tick = filters(runtime.instruments[symbol])["tick"]
    bid, ask = Decimal(quote["bid"]), Decimal(quote["ask"])
    entry = (ask * (1 + slippage) / tick).to_integral_value(rounding=ROUND_UP) * tick
    exit_price = (bid * (1 - slippage) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    entry_cost = entry * (1 + fee)
    exit_value = exit_price * (1 - fee)
    minimum_exit = (entry_cost / (1 - fee) / tick).to_integral_value(rounding=ROUND_UP) * tick
    required_bid = (minimum_exit / (1 - slippage) / tick).to_integral_value(
        rounding=ROUND_UP
    ) * tick
    return {
        "execution_profile": profile.id,
        "symbol": symbol,
        "quote": quote,
        "round_trip_loss_percent": str((1 - exit_value / entry_cost) * 100),
        "required_bid": str(required_bid),
        "required_bid_move_percent": str((required_bid / bid - 1) * 100),
        "fee_per_side": str(fee),
        "adverse_price_per_side": str(slippage),
        "participation_cap": profile.participation,
        "price_tick": str(tick),
        "scope": (
            "Top-of-book cost hurdle per unit; deeper impact, quantity filters, timing "
            "and fill uncertainty are excluded. No order or fill is created."
        ),
    }


def execute_tool(runtime: TieredPaperRuntime, tool: str, symbol: str) -> dict[str, Any]:
    if tool not in TOOLS:
        raise ValueError("Tool is not registered")
    validate_symbol(symbol, runtime)
    result: dict[str, Any]
    if tool == "market_evidence":
        result = market_evidence(runtime, symbol)
    elif tool == "cost_hurdle":
        result = cost_hurdle(runtime, symbol)
    elif tool == "strategy_evidence":
        result = strategy_evidence(runtime, symbol)
    else:
        account = runtime.state["accounts"]["primary"]
        retained = [trade for trade in account["recent_trades"] if trade.get("symbol") == symbol]
        sample = retained[-30:]
        result = {
            "symbol": symbol,
            "recent_market_trades": copy.deepcopy(sample),
            "sample_totals": {
                "trades": len(sample),
                "net_pnl": str(sum((Decimal(trade["pnl"]) for trade in sample), Decimal(0))),
                "fees": str(sum((Decimal(trade["fees"]) for trade in sample), Decimal(0))),
            },
            "retained_market_count": len(retained),
            "omitted_retained_market_trades": max(0, len(retained) - 30),
            "scope": (
                "Latest 30 matching trades from the primary account's 1,000-trade memory; "
                "durable history remains in the journal"
            ),
            "account_totals": {
                key: copy.deepcopy(account[key])
                for key in (
                    "equity",
                    "funding",
                    "fees",
                    "realized",
                    "closed",
                    "attempt",
                    "replenishments",
                )
            },
        }
    return {"tool": tool, "version": VERSION, "observed_at": time.time(), "result": result}
