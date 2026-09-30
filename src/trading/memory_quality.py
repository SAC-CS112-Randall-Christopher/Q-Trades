"""Small frozen history estimator. Recognition and execution evidence stay separate."""

import math
import statistics
import time
from copy import deepcopy
from typing import Any

from trading.research_evidence import digest

VERSION = "memory-entry-v1"
CONTRACT: dict[str, Any] = {
    "version": VERSION,
    "family": "memory_entry",
    "symbol": "BTCUSD",
    "horizon_seconds": 2700,
    "neighbors": 5,
    "minimum_groups": 5,
    "minimum_train": 12,
    "minimum_calibration": 6,
    "minimum_test": 8,
    "library_max": 128,
    "maximum_concentration": 0.2,
    "unfamiliar_distance": 3.0,
    "weak_distance": 2.0,
    "minimum_net_bps": 5.0,
    "target": "Recorded filled-trade net return on filled cost; execution costs embedded once",
    "fallback": "No additional signal; unchanged baseline entry and deterministic exits",
    "normalization": "Per-coordinate training-only mean/std with explicit zero-variance rejection",
    "evaluation": "Chronological training/calibration/protected test; 3300-second purge",
    "minimum_worthwhile_account_return": 0.001,
    "stopping": "One frozen comparison; insufficient or negative evidence is retained",
}


def vector(descriptor: dict[str, Any], arm: str) -> list[float]:
    if descriptor.get("status") != "available":
        raise ValueError("As-seen descriptor unavailable")
    values = descriptor["returns_bps"]
    if not isinstance(values, list) or len(values) != 10:
        raise ValueError("Ten as-seen returns required")
    result = [float(x) for x in values]
    if arm == "C":
        book = descriptor.get("context", {}).get("book") or {}
        # Unknown depth/liquidity is never zero or a fabricated neutral condition.
        result += [float(descriptor["volatility_bps"]), float(book["spread_bps"])]
        result += [float(book["visible_depth_imbalance"])]
    elif arm != "B":
        raise ValueError("Unregistered local memory arm")
    if not all(math.isfinite(x) for x in result):
        raise ValueError("Invalid as-seen numerical input")
    return result


def validate_artifact(artifact: dict[str, Any]) -> None:
    if not isinstance(artifact, dict):
        raise ValueError("Memory artifact is unavailable")
    body = {k: v for k, v in artifact.items() if k != "sha256"}
    if digest(body) != artifact.get("sha256") or artifact.get("contract") != CONTRACT:
        raise ValueError("Frozen memory artifact fingerprint/contract mismatch")
    if (
        artifact.get("version") != VERSION
        or artifact.get("family") != "memory_entry"
        or artifact.get("symbol") != "BTCUSD"
        or artifact.get("maximum_hold_seconds") != 2700
        or artifact.get("progress_seconds") != 600
        or artifact.get("arm") not in {"B", "C"}
        or artifact.get("evidence_kind") not in {"synthetic_qa", "observed_public_quotes"}
    ):
        raise ValueError("Unregistered memory contract")
    dimensions = 10 if artifact["arm"] == "B" else 13
    means, scales, library = artifact["means"], artifact["scales"], artifact["library"]
    if len(means) != dimensions or len(scales) != dimensions or not 12 <= len(library) <= 128:
        raise ValueError("Frozen memory dimensions/support unavailable")
    if not all(type(x) in (int, float) and math.isfinite(x) for x in means + scales):
        raise ValueError("Invalid frozen normalization")
    if any(x <= 1e-12 for x in scales):
        raise ValueError("Unstable training normalization")
    seen = set()
    for row in library:
        if row["group"] in seen or len(row["x"]) != dimensions:
            raise ValueError("Duplicated independent groups or invalid dimensions")
        seen.add(row["group"])
        if not all(math.isfinite(float(x)) for x in row["x"] + [row["net_bps"], row["at"]]):
            raise ValueError("Invalid frozen library")
        if not row["at"] < row["available_at"] <= artifact["train_end"]:
            raise ValueError("Library target availability exceeds training")
    bins = artifact.get("calibration", [])
    if len(bins) != 3 or any(
        type(b["count"]) is not int
        or b["count"] < 0
        or b["probability"] is not None
        and not 0 <= b["probability"] <= 1
        for b in bins
    ):
        raise ValueError("Frozen calibration unavailable")


def predict(
    descriptor: dict[str, Any], artifact: dict[str, Any], available_at: float
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "invalid_input",
        "action": "no_additional_signal",
        "reason": "Frozen artifact or required input unavailable",
        "recognition_confidence": None,
        "profit_probability": None,
        "financial_authority": False,
        "contract": VERSION,
    }
    try:
        validate_artifact(artifact)
        cutoff, expiry = descriptor["cutoff"], descriptor["expires_at"]
        if not math.isfinite(available_at) or not cutoff <= available_at <= expiry:
            return dict(result, status="result_too_late", reason="Result outside action deadline")
        if max(artifact["train_end"], artifact["calibration_end"]) >= cutoff:
            raise ValueError("Training target information must precede this query")
        x = vector(descriptor, artifact["arm"])
        z = [(v - m) / s for v, m, s in zip(x, artifact["means"], artifact["scales"], strict=True)]
        candidates = []
        for row in artifact["library"]:
            if row["available_at"] > cutoff or row["end"] >= descriptor["start_at"]:
                continue
            distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(z, row["x"], strict=True)) / len(z)
            )
            candidates.append((distance, row))
        # Selection is entirely outcome-blind. Opaque IDs never break numerical ties.
        candidates.sort(key=lambda pair: (pair[0], pair[1]["at"]))
        selected = candidates[: CONTRACT["neighbors"]]
        distances = [d for d, _ in selected]
        base = {
            **result,
            "available_at": available_at,
            "earliest_action_at": available_at,
            "expires_at": expiry,
            "cutoff": cutoff,
            "artifact_sha256": artifact["sha256"],
            "neighbors": [
                {
                    "episode": r["episode"],
                    "record_id": r.get("record_id"),
                    "group": r["group"],
                    "distance": d,
                }
                for d, r in selected
            ],
            "distinct_groups": len(selected),
            "distinct_days": len({int(r["at"] // 86400) for _, r in selected}),
            "maximum_weight": 1 / len(selected) if selected else None,
            "normalization_source": "Frozen training partition",
            "horizon_seconds": 2700,
        }
        if selected and distances[0] > CONTRACT["unfamiliar_distance"]:
            return dict(base, status="unfamiliar", reason="Outside frozen familiarity radius")
        if len(selected) < 5 or distances[-1] > CONTRACT["weak_distance"]:
            return dict(base, status="weak_support", reason="Five distinct close groups required")
        outcomes = [float(r["net_bps"]) for _, r in selected]
        expected = statistics.mean(outcomes)
        raw_probability = sum(y > 0 for y in outcomes) / len(outcomes)
        bucket = min(2, int(raw_probability * 3))
        calibrated = artifact["calibration"][bucket]
        probability = calibrated["probability"] if calibrated["count"] >= 3 else None
        unfavorable = [r["episode"] for _, r in selected if r["net_bps"] <= 0]
        favorable = [r["episode"] for _, r in selected if r["net_bps"] > 0]
        action = "accept" if expected > 5 and min(outcomes) > -100 else "reject_entry"
        return {
            **base,
            "status": "supported",
            "action": action,
            "reason": "Frozen net-quality rule; baseline risk authority still applies",
            "expected_net_bps": expected,
            "downside_bps": min(outcomes),
            "range_bps": [min(outcomes), max(outcomes)],
            "dispersion_bps": statistics.pstdev(outcomes),
            "profit_probability": probability,
            "raw_positive_fraction": raw_probability,
            "probability_scope": "Small chronological calibration; later reliability unverified",
            "target": CONTRACT["target"],
            "costs_already_embedded": True,
            "uncertainty": "Five separated groups are descriptive; independence unverified",
            "illustrations": {
                "favorable": favorable[:1],
                "unfavorable": unfavorable[:1],
                "scope": "Illustrations only; distribution uses every selected neighbor",
            },
            "economic_evidence": "Matched whole-account net comparison still required",
        }
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return dict(result, reason=str(exc))


def evaluate_memory(rows: list[dict[str, Any]], plan: Any) -> dict[str, Any]:
    started, cpu = time.perf_counter(), time.process_time()
    if len(rows) > 512:
        raise ValueError("Memory corpus exceeds the declared 512-episode budget")
    valid, unknown = [], []
    for row in sorted(rows, key=lambda r: (r["descriptor"]["cutoff"], r["episode"])):
        label, d = row.get("executable_label"), row["descriptor"]
        if d["cutoff"] > plan.as_of or row.get("available_at", d["cutoff"]) > plan.as_of:
            continue
        if not label or label.get("status") != "available" or label["available_at"] > plan.as_of:
            unknown.append(
                {"episode": row["episode"], "reason": "Executable target unavailable or pending"}
            )
            continue
        if label.get("version") != "executed-trade-net-v1" or label.get("horizon_seconds") != 2700:
            unknown.append({"episode": row["episode"], "reason": "Unsupported executable target"})
            continue
        if (
            not math.isfinite(label["available_at"])
            or not d["horizon_at"] <= label["available_at"]
            or not math.isfinite(label["net_bps"])
        ):
            raise ValueError("Invalid executable target availability or return")
        valid.append(row)
    cal_start = plan.test_start - 7 * 86400
    train_end = cal_start - 3300

    def known_at(row: dict[str, Any]) -> float:
        return float(
            max(
                row["executable_label"]["available_at"],
                row.get("available_at", row["descriptor"]["cutoff"]),
            )
        )

    train = [r for r in valid if known_at(r) < train_end]
    calibration = [
        r
        for r in valid
        if cal_start <= r["descriptor"]["start_at"] and known_at(r) < plan.test_start - 3300
    ]
    test = [
        r
        for r in valid
        if r["descriptor"]["start_at"] >= plan.test_start and known_at(r) <= plan.test_end
    ]

    def separated(partition: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected = []
        prior_end = -math.inf
        seen = set()
        for row in partition:
            d = row["descriptor"]
            if d["start_at"] <= prior_end or d["group_id"] in seen:
                continue
            selected.append(row)
            seen.add(d["group_id"])
            prior_end = d["horizon_at"]
        return selected

    train, calibration, test = (separated(p) for p in (train, calibration, test))
    result: dict[str, Any] = {
        "status": "insufficient_data",
        "decision": "reject",
        "eligible_for_forward_review": False,
        "contract": CONTRACT,
        "target_coverage": {
            "opportunities": len(rows),
            "available": len(valid),
            "unknown": len(unknown),
            "unknown_examples": unknown[:20],
        },
        "train_samples": len(train),
        "calibration_samples": len(calibration),
        "test_samples": len(test),
        "candidate_group": [],
        "independent_validation": False,
        "whole_account_effect": None,
        "cash_control": None,
        "exposure_control": None,
        "reason": "Need twelve training, six calibration and eight protected executable groups",
        "selection_treatment": "Fixed B/C comparison; retained attempts; outcome-blind neighbors",
        "limitations": [
            "Taken-trade targets retain selection bias; missing counterfactuals remain unknown",
            "Trade diagnostics do not establish whole-account advantage or permit promotion",
            "Minute-price outcomes are never substituted for executable net targets",
        ],
    }
    for arm in ("B", "C"):
        usable = []
        prior_end = -math.inf
        for row in train:
            d = row["descriptor"]
            if d["start_at"] <= prior_end:
                continue
            try:
                x = vector(d, arm)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                continue
            usable.append(
                {
                    "episode": row["episode"],
                    "record_id": row.get("record_id"),
                    "group": d["group_id"],
                    "x": x,
                    "at": d["cutoff"],
                    "end": d["horizon_at"],
                    "available_at": known_at(row),
                    "net_bps": row["executable_label"]["net_bps"],
                }
            )
            prior_end = d["horizon_at"]
        groups = {r["group"] for r in usable}
        candidate: dict[str, Any] = {
            "family": "memory_entry",
            "arm": arm,
            "name": "Numerical history" if arm == "B" else "Local context history",
            "status": "insufficient_data",
            "train_samples": len(groups),
            "test_samples": len(test),
        }
        result["candidate_group"].append(candidate)
        if len(groups) < 12 or len(calibration) < 6 or len(test) < 8:
            continue
        # Fixed chronological first 128, never selected by outcome. Report the declared cap.
        usable = usable[:128]
        means = [statistics.mean(x) for x in zip(*(r["x"] for r in usable), strict=True)]
        scales = [statistics.pstdev(x) for x in zip(*(r["x"] for r in usable), strict=True)]
        if any(s <= 1e-12 for s in scales):
            candidate["reason"] = "Unstable training-only normalization; no imputation"
            continue
        for row in usable:
            row["x"] = [(x - m) / s for x, m, s in zip(row["x"], means, scales, strict=True)]
        artifact: dict[str, Any] = {
            "version": VERSION,
            "family": "memory_entry",
            "arm": arm,
            "symbol": "BTCUSD",
            "contract": CONTRACT,
            "maximum_hold_seconds": 2700,
            "progress_seconds": 600,
            "lookback": 10,
            "means": means,
            "scales": scales,
            "library": usable,
            "train_end": train_end,
            "evidence_kind": plan.evidence_kind,
            "calibration": [{"count": 0, "probability": None} for _ in range(3)],
            "calibration_end": train_end,
        }
        artifact["sha256"] = digest(artifact)
        bins: list[list[int]] = [[], [], []]
        for row in calibration:
            p = predict(row["descriptor"], artifact, row["descriptor"]["cutoff"])
            if p["status"] == "supported":
                bins[min(2, int(p["raw_positive_fraction"] * 3))].append(
                    int(row["executable_label"]["net_bps"] > 0)
                )
        artifact["calibration"] = [
            {"count": len(b), "probability": (sum(b) + 1) / (len(b) + 2) if b else None}
            for b in bins
        ]
        artifact["calibration_end"] = plan.test_start - 3300
        artifact.pop("sha256")
        artifact["sha256"] = digest(artifact)
        predictions, scores = [], []
        for row in test:
            p = predict(row["descriptor"], artifact, row["descriptor"]["cutoff"])
            predictions.append(
                {
                    "episode": row["episode"],
                    "prediction": p,
                    "net_bps": row["executable_label"]["net_bps"],
                }
            )
            if p["profit_probability"] is not None:
                scores.append(
                    (p["profit_probability"] - int(row["executable_label"]["net_bps"] > 0)) ** 2
                )
        supported = [r for r in predictions if r["prediction"]["status"] == "supported"]
        candidate.update(
            status="research_artifact",
            artifact=artifact,
            predictions=predictions,
            metrics={
                "supported": len(supported),
                "queries": len(test),
                "brier": statistics.mean(scores) if scores else None,
                "mean_absolute_net_error_bps": statistics.mean(
                    abs(r["prediction"]["expected_net_bps"] - r["net_bps"]) for r in supported
                )
                if supported
                else None,
                "rejected_entries": sum(
                    r["prediction"]["action"] == "reject_entry" for r in predictions
                ),
                "missed_positive_opportunities": sum(
                    r["prediction"]["action"] == "reject_entry" and r["net_bps"] > 0
                    for r in predictions
                ),
            },
        )
        result.update(
            status="inconclusive",
            reason="Prototype retained; matched account effect and marginal costs unverified",
        )
    result["contributions"] = [
        {
            "from": "A",
            "to": "B",
            "paired_account_effect": None,
            "marginal_cost_usd": None,
            "conclusion": "inconclusive",
        },
        {
            "from": "B",
            "to": "C",
            "paired_account_effect": None,
            "marginal_cost_usd": None,
            "conclusion": "inconclusive",
        },
    ]
    result["small_baselines"] = {
        "A_no_filter": {
            "taken_trade_count": len(test),
            "mean_net_trade_bps": statistics.mean(r["executable_label"]["net_bps"] for r in test)
            if test
            else None,
        },
        "simple_direction_filter": {
            "rule": "Sum of as-seen ten returns is positive",
            "accepted": sum(sum(r["descriptor"]["returns_bps"]) > 0 for r in test),
        },
        "cash": {"trading_return": 0, "whole_account_return": None},
        "exposure": {
            "whole_account_return": None,
            "reason": "Matched executable exposure history unavailable",
        },
        "complex_model": "Deferred until small baselines and executable coverage justify it",
    }
    prior_actions: dict[str, bool] = {}
    for candidate, contribution in zip(
        result["candidate_group"], result["contributions"], strict=True
    ):
        predictions = candidate.get("predictions", [])
        contribution.update(
            changed_decisions=[
                r["episode"]
                for r in predictions
                if (r["prediction"]["action"] == "reject_entry")
                != prior_actions.get(r["episode"], False)
            ],
            forecast_coverage=len(
                [r for r in predictions if r["prediction"]["status"] == "supported"]
            ),
            opportunity_denominator=len(test),
            exposure=None,
            turnover=None,
            uncertainty="Matched account effect unavailable; correlations are not economic support",
        )
        prior_actions = {
            r["episode"]: r["prediction"]["action"] == "reject_entry" for r in predictions
        }
    result["resources"] = {
        "elapsed_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "paid_usd": "0",
        "marginal_operating_usd": None,
        "common_baseline_allocation": "CP7 allocation unchanged; costs already in net labels",
    }
    return result


def filtered_feature(
    base: dict[str, Any], descriptor: dict[str, Any], artifact: dict[str, Any], now: float
) -> dict[str, Any]:
    prediction = predict(descriptor, artifact, now)
    feature = deepcopy(base)
    feature["memory_evidence"] = prediction
    if prediction["status"] == "supported" and prediction["action"] == "reject_entry":
        feature.update(eligible=False, reason="Frozen memory entry filter rejected this proposal")
    return feature
