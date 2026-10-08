"""Compact role facts bound to retained artifacts; numerical owners keep full inputs."""

from typing import Any

from trading.experiment_registry import fingerprint


def artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    if artifact.get("retained"):
        return dict(artifact)
    return {
        "sha256": artifact["sha256"],
        "version": artifact["version"],
        "arm": artifact["arm"],
        "evidence_kind": artifact["evidence_kind"],
        "library_groups": len(artifact["library"]),
        "train_end": artifact["train_end"],
        "calibration_end": artifact["calibration_end"],
        "calibration_groups": sum(b["count"] for b in artifact["calibration"]),
        "normalization": "Frozen training only",
        "neighbors": 5,
        "minimum_groups": 5,
        "maximum_weight": 0.2,
        "limits": "Correlated history; prospective account benefit unknown",
    }


def strategy_summary(strategy: dict[str, Any]) -> dict[str, Any]:
    result = dict(strategy)
    if strategy.get("entry_filter"):
        result["entry_filter"] = strategy["entry_filter"] | {
            "artifact": artifact_summary(strategy["entry_filter"]["artifact"]),
            "purpose": "Baseline entry filter; exits/sizing/risk unchanged",
        }
    return result


def method_summary(proposal: dict[str, Any]) -> dict[str, Any]:
    return proposal | {
        "strategy": strategy_summary(proposal["strategy"]),
        "reference": strategy_summary(proposal["reference"]),
        "method_sha256": fingerprint(proposal),
        "detail": "Full frozen method retained in selected task",
    }


def feature_summary(feature: dict[str, Any]) -> dict[str, Any]:
    omitted = {"memory_input", "memory_descriptor", "memory_evidence"}
    result = {k: v for k, v in feature.items() if k not in omitted}
    if "memory_evidence" in feature:
        evidence = feature["memory_evidence"]
        result["memory_evidence"] = {
            k: evidence[k]
            for k in (
                "status",
                "action",
                "reason",
                "artifact_sha256",
                "horizon_seconds",
                "expected_net_bps",
                "profit_probability",
                "recognition_confidence",
                "distinct_groups",
                "distinct_days",
                "maximum_weight",
                "marginal_daily_usd",
                "cutoff",
                "available_at",
                "expires_at",
            )
            if k in evidence
        }
        result["detail"] = {
            "feature_sha256": fingerprint(feature),
            "scope": "Full descriptor/input/neighbors retained in task",
        }
    return result


def feature_set(features: dict[str, Any]) -> dict[str, Any]:
    summaries = {k: feature_summary(v) for k, v in features.items()}
    values = list(summaries.values())
    shared = (
        {
            k: v
            for k, v in values[0].items()
            if all(k in other and other[k] == v for other in values[1:])
        }
        if values
        else {}
    )
    return {
        "shared": shared,
        "by_capability": {
            k: {field: v for field, v in value.items() if field not in shared}
            for k, value in summaries.items()
        },
    }


def bundle_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    evidence = bundle.get("evidence", {})
    return {k: bundle[k] for k in ("as_of", "current_inputs", "uncertainty") if k in bundle} | {
        "evidence": {
            key: {
                "total": len(values),
                "shown": min(3, len(values)),
                "latest": [
                    {
                        k: v
                        for k, v in item.items()
                        if k not in {"trial_id", "proposal_id", "episode", "archive_type", "sha256"}
                    }
                    for item in values[-3:]
                ],
                "omitted": max(0, len(values) - 3),
            }
            for key, values in evidence.items()
        },
        "detail": {
            "sha256": fingerprint(bundle),
            "scope": "Full bundle retained; latest three/category shown",
        },
    }


def pattern_packet(summary: dict[str, Any]) -> dict[str, Any]:
    """Bounded wire facts; the exact full preparation remains in the task context."""
    return {
        "finding_sha256": summary["finding_sha256"],
        "original_event": {
            k: summary["original_event"][k]
            for k in (
                "kind",
                "bar_close_ms",
                "level_price",
                "volume_confirmed",
                "volume_ratio",
                "reason",
            )
        },
        "coverage_columns": ["timeframe", "observed_bars", "expected_bars", "missing_bars"],
        "coverage": [
            [row.get(k) for k in ("timeframe", "observed_bars", "expected_bars", "missing_bars")]
            for row in summary["coverage"]
        ],
        "native_proof": {
            k: summary["native_proof"][k]
            for k in ("archive_verified", "recognition_rows", "contiguous_relevant_window")
        },
        "verification_at": summary["prepared_at"],
        "detail_sha256": fingerprint(summary),
        "detail": "Original local proof/coverage retained; historical motivation only",
    }


def pattern_controls(fixed: dict[str, Any]) -> dict[str, Any]:
    candidate, reference = fixed["candidate"], fixed["reference"]
    return {
        "candidate": candidate["proposal"]["strategy"]["family"],
        "reference": reference["proposal"]["strategy"]["family"],
        "unchanged": candidate["unchanged"],
        "entry": {"candidate": candidate["entry"], "reference": reference["entry"]},
        "exit": {k: v for k, v in candidate["exit"].items() if k != "protection"},
        "costs": candidate["costs"],
        "evaluation": candidate["evaluation"],
        "inapplicable_compatibility_fields": candidate["inapplicable_compatibility_fields"],
        "fixed_inputs": {
            k: v for k, v in candidate["fixed_method"]["inputs"].items() if isinstance(v, int)
        },
        "source_sha256": fixed["source_sha256"],
        "current_inputs": fixed["current_inputs"],
        "detail_sha256": fingerprint(fixed),
    }


def pattern_followup_controls(fixed: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    """Identify the executed method; full fixed controls remain in the original task."""
    return {
        "candidate": fixed["candidate"]["proposal"]["strategy"]["family"],
        "reference": fixed["reference"]["proposal"]["strategy"]["family"],
        "proposal_id": proposal["request_id"],
        "method_sha256": fingerprint(proposal),
        "detail_sha256": fingerprint(fixed),
        "detail": "Original fixed controls and implementation hashes retained in task context",
    }


def pattern_followup_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    """Preserve every scored fact, sharing only exactly equal execution-sample fields."""
    body = dict(outcome["body"])
    candidate, reference = body.get("candidate_sample"), body.get("reference_sample")
    if (
        isinstance(candidate, dict)
        and isinstance(reference, dict)
        and "execution_samples" not in body
    ):
        common = {
            key: value
            for key, value in candidate.items()
            if key in reference and fingerprint(value) == fingerprint(reference[key])
        }
        body.pop("candidate_sample")
        body.pop("reference_sample")
        body["execution_samples"] = {
            "common": common,
            "candidate": {key: value for key, value in candidate.items() if key not in common},
            "reference": {key: value for key, value in reference.items() if key not in common},
            "encoding": "Each original sample is common overlaid by its named fields",
        }
    return {
        "id": outcome["id"],
        "at": outcome["at"],
        "body": body,
        "source_sha256": fingerprint(outcome),
        "detail": "Full scored event retained in task/lesson; no scored fields omitted",
    }


def pattern_feature(feature: dict[str, Any]) -> dict[str, Any]:
    keys = ("eligible", "reason", "atr", "modeled_hurdle_bps", "cost_gate")
    return {key: feature[key] for key in keys if key in feature} | {
        "detail_sha256": fingerprint(feature),
    }


def pattern_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    """Native motivation is distinct from subsequent executable comparison inputs."""
    finding = receipt["finding"]
    native = finding["native_proof"]
    event = finding["original_event"]
    return {
        "preparation_request_id": receipt["request_id"],
        "issued_bundle_sha256": receipt["issued_bundle_sha256"],
        "finding_sha256": receipt["finding_sha256"],
        "selection": finding["selection"],
        "campaign_id": finding["campaign_id"],
        "captured_at": finding["captured_at"],
        "prepared_at": receipt["prepared_at"],
        "original_event": {
            key: event[key]
            for key in (
                "id",
                "kind",
                "bar_open_ms",
                "bar_close_ms",
                "level_id",
                "level_price",
                "volume_confirmed",
                "volume_ratio",
                "reason",
            )
            if key in event
        },
        "coverage": finding["coverage"],
        "native_proof": {
            key: native[key]
            for key in (
                "archive_verified",
                "recognition_rows",
                "pivot_rows",
                "contiguous_relevant_window",
                "recognition_start_ms",
                "recognition_end_ms",
                "input_window_sha256",
                "pivot_sha256",
                "coverage_claim",
            )
        },
        "mapping": receipt["mapping"],
        "scope": (
            "Preparation-time native verification; historical recognition motivates a distinct "
            "fixed v4 hypothesis. Current numerical inputs/admission are separate."
        ),
        "financial_authority": False,
    }


def outcome_summary(outcome: dict[str, Any]) -> dict[str, Any]:
    body = outcome["body"]
    keys = {
        "trial_id",
        "proposal_id",
        "outcome",
        "reason",
        "available_at",
        "window_start",
        "window_end",
        "net_after_operating_usd",
        "delta_usd",
        "passive_usd",
        "cash_usd",
        "operating_each_usd",
        "component_operating_usd",
        "fees_treatment",
        "coverage_seconds",
        "qualification",
        "coverage",
        "exposure",
        "drawdown",
        "closed",
    }
    return {
        "id": outcome["id"],
        "at": outcome["at"],
        "body": {k: v for k, v in body.items() if k in keys},
        "source_sha256": fingerprint(outcome),
        "detail": "Full scored event retained in task/lesson",
        "omitted_fields": sorted(set(body) - keys),
    }
