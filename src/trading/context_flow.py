"""Frozen local conditions and a separate sampled-flow shadow comparison."""

import math
import statistics
import time
from typing import Any

from trading.market import parse_book
from trading.research_evidence import book_features, digest

VERSION = "context-flow-v1"
TAXONOMY: dict[str, Any] = {
    "version": VERSION,
    "trend": "Ten-return sum: up >=5 bps, down <=-5 bps, otherwise range",
    "volatility": "Last/first five-return std: expanding >=1.5, contracting <=2/3",
    "structure": "Last cumulative return versus prior boundary, then negative last return",
    "liquidity": "Visible spread >10 bps is thin; <=10 is observed_narrow, not full liquidity",
    "flow": "Observed aggressive notional balance >0.2 buying, <-0.2 selling",
    "unknown": "Missing, nonfinite, unstable or unavailable inputs remain unknown",
    "comparability": "At least three known shared dimensions; disagreements remain visible",
    "authority": "Shadow entry filters only; baseline exits, sizing and controls unchanged",
    "cohort_result_max_bytes": 2 * 1024 * 1024,
}
FLOW: dict[str, Any] = {
    "version": VERSION,
    "window_seconds": 10,
    "minimum_snapshots": 2,
    "maximum_snapshots": 64,
    "depth_threshold": -0.2,
    "trade_threshold": -0.2,
    "delays_seconds": [0, 3, 91],
    "rule": "Wait only when observed depth and aggressive-trade balance both indicate selling",
    "coverage": "Sampled top-book changes are not complete event-level order flow",
}
CHOICES = {"comparable", "partial", "not_comparable", "insufficient_evidence"}


def number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not an observed quantity")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite observed quantity")
    return result


def classify(descriptor: dict[str, Any]) -> dict[str, Any]:
    tags = dict.fromkeys(("trend", "volatility", "structure", "liquidity", "flow"), "unknown")
    facts: dict[str, Any] = {}
    if descriptor.get("status") == "available":
        try:
            returns = [number(x) for x in descriptor["returns_bps"]]
            if len(returns) != 10:
                raise ValueError("Ten returns required")
            total = sum(returns)
            facts.update(net_change_bps=total, trend_strength=abs(total) / sum(map(abs, returns)))
            tags["trend"] = "up" if total >= 5 else "down" if total <= -5 else "range"
            early, late = statistics.pstdev(returns[:5]), statistics.pstdev(returns[5:])
            if early > 1e-12 and late > 1e-12:
                ratio = late / early
                facts["volatility_ratio"] = ratio
                tags["volatility"] = (
                    "expanding" if ratio >= 1.5 else "contracting" if ratio <= 2 / 3 else "stable"
                )
            prefix = [sum(returns[:i]) for i in range(1, 10)]
            tags["structure"] = (
                "boundary_break"
                if total > max(prefix) + 0.5
                else "near_boundary"
                if abs(total - max(prefix)) <= 0.5
                else "pullback"
                if total > 0 and returns[-1] < 0
                else "none"
            )
        except (ValueError, KeyError, TypeError, ArithmeticError):
            pass
        try:
            book = descriptor.get("context", {}).get("book", {})
            if book.get("status") != "available":
                raise ValueError("Book quality unavailable")
            spread = number(book["spread_bps"])
            imbalance = number(book["visible_depth_imbalance"])
            if spread < 0 or not -1 <= imbalance <= 1:
                raise ValueError("Invalid visible book")
            facts.update(spread_bps=spread, visible_depth_imbalance=imbalance)
            tags["liquidity"] = "thin" if spread > 10 else "observed_narrow"
        except (ValueError, KeyError, TypeError):
            pass
    return {
        "version": VERSION,
        "tags": tags,
        "facts": facts,
        "recognition_confidence": None,
        "profit_probability": None,
        "definition": TAXONOMY,
        "input_sha256": digest(descriptor),
        "reason": "Descriptions of observed inputs; no outcome or causal explanation",
    }


def comparable(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    a, b = classify(left)["tags"], classify(right)["tags"]
    known = [k for k in a if a[k] != "unknown" and b[k] != "unknown"]
    different = [k for k in known if a[k] != b[k]]
    label = (
        "insufficient_evidence"
        if len(known) < 3
        else "comparable"
        if not different
        else "partial"
        if len(different) == 1
        else "not_comparable"
    )
    return {"label": label, "shared_dimensions": known, "differences": different}


def permitted_descriptor(d: dict[str, Any]) -> dict[str, Any]:
    """Internal proposed classification packet; not any provider's native schema."""
    values = [number(x) for x in d["returns_bps"]]
    if d.get("status") != "available" or len(values) != 10:
        raise ValueError("As-seen descriptor unavailable")
    book = d.get("context", {}).get("book", {})
    measured = (
        {k: number(book[k]) for k in ("spread_bps", "visible_depth_imbalance") if k in book}
        if book.get("status") == "available"
        else {}
    )
    return {
        "returns_bps": values,
        "volatility_bps": number(d["volatility_bps"]),
        "book": measured,
        "lookback_seconds": 600,
        "horizon_seconds": 2700,
    }


def classification_packet(
    query: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(candidates) > 5:
        raise ValueError("At most five preselected numerical candidates")
    rows = [
        {
            "id": digest({"prefix": permitted_descriptor(d), "ordinal": i}),
            "prefix": permitted_descriptor(d),
        }
        for i, d in enumerate(candidates)
    ]
    packet = {
        "version": VERSION,
        "taxonomy": TAXONOMY,
        "query": permitted_descriptor(query),
        "candidates": rows,
        "question": "How comparable are the supplied beginnings?",
        "choices": sorted(CHOICES),
        "provider_wire_contract": "unverified",
    }
    packet["sha256"] = digest(packet)
    return packet


def provider_result(
    packet: dict[str, Any],
    response: dict[str, Any] | None,
    requested_at: float,
    completed_at: float,
    expires_at: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "unavailable",
        "action": "no_additional_signal",
        "paid_usd": "0",
        "reason": "Decisions access, wire contract, privacy and budget remain unverified",
        "requested_at": requested_at,
        "available_at": completed_at,
        "packet_sha256": packet["sha256"],
        "recognition_confidence": None,
        "historical_contamination": "Prefix hiding does not exclude pretrained event knowledge",
    }
    if response is None:
        return result
    try:
        if not all(math.isfinite(t) for t in (requested_at, completed_at, expires_at)):
            raise ValueError("Invalid response timing")
        if completed_at < requested_at:
            raise ValueError("Response cannot precede request")
        if completed_at > expires_at:
            return dict(result, status="result_too_late", reason="Saved response missed deadline")
        ids = {r["id"] for r in packet["candidates"]}
        answers = response["answers"]
        if (
            response["packet_sha256"] != packet["sha256"]
            or response["version"] != VERSION
            or len(answers) != len(ids)
            or {a["id"] for a in answers} != ids
            or any(a["label"] not in CHOICES for a in answers)
        ):
            raise ValueError("Unrecognized answer or candidate")
        return dict(
            result,
            status="saved_response_only",
            answers=answers,
            reason="Internal validation only; no actual provider call or economic proof",
        )
    except (KeyError, ValueError, TypeError):
        return dict(result, status="invalid_response", reason="Invalid saved classification")


def flow_features(records: list[dict[str, Any]], cutoff: float) -> dict[str, Any]:
    """Sampled valid books and explicit aggressive trade direction. Never guess missing events."""
    result: dict[str, Any] = {
        "status": "unavailable",
        "reason": "Sequence/coverage unavailable",
        "contract": FLOW,
        "action": "no_additional_signal",
    }
    try:
        eligible = [
            r
            for r in records
            if cutoff - 10 <= r["at"] <= cutoff
            and r["payload"].get("committed_at", math.inf) <= cutoff
        ]
        if not 2 <= len(eligible) <= 64:
            raise ValueError("Need two to sixty-four permitted book snapshots")
        frames = []
        sessions = set()
        trades: dict[int, dict[str, Any]] = {}
        for record in sorted(eligible, key=lambda r: r["at"]):
            p = record["payload"]
            if digest(p) != record["sha256"]:
                raise ValueError("Retained input changed")
            sessions.add(p["session"])
            f = p["frames"]["BTCUSD"]
            if f["source"] != "binance.us-depth-websocket":
                raise ValueError("Sequence-valid streaming book required")
            b = book_features(f, record["at"])
            if b["status"] != "available":
                raise ValueError("Invalid book receipt")
            frames.append((f, parse_book(f["raw"], 1000)))
            for t in p["observed_trades"].get("BTCUSD", []):
                if t["received_at"] <= cutoff and t["exchange_ms"] <= cutoff * 1000:
                    old = trades.get(t["id"])
                    if old is not None and old != t:
                        raise ValueError("Conflicting trade identity")
                    trades[t["id"]] = t
        if len(sessions) != 1 or any(
            b[1].update_id <= a[1].update_id for a, b in zip(frames, frames[1:], strict=False)
        ):
            raise ValueError("Duplicate/regressed book or connection boundary")
        # No inference that skipped sequence numbers represent complete captured order flow.
        books = [b for _, b in frames]
        final_book = books[-1]
        bid_total = sum(q for _, q in final_book.bids)
        ask_total = sum(q for _, q in final_book.asks)
        depth = float((bid_total - ask_total) / (bid_total + ask_total))
        ordered = sorted(trades.values(), key=lambda t: t["id"])
        if (
            not ordered
            or ordered[0]["received_at"] > cutoff - 10
            or any(b["id"] != a["id"] + 1 for a, b in zip(ordered, ordered[1:], strict=False))
        ):
            raise ValueError("Trade tape does not cover start or contains gaps")
        selected = [t for t in ordered if cutoff - 10 <= t["received_at"] <= cutoff]
        if not selected or any(type(t["buyer_is_maker"]) is not bool for t in selected):
            raise ValueError("Trade direction unavailable")
        notionals = [number(t["price"]) * number(t["quantity"]) for t in selected]
        if any(n <= 0 for n in notionals):
            raise ValueError("Invalid aggressive notional")
        pressure = sum(
            (-1 if t["buyer_is_maker"] else 1) * n for t, n in zip(selected, notionals, strict=True)
        ) / sum(notionals)
        ofi = 0.0
        for old_book, new_book in zip(books, books[1:], strict=False):
            pb, qb = old_book.bids[0]
            nb, nq = new_book.bids[0]
            pa, qa = old_book.asks[0]
            na, aq = new_book.asks[0]
            ofi += float(
                (nq if nb >= pb else 0)
                - (qb if nb <= pb else 0)
                - (aq if na <= pa else 0)
                + (qa if na >= pa else 0)
            )
        spreads = [
            float((b.asks[0][0] - b.bids[0][0]) / ((b.asks[0][0] + b.bids[0][0]) / 2) * 10000)
            for b in books
        ]
        return dict(
            result,
            status="observed_sample",
            snapshots=len(books),
            trades=len(selected),
            depth_imbalance=depth,
            aggressive_notional_balance=pressure,
            sampled_top_book_ofi_base=ofi,
            spread_change_bps=spreads[-1] - spreads[0],
            liquidity_replenishment="unavailable without complete event-level changes",
            action="wait_entry" if depth < -0.2 and pressure < -0.2 else "accept_baseline",
            reason="Sampled ten-second interval; omitted events remain unknown",
        )
    except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
        return dict(result, reason=str(exc))


def context_neighbors(query: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep numerical eligibility visible; category errors never erase history."""
    cutoff, start = query["cutoff"], query["start_at"]
    candidates, exclusions = [], []
    if len(rows) > 512:
        raise ValueError("Declared local library exceeds 512 prefixes")
    for row in rows:
        d = row["descriptor"]
        if row.get("available_at", d["cutoff"]) > cutoff or d["cutoff"] >= cutoff:
            continue  # Future information cannot alter even the candidate receipt.
        reason = None
        if d.get("contract") != query.get("contract") or d.get("data_mode") != query.get(
            "data_mode"
        ):
            reason = "Incompatible frozen representation or data mode"
        elif d.get("horizon_at", math.inf) >= start:
            reason = "Overlapping lookback/outcome window"
        try:
            a, b = permitted_descriptor(query), permitted_descriptor(d)
            distance = math.sqrt(
                sum((x - y) ** 2 for x, y in zip(a["returns_bps"], b["returns_bps"], strict=True))
                / 10
            )
        except (KeyError, ValueError, TypeError):
            reason = "Invalid numerical prefix"
            distance = math.inf
        if reason:
            exclusions.append({"episode": row["episode"], "reason": reason})
        else:
            candidates.append((distance, d["cutoff"], row))
    candidates.sort(key=lambda c: (c[0], c[1]))
    selected, groups = [], set()
    for distance, _, row in candidates:
        d = row["descriptor"]
        if d["group_id"] in groups:
            continue
        groups.add(d["group_id"])
        selected.append((distance, row))
        if len(selected) == 5:
            break
    matches = []
    for distance, row in selected:
        label = row.get("executable_label") or {}
        matches.append(
            {
                "episode": row["episode"],
                "distance_bps": distance,
                "classification": comparable(query, row["descriptor"]),
                "net_bps": label.get("net_bps")
                if label.get("status") == "available"
                and label.get("available_at", math.inf) <= cutoff
                else None,
            }
        )
    exclusion_counts: dict[str, int] = {}
    for item in exclusions:
        exclusion_counts[item["reason"]] = exclusion_counts.get(item["reason"], 0) + 1
    packet = (
        classification_packet(query, [r["descriptor"] for _, r in selected])
        if query.get("status") == "available"
        else None
    )
    return {
        "matches": matches,
        "eligible_candidates": len(candidates),
        "exclusion_counts": exclusion_counts,
        "input_library_sha256": digest(
            [
                {"episode": row["episode"], "prefix": row["descriptor"]}
                for row in rows
                if row.get("available_at", row["descriptor"]["cutoff"]) <= cutoff
                and row["descriptor"]["cutoff"] < cutoff
            ]
        ),
        "provider_packet": {"sha256": packet["sha256"], "status": "not_requested"}
        if packet
        else None,
        "recognition_confidence": None,
        "economic_probability": None,
    }


def evaluate_context(
    rows: list[dict[str, Any]], records: list[dict[str, Any]], plan: Any
) -> dict[str, Any]:
    started, cpu = time.perf_counter(), time.process_time()
    mode = plan.experiment_mode
    queries = [
        r
        for r in rows
        if plan.test_start <= r["descriptor"]["cutoff"] <= plan.test_end
        and r.get("available_at", r["descriptor"]["cutoff"]) <= plan.as_of
    ]
    comparisons = []
    for row in sorted(queries, key=lambda r: r["descriptor"]["cutoff"]):
        d = row["descriptor"]
        tags = classify(d)
        tags.pop("definition")  # One frozen taxonomy in the result; never repeated per query.
        if mode == "context_regime":
            rejection = tags["tags"]["trend"] == "down" or tags["tags"]["liquidity"] == "thin"
            evidence = tags
            evidence["historical_comparability"] = context_neighbors(d, rows)
            status = "observed" if any(v != "unknown" for v in tags["tags"].values()) else "unknown"
        else:
            evidence = flow_features(records, d["cutoff"])
            evidence.pop("contract", None)
            rejection = evidence["action"] == "wait_entry"
            status = evidence["status"]
        label = row.get("executable_label") or {}
        target = None
        if (
            label.get("status") == "available"
            and d["horizon_at"] <= label["available_at"] <= plan.as_of
        ):
            target = number(label["net_bps"])
        comparisons.append(
            {
                "episode": row["episode"],
                "cutoff": d["cutoff"],
                "status": status,
                "action": "reject_entry" if rejection else "no_additional_signal",
                "evidence": evidence,
                "ablations": {
                    "without_component": "unchanged_baseline",
                    "fixed_direction": "accept" if sum(d.get("returns_bps", [])) > 0 else "wait",
                },
                "later_net_trade_bps": target,
                "latency_sensitivity": [
                    {
                        "delay_seconds": delay,
                        "status": "result_too_late"
                        if d["cutoff"] + delay > d.get("expires_at", d["cutoff"])
                        else status,
                        "changes_entry": rejection
                        and d["cutoff"] + delay <= d.get("expires_at", 0),
                    }
                    for delay in FLOW["delays_seconds"]
                ],
            }
        )
    known = [q for q in comparisons if q["later_net_trade_bps"] is not None]
    return {
        "version": VERSION,
        "mode": mode,
        "status": "inconclusive" if queries else "insufficient_data",
        "decision": "reject",
        "eligible_for_forward_review": False,
        "contract": TAXONOMY if mode == "context_regime" else FLOW,
        "reason": "Independent shadow comparison; paired-account effect unverified",
        "comparisons": comparisons,
        "opportunities": len(queries),
        "labeled": len(known),
        "unknown_outcomes": len(queries) - len(known),
        "changed_decisions": sum(q["action"] == "reject_entry" for q in comparisons),
        "missed_positive_taken_trades": sum(
            q["action"] == "reject_entry" and q["later_net_trade_bps"] > 0 for q in known
        ),
        "whole_account_effect": None,
        "turnover": None,
        "exposure": None,
        "switching_cost": None,
        "marginal_operating_usd": None,
        "controls": ["unchanged_baseline", "fixed_direction", "matched_cash_unavailable"],
        "optional_D": provider_result(
            {"sha256": "not_requested"}, None, plan.as_of, plan.as_of, plan.as_of
        ),
        "limitations": [
            "No forward selection or strategy switching",
            "Taken-trade selection bias",
            "Condition labels are descriptive hypotheses, not causes",
            "Sampled flow is not complete order flow or execution improvement",
        ],
        "resources": {
            "elapsed_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "paid_usd": "0",
        },
    }
