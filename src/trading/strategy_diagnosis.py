"""Bounded explanations over original evidence and existing accounting owners."""

import math
import sqlite3
import time
from collections import Counter
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.research_storage import StoragePlan, reopen_evidence

# Full original projections are about one MiB each on retained operating history.
# Keep the finite tail small; never truncate an individual original packet.
MAX_INPUT_RECORDS = 6
MAX_INPUT_BYTES = 8 * 1024**2
MAX_INTERVAL_SECONDS = 3600
MAX_QUERY_SECONDS = 2.0


def interval_start(start: float, cutoff: float) -> float:
    start = start or cutoff - 300
    if (
        not all(math.isfinite(v) for v in (start, cutoff))
        or not 0 < cutoff - start <= MAX_INTERVAL_SECONDS
    ):
        raise ValueError("Diagnosis requires a positive interval of at most one hour")
    return start


def input_row(
    packet: dict[str, Any], reference: str, symbol: str, account: str, available: float | None
) -> dict[str, Any]:
    at = packet["at"]
    eligibility = packet.get("input_eligibility", {}).get("markets", {}).get(symbol)
    saved = packet.get("state_before", {}).get("accounts", {}).get(account)
    candles = packet.get("candle_input_status", {}).get(symbol, {})
    decisions = [
        event["body"]
        for event in packet.get("events", [])
        if event.get("kind") == "decision"
        and event.get("account") == account
        and event.get("body", {}).get("symbol") == symbol
    ]
    if len(decisions) > 1:
        raise ValueError("Conflicting original decisions at one account/market tick")
    decision = decisions[0] if decisions else None
    decision_current = bool(decision and decision.get("at") == at)
    feature = {
        **{key: candles[key] for key in ("computed_at", "available_at") if key in candles},
        **packet.get("feature_origin", {}).get(symbol, {}),
        **packet.get("feature_timing", {}).get(symbol, {}),
    }
    source = packet.get("frames", {}).get(symbol, {}).get("source")
    problems = []
    if not saved:
        problems.append("account_absent")
    elif symbol not in saved.get("symbols", ["BTCUSD", "ETHUSD"]):
        problems.append("market_outside_account")
    if available is None:
        problems.append("source_availability_unknown")
    if eligibility is None:
        problems.append("input_eligibility_unknown")
    elif not eligibility.get("frame_present"):
        reason = eligibility.get("reason", "unknown")
        problems.append("missing_or_stale_book" if reason == "no_fresh_book" else reason)
    elif not isinstance(source, str) or not source.startswith("binance.us-"):
        problems.append("execution_venue_unknown_or_different")
    if not candles:
        problems.append("candle_coverage_unknown")
    elif candles.get("candle_error"):
        problems.append("candle_error")
    elif not candles.get("continuous"):
        problems.append("candle_gap")
    elif candles.get("retained_bars", 0) < 600:
        problems.append("warmup_incomplete")
    last = candles.get("last_close_ms")
    if last is not None and not 0 <= at - last / 1000 <= 90:
        problems.append("stale_or_future_candle")
    if feature.get("available_at") is not None and feature["available_at"] > at:
        problems.append("feature_not_available_at_tick")
    if feature.get("computed_at") is not None and feature["computed_at"] > at:
        problems.append("feature_not_computed_at_tick")
    if any(feature.get(key) is None for key in ("available_at", "computed_at")):
        problems.append("feature_timing_unknown")
    if (
        feature.get("ready_at") is not None
        and feature.get("computed_at") is not None
        and feature["computed_at"] < feature["ready_at"]
    ):
        problems.append("bootstrap_feature")
    books = packet.get("book_features", {}).get(symbol)
    original_scope = (
        {
            "version": saved.get("version"),
            "execution_profile": saved.get("execution_profile"),
            "rule_spec": saved.get("rule_spec"),
            "entries_paused": saved.get("entries_paused"),
            "risk_policy": saved.get("risk_policy"),
        }
        if saved
        else None
    )
    return {
        "at": at,
        "source_available_at": available,
        "reference": reference,
        "problems": problems,
        "could_evaluate": not problems,
        "original_scope": original_scope,
        "original_input_eligibility": eligibility,
        "original_frame_source": source,
        "candle_status": candles,
        "original_book_measurements": books,
        "spread_depth_basis": "Original measurements only; absent book information stays unknown",
        "recorded_decision": decision,
        "prior_decision": saved.get("last_decision", {}).get(symbol) if saved else None,
        "decision_at_this_tick": decision_current,
        "decision_meaning": (
            "Original decision recorded at this tick"
            if decision_current
            else "No new decision recorded here; an earlier decision is not a no-signal verdict"
        ),
    }


def input_coverage(
    plan: StoragePlan | None, symbol: str, account: str, start: float, cutoff: float
) -> dict[str, Any]:
    if plan is None:
        raise ValueError("Original retained input storage is unavailable; no live substitute")
    path = Path(plan.root) / "research/storage-index.sqlite"
    deadline = time.monotonic() + MAX_QUERY_SECONDS
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: 1, 1_000_000)
        records = db.execute(
            "SELECT sha,segment,record,at,available,bytes FROM storage_records "
            "WHERE kind='decision' AND at>=? AND at<=? ORDER BY at DESC,segment DESC,record DESC "
            "LIMIT ?",
            (start, cutoff, MAX_INPUT_RECORDS + 1),
        ).fetchall()
    selected = records[:MAX_INPUT_RECORDS]
    source_bytes = sum(row["bytes"] for row in selected)
    if source_bytes > MAX_INPUT_BYTES:
        raise ValueError("Selected original input records exceed the eight-MiB read budget")
    rows = []
    later = 0
    for row in reversed(selected):
        if time.monotonic() > deadline:
            raise ValueError("Original input diagnosis exceeded its two-second query budget")
        if row["available"] is not None and row["available"] > cutoff:
            later += 1
            continue
        reference = f"capture-v2:{row['segment']}:{row['record']}:{row['sha']}"
        packet = reopen_evidence(plan, reference)
        if packet.get("kind") != "decision" or packet.get("at") != row["at"]:
            raise ValueError("Original input/index identity conflicts")
        rows.append(input_row(packet, reference, symbol, account, row["available"]))
    if time.monotonic() > deadline:
        raise ValueError("Original input diagnosis exceeded its two-second query budget")
    counts = Counter(reason for row in rows for reason in row["problems"])
    evaluable = sum(row["could_evaluate"] for row in rows)
    decisions = sum(row["decision_at_this_tick"] for row in rows)
    return {
        "diagnosis": "input_coverage",
        "status": "available" if rows else "unavailable",
        "summary": f"{evaluable}/{len(rows)} retained samples supported evaluation; "
        f"{decisions} recorded a new decision. This is sampled coverage, not all engine ticks.",
        "population": {
            "retained_samples_inspected": len(rows),
            "evaluable": evaluable,
            "not_evaluable_or_unknown": len(rows) - evaluable,
            "later_available_excluded": later,
            "more_retained_records": len(records) > MAX_INPUT_RECORDS,
            "total_engine_ticks": None,
            "source_bytes": source_bytes,
            "maximum_records": MAX_INPUT_RECORDS,
            "maximum_bytes": MAX_INPUT_BYTES,
            "byte_basis": "Logical record payloads; physical cold-segment IO is unmeasured",
            "maximum_query_seconds": MAX_QUERY_SECONDS,
        },
        "problem_counts": dict(counts),
        "rows": rows,
        "facts": [
            "All shown inputs, decisions, rule/cost metadata and times come from original records",
            "Unknown opportunities and no-trade observations are not measured missed profits",
            "Supported input classification does not grant entry or operating-model authority",
        ],
        "hypotheses": [],
        "unresolved": ["Sparse retention cannot prove continuous coverage or actual fills"],
        "next_question": (
            "Which recorded input boundary prevents this comparison? Inspect original eligibility."
            if counts
            else "Which offered strategy change merits a matched prospective test?"
        ),
    }


def cost_diagnosis(outcomes: dict[str, Any]) -> dict[str, Any]:
    totals = outcomes["market_totals"]
    try:
        net, fees = Decimal(totals["net_pnl"]), Decimal(totals["fees"])
        trades = totals["trades"]
    except (TypeError, KeyError, ArithmeticError) as exc:
        raise ValueError("Original accounting totals are unavailable or invalid") from exc
    if (
        not net.is_finite()
        or not fees.is_finite()
        or fees < 0
        or type(trades) is not int
        or trades < 0
        or trades == 0
        and (net != 0 or fees != 0)
    ):
        raise ValueError("Original accounting totals are invalid")
    gross = net + fees
    status = (
        "no_closed_trades"
        if trades == 0
        else "cost_dominated"
        if gross >= 0 and net < 0 or gross > 0 and net == 0
        else "negative_before_fees"
        if gross < 0
        else "breakeven_after_recorded_fees"
        if net == 0
        else "positive_after_recorded_fees"
    )
    account_totals = outcomes["account_totals"]
    holdings = outcomes["open_holdings"]
    groups = outcomes.get("original_cost_groups", {"groups": [], "more_groups": None})
    rows = [
        {
            **row,
            "gross_before_recorded_fees_usd": str(Decimal(row["net_pnl"]) + Decimal(row["fees"])),
            "policy_basis": "Only metadata retained on original closed events; missing is unknown",
        }
        for row in groups["groups"]
    ]
    return {
        "diagnosis": "gross_after_cost",
        "status": status,
        "summary": f"{trades} closed trades in the same account/market/time cohort: "
        f"${gross} before recorded fees; ${fees} fees; ${net} net. Open holdings remain separate.",
        "population": {
            "closed_trades": trades,
            "shown_original_events": len(outcomes["events"]),
            "more_original_events": outcomes["has_more"],
            "winner_only_selection": False,
            "shown_cost_groups": len(rows),
            "more_cost_groups": groups["more_groups"],
        },
        "measured": {
            "gross_before_recorded_fees_usd": str(gross),
            "recorded_fees_usd": str(fees),
            "net_closed_pnl_usd": str(net),
            "net_basis": "Original net P/L already includes fees; no second subtraction",
            "gross_basis": "Net plus recorded fees; spread/slippage already embedded in fills",
            "whole_account": account_totals,
            "account_totals_basis": outcomes.get(
                "account_totals_basis", "Original whole-account basis is unavailable"
            ),
            "accounting_at": outcomes.get("accounting_at"),
            "closed_trade_cohort": {
                "account": outcomes.get("account"),
                "symbol": outcomes.get("symbol"),
                "interval": outcomes.get("interval"),
                "basis": (
                    "Selected interval/market closed events; not a whole-account period return"
                ),
            },
            "open_holdings": holdings,
            "pending_orders": outcomes["pending_orders"],
            "original_cost_groups": rows,
            "matched_trial_comparison": outcomes.get("trial_comparison"),
        },
        "facts": ["Gross and net use identical permanent cohort membership and original fees"],
        "hypotheses": [
            "A supported lower-turnover variation might change costs and missed moves; test both"
        ]
        if status == "cost_dominated"
        else [],
        "unresolved": [
            "This accounting identity does not identify a causal exit/sizing or liquidity defect",
            "Current contracts do not attest every historical trade's cost/horizon policy",
            "Mixed strategy versions and correlated trades are not independent matched experiments",
        ],
        "next_question": (
            "Could an offered turnover refinement reduce fees without losing useful moves?"
            if status == "cost_dominated"
            else "Which original decisions and input gaps merit a supported follow-up?"
        ),
        "source_outcomes": outcomes,
    }
