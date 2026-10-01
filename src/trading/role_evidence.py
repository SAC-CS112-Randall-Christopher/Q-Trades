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
        "limits": "Correlated historical support; prospective account benefit unknown",
    }


def strategy_summary(strategy: dict[str, Any]) -> dict[str, Any]:
    result = dict(strategy)
    if strategy.get("entry_filter"):
        result["entry_filter"] = strategy["entry_filter"] | {
            "artifact": artifact_summary(strategy["entry_filter"]["artifact"]),
            "purpose": "Filter an eligible baseline entry; exits, sizing and risk unchanged",
        }
    return result


def method_summary(proposal: dict[str, Any]) -> dict[str, Any]:
    return proposal | {
        "strategy": strategy_summary(proposal["strategy"]),
        "reference": strategy_summary(proposal["reference"]),
        "method_sha256": fingerprint(proposal),
        "detail": "Selected task's frozen proposal; exact full method retained",
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
            "scope": "Full descriptor/input/neighbors retained with selected task",
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
            "scope": "Exact permitted bundle retained; last three per category shown",
        },
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
        "detail": "Exact scored event retained with selected task/lesson",
        "omitted_fields": sorted(set(body) - keys),
    }
