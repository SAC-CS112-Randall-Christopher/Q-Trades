"""Frozen, outcome-blind local episode descriptors. Diagnostic only in CP10."""

import math
from decimal import Decimal
from statistics import pstdev
from typing import Any

from trading.paper_strategy import VARIANTS
from trading.research_evidence import digest

VERSION = "breakout-prefix-v1"
CONTRACT = {
    "version": VERSION,
    "strategy": "breakout-v1",
    "venue": "Binance.US",
    "symbol": "BTCUSD",
    "lookback_seconds": VARIANTS["breakout-v1"]["lookback"] * 60,
    "horizon_seconds": 2700,  # Existing engine maximum hold, not a fitted label horizon.
    "representation": "Ten consecutive one-minute close returns in basis points",
    "normalization": "Price-relative per prefix; no learned scaling or time warping",
    "neighbors": 5,
    "per_group_limit": 1,
    "authority": "Observation-only; baseline action and all financial controls unchanged",
}


def permitted_bars(rows: list[dict[str, Any]], cutoff: float) -> list[dict[str, Any]]:
    if not math.isfinite(cutoff) or len(rows) > 1200:
        raise ValueError("Invalid bounded prefix")
    selected: dict[int, dict[str, Any]] = {}
    eligible = []
    for row in rows:
        available = float(row["available_at"])
        if not math.isfinite(available):
            raise ValueError("Invalid bar availability")
        if available <= cutoff:
            eligible.append(row)
    for row in sorted(eligible, key=lambda r: (r["open_ms"], r["available_at"])):
        available = row["available_at"]
        if row["close_ms"] >= cutoff * 1000:
            continue
        if row["open_ms"] % 60000 or row["close_ms"] != row["open_ms"] + 59999:
            raise ValueError("Unsupported bar interval")
        # First permitted version wins; later corrections are different evidence.
        previous = selected.get(row["open_ms"])
        if previous is not None:
            if previous["available_at"] == available and previous != row:
                raise ValueError("Ambiguous same-availability revision")
            continue
        selected[row["open_ms"]] = row
    return list(selected.values())


def descriptor(
    rows: list[dict[str, Any]], cutoff: float, context: dict[str, Any], data_mode: str
) -> dict[str, Any]:
    base: dict[str, Any] = {"contract": CONTRACT, "cutoff": cutoff, "data_mode": data_mode}
    try:
        bars = permitted_bars(rows, cutoff)[-11:]
        if len(bars) != 11 or any(
            b["open_ms"] - a["open_ms"] != 60000 for a, b in zip(bars, bars[1:], strict=False)
        ):
            raise ValueError("Eleven contiguous as-seen closes required")
        if not 0 < cutoff * 1000 - bars[-1]["close_ms"] <= 90000:
            raise ValueError("Prefix closes are stale")
        closes = [Decimal(b["close"]) for b in bars]
        if not all(p.is_finite() and p > 0 for p in closes):
            raise ValueError("Invalid prefix price")
        returns = [float((b / a - 1) * 10000) for a, b in zip(closes, closes[1:], strict=False)]
        if not all(math.isfinite(r) for r in returns) or pstdev(returns) <= 1e-12:
            raise ValueError("Flat or zero-variance descriptor; no resemblance inferred")
        prefix = {"bars": bars, "context": context}
        return {
            **base,
            "status": "available",
            "prefix_sha256": digest(prefix),
            "start_at": bars[0]["open_ms"] / 1000,
            "anchor_close": str(closes[-1]),
            "returns_bps": returns,
            "volatility_bps": pstdev(returns),
            "raw_closes": [str(p) for p in closes],
            "context": context,
            "group_id": f"BTCUSD:{int(cutoff // 3300)}",
            "horizon_at": cutoff + CONTRACT["horizon_seconds"],
            "expires_at": bars[-1]["close_ms"] / 1000 + 90,
            "units": {"shape": "basis points per minute", "price": "USD", "volume": "BTC"},
            "execution_coverage": "Decision book only; continuous execution path unavailable",
        }
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return {**base, "status": "invalid_input", "reason": str(exc)}


def lookup(
    query: dict[str, Any], library: list[dict[str, Any]], completed_at: float
) -> dict[str, Any]:
    """Select by beginning only, then attach outcomes available at the query cutoff."""
    cutoff = query["cutoff"]
    receipt: dict[str, Any] = {
        "version": VERSION,
        "query_cutoff": cutoff,
        "completed_at": completed_at,
        "earliest_action_at": completed_at,
        "expires_at": query.get("expires_at"),
        "library_snapshot": [],
        "candidates": [],
        "matches": [],
        "classification": "Local numerical distance; contextual classifier not requested",
        "recognition_confidence": None,
        "economic_evidence": "No executable-return estimate in CP10",
        "changed_decision": False,
        "fallback": "No additional signal; existing baseline controls apply",
    }
    if query["status"] != "available":
        return {**receipt, "status": "data_incomplete", "reason": query["reason"]}
    if len(library) > 512:
        raise ValueError("Frozen episode-library capacity exceeded")
    ranked = []
    for entry in library:
        # Post-cutoff inserts/revisions/labels do not even alter the saved snapshot.
        if entry["available_at"] > cutoff:
            continue
        d = entry["descriptor"]
        if d["cutoff"] > cutoff:
            continue
        receipt["library_snapshot"].append(
            {"episode": entry["episode"], "sha256": entry["descriptor_sha256"]}
        )
        reason = None
        if d.get("contract") != query["contract"] or d.get("data_mode") != query["data_mode"]:
            reason = "Incompatible version, instrument or data mode"
        elif d.get("status") != "available":
            reason = "Invalid descriptor"
        elif not (d["horizon_at"] < query["start_at"] or query["horizon_at"] < d["start_at"]):
            reason = "Overlapping lookback/outcome event"
        if reason:
            receipt["candidates"].append({"episode": entry["episode"], "excluded": reason})
            continue
        vector = d["returns_bps"]
        distance = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(query["returns_bps"], vector, strict=True))
            / len(vector)
        )
        ranked.append((distance, entry["episode"], entry))
    groups: set[str] = set()
    selected_intervals: list[tuple[float, float]] = []
    for distance, _, entry in sorted(ranked):
        d = entry["descriptor"]
        overlap = any(
            not (d["horizon_at"] < start or end < d["start_at"])
            for start, end in selected_intervals
        )
        excluded = (
            overlap or d["group_id"] in groups or len(receipt["matches"]) >= CONTRACT["neighbors"]
        )
        receipt["candidates"].append(
            {
                "episode": entry["episode"],
                "distance_bps": distance,
                "excluded": "Group concentration / neighbor cap" if excluded else None,
                "overlapping_historical_event": overlap,
            }
        )
        if excluded:
            continue
        groups.add(d["group_id"])
        selected_intervals.append((d["start_at"], d["horizon_at"]))
        outcome = entry.get("outcome")
        permitted = outcome is not None and outcome["available_at"] <= cutoff
        receipt["matches"].append(
            {
                "episode": entry["episode"],
                "record_id": entry["record_id"],
                "distance_bps": distance,
                "group_id": d["group_id"],
                "cutoff": d["cutoff"],
                "context": d["context"],
                "outcome": outcome if permitted else None,
                "outcome_status": outcome["status"]
                if permitted and outcome is not None
                else "outcome_pending_at_cutoff",
            }
        )
    receipt["library_snapshot"].sort(key=lambda row: row["episode"])
    receipt["candidates"].sort(key=lambda row: row["episode"])
    receipt["library_sha256"] = digest(receipt["library_snapshot"])
    receipt["distinct_groups"] = len(groups)
    receipt["status"] = (
        "result_too_late"
        if completed_at > query["expires_at"]
        else "matches_available"
        if receipt["matches"]
        else "no_comparable_history"
    )
    receipt["support_note"] = (
        "Similarity and event groups are diagnostics, not trading probabilities"
    )
    return receipt


def market_outcome(
    episode: dict[str, Any], rows: list[dict[str, Any]], cutoff: float, available_at: float
) -> dict[str, Any]:
    """Immutable delayed market label; no invented orders, costs or executable P&L."""
    d = episode["descriptor"]
    if cutoff < d["horizon_at"] or available_at < d["horizon_at"]:
        raise ValueError("Outcome has not matured")
    base = {
        "episode": episode["episode"],
        "kind": "outcome",
        "at": available_at,
        "available_at": available_at,
        "horizon_at": d["horizon_at"],
        "version": VERSION,
        "label_type": "Subsequent minute-candle market path; not filled/net trading return",
        "realized_pnl": None,
        "remaining_executable_opportunity": None,
        "execution_reason": "Continuous books and supported action replay required by CP11",
    }
    bars = [
        b
        for b in permitted_bars(rows, cutoff)
        if b["open_ms"] >= int(d["cutoff"] // 60) * 60000
        and b["close_ms"] <= d["horizon_at"] * 1000
    ]
    expected = int(CONTRACT["horizon_seconds"] // 60)
    if len(bars) != expected or any(
        b["open_ms"] - a["open_ms"] != 60000 for a, b in zip(bars, bars[1:], strict=False)
    ):
        return {
            **base,
            "status": "unavailable",
            "reason": "Subsequent candle path incomplete",
            "observed_bars": len(bars),
            "required_bars": expected,
        }
    anchor = Decimal(d["anchor_close"])
    return {
        **base,
        "status": "available",
        "observed_bars": len(bars),
        "return_bps": str((Decimal(bars[-1]["close"]) / anchor - 1) * 10000),
        "favorable_excursion_bps": str(
            max(Decimal(0), (max(Decimal(b["high"]) for b in bars) / anchor - 1) * 10000)
        ),
        "adverse_excursion_bps": str(
            min(Decimal(0), (min(Decimal(b["low"]) for b in bars) / anchor - 1) * 10000)
        ),
        "ambiguity": "Intrabar ordering unknown; stop/target fills cannot be inferred",
        "path_sha256": digest(bars),
    }
