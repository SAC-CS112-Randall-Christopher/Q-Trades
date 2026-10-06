"""Frozen, distinct mechanisms and small numerical artifacts; predictions grant no orders."""

import math
import statistics
from decimal import Decimal
from typing import Any

from trading.experiment_registry import fingerprint
from trading.research_experiment import FEE, SLIPPAGE, examples

FAMILIES: dict[str, dict[str, Any]] = {
    "slow_trend": {
        "name": "Slower trend / momentum",
        "lookback": 60,
        "horizon_minutes": 60,
        "mechanism": "Persistent direction may outlast short-lived noise and execution costs.",
        "failure_regimes": "Choppy reversals, long flat periods and gap risk.",
        "rule": "Positive one-hour direction; cost-adjusted fitted forecast must also be positive.",
    },
    "volatility_breakout": {
        "name": "Volatility expansion",
        "lookback": 20,
        "horizon_minutes": 15,
        "mechanism": "A directional move beyond recent volatility may continue as a range expands.",
        "failure_regimes": "False breaks, spread expansion, fast reversals and thin books.",
        "rule": "Direction exceeds twice recent volatility; fitted forecast exceeds costs.",
    },
    "range_reversion": {
        "name": "Range-conditioned reversion",
        "lookback": 20,
        "horizon_minutes": 15,
        "mechanism": "A small negative excursion may revert in an otherwise stable range.",
        "failure_regimes": "Persistent downtrends, structural breaks and news gaps.",
        "rule": "Buy a negative excursion inside the range gate and above the forecast hurdle.",
    },
}
VERSION = "distinct-numerical-v1"


def observation_rows(rows: list[dict[str, Any]], as_of: float) -> list[dict[str, Any]]:
    if len(rows) > 12000:
        raise ValueError("Candidate input exceeds its registered bound")
    result = []
    seen = set()
    for row in sorted(rows, key=lambda r: (r["at"], r["id"])):
        b = row["body"]
        if b["symbol"] != "BTCUSD" or row["at"] > as_of:
            continue
        minute = int(b["minute"])
        if minute in seen:
            continue  # A later revision cannot replace the originally available observation.
        seen.add(minute)
        at, observed = float(row["at"]), float(b["last_observed_at"])
        bid, ask = Decimal(b["last_depth"]["bid"]), Decimal(b["last_depth"]["ask"])
        if not all(math.isfinite(x) for x in (at, observed)) or not 0 <= at - observed <= 90:
            continue
        if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
            continue
        result.append(
            {
                "id": row["id"],
                "at": at,
                "observed": observed,
                "minute": minute,
                "mid": float((bid + ask) / 2),
            }
        )
    return sorted(result, key=lambda q: q["minute"])


def feature_value(
    history: list[dict[str, Any]],
    family: str,
    *,
    lookback: int | None = None,
    interval_minutes: int = 1,
) -> float | None:
    if type(interval_minutes) is not int or interval_minutes not in {1, 5, 15}:
        raise ValueError("Feature sampling must be a declared one/five/fifteen-minute interval")
    lookback = FAMILIES[family]["lookback"] if lookback is None else lookback
    if len(history) < lookback + 1:
        return None
    tail = history[-lookback - 1 :]
    if any(
        b["minute"] - a["minute"] != interval_minutes or a["at"] > tail[-1]["at"]
        for a, b in zip(tail, tail[1:], strict=False)
    ):
        return None
    direction = (tail[-1]["mid"] / tail[0]["mid"] - 1) * 10000
    if family == "slow_trend":
        return float(direction)
    returns = [(b["mid"] / a["mid"] - 1) * 10000 for a, b in zip(tail, tail[1:], strict=False)]
    volatility = statistics.pstdev(returns)
    if family == "volatility_breakout":
        return float(max(0.0, direction - 2 * volatility))
    return float(-direction) if abs(direction) <= max(10.0, 5 * volatility) else 0.0


def family_result(
    rows: list[dict[str, Any]], family: str, start: float, end: float, as_of: float
) -> dict[str, Any]:
    config = FAMILIES[family]
    built = examples(rows, "momentum_5", config["horizon_minutes"])
    quotes = observation_rows(rows, as_of)
    features: dict[int, float] = {}
    for i, quote in enumerate(quotes):
        value = feature_value(quotes[max(0, i - config["lookback"]) : i + 1], family)
        if value is not None:
            features[quote["id"]] = value
    samples = [
        dict(s, x=features[s["feature_event"]])
        for s in built["samples"]
        if s["feature_event"] in features
    ]
    train = [s for s in samples if s["label_available_at"] < start - config["horizon_minutes"] * 60]
    test = [s for s in samples if s["at"] >= start and s["label_available_at"] <= end]
    report: dict[str, Any] = {
        "family": family,
        **config,
        "train_samples": len(train),
        "test_samples": len(test),
        "excluded": built["excluded"],
        "status": "insufficient_data",
        "decision": "reject",
    }
    if len(train) < 200 or len(test) < 50:
        return dict(report, reason="Need 200 training and 50 untouched matured test examples")
    mean = statistics.mean(s["x"] for s in train)
    scale = statistics.pstdev(s["x"] for s in train) or 1.0
    intercept = statistics.mean(s["y"] for s in train)
    z = [(s["x"] - mean) / scale for s in train]
    weight = sum(x * (s["y"] - intercept) for x, s in zip(z, train, strict=True)) / (
        sum(x * x for x in z) + 1.0
    )
    artifact: dict[str, Any] = {
        "version": VERSION,
        "family": family,
        "symbol": "BTCUSD",
        "lookback": config["lookback"],
        "horizon_minutes": config["horizon_minutes"],
        "mean": mean,
        "scale": scale,
        "intercept": intercept,
        "weight": weight,
        "ridge_penalty": 1.0,
        "input_version": "observed-minute-mid-v1",
        "train_end": max(s["label_available_at"] for s in train),
        "fees_per_side": str(FEE),
        "slippage_per_side": str(SLIPPAGE),
        "risk_envelope": "existing-cash-only-hard-stop-v1",
        "entry_prediction_bps": 0.0,
        "stop_atr": "1.5",
        "progress_seconds": 600,
        "maximum_hold_seconds": min(3600, config["horizon_minutes"] * 60),
    }
    artifact["sha256"] = fingerprint(artifact)
    predictions = [intercept + weight * (s["x"] - mean) / scale for s in test]
    chosen = [
        s for s, prediction in zip(test, predictions, strict=True) if s["x"] > 0 and prediction > 0
    ]
    # Nonoverlapping label blocks prevent treating each correlated minute as a sample.
    blocks = []
    last = -math.inf
    for s in chosen:
        if s["at"] > last:
            blocks.append(s["y"])
            last = s["label_available_at"]
    uncertainty = (statistics.stdev(blocks) / math.sqrt(len(blocks))) if len(blocks) >= 2 else None
    mse = statistics.mean((p - s["y"]) ** 2 for p, s in zip(predictions, test, strict=True))
    control = statistics.mean((intercept - s["y"]) ** 2 for s in test)
    trials = []
    for threshold in (0.0, 5.0, 10.0):
        selected = [
            s["y"] for s, p in zip(test, predictions, strict=True) if s["x"] > 0 and p > threshold
        ]
        trials.append(
            {
                "forecast_hurdle_bps": threshold,
                "selections": len(selected),
                "mean_net_bps": statistics.mean(selected) if selected else None,
                "purpose": "Predeclared sensitivity, never a replacement for the frozen rule",
            }
        )
    return {
        **report,
        "status": "completed",
        "artifact": artifact,
        "decision": "prospective_exploration_only",
        "metrics": {
            "model_mse_bps_squared": mse,
            "constant_baseline_mse_bps_squared": control,
            "rule_only_selections": sum(s["x"] > 0 for s in test),
            "fitted_selections": len(chosen),
            "nonoverlapping_label_blocks": len(blocks),
            "mean_selected_net_bps": statistics.mean(s["y"] for s in chosen) if chosen else None,
            "descriptive_block_standard_error_bps": uncertainty,
            "doubled_cost_mean_bps": statistics.mean(s["y"] - 24 for s in chosen)
            if chosen
            else None,
            "cash_control_net_bps": 0,
            "fee_currency": "USD",
        },
        "parameter_trials": trials,
        "qualification": (
            "Not qualified; common holdout and correlated trials count as one search group"
        ),
        "execution_replay": (
            "Unavailable: minute quotes do not retain price-level books or complete fills"
        ),
        "small_account_feasibility": (
            "Forward checks enforce fees, precision and displayed depth for $50/$100"
        ),
        "primary_changed": False,
    }


def evaluate_families(
    rows: list[dict[str, Any]], start: float, end: float, as_of: float
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "status": "completed",
        "decision": "prospective_exploration_only",
        "candidate_group": [family_result(rows, family, start, end, as_of) for family in FAMILIES],
        "selection_treatment": (
            "Three families and nine threshold trials are one predeclared search group"
        ),
        "independent_validation": False,
        "eligible_for_forward_review": False,
        "next_action": (
            "Inspect retained results; exploratory forward accounts "
            "require an explicit frozen admission"
        ),
        "limitations": [
            "Quote labels are not simulated account returns.",
            "Only BTC/USD with original availability; rotation history is unavailable.",
            "Block errors are descriptive; short history and selection prevent significance.",
        ],
    }


def validate_artifact(artifact: dict[str, Any]) -> None:
    if not isinstance(artifact, dict):
        raise ValueError("Frozen artifact is unavailable")
    from trading.account_purpose import require_research_provenance

    require_research_provenance(artifact)
    if artifact.get("version") == "memory-entry-v1":
        from trading.memory_quality import validate_artifact as validate_memory

        validate_memory(artifact)
        return
    body = {k: v for k, v in artifact.items() if k != "sha256"}
    if fingerprint(body) != artifact.get("sha256") or artifact.get("version") != VERSION:
        raise ValueError("Frozen artifact fingerprint/version mismatch")
    family = artifact.get("family")
    if not isinstance(family, str):
        raise ValueError("Unregistered numerical artifact")
    config = FAMILIES.get(family)
    if (
        config is None
        or artifact.get("symbol") != "BTCUSD"
        or artifact.get("lookback") != config["lookback"]
    ):
        raise ValueError("Unregistered numerical artifact")
    fixed = {
        "horizon_minutes": config["horizon_minutes"],
        "ridge_penalty": 1.0,
        "input_version": "observed-minute-mid-v1",
        "fees_per_side": str(FEE),
        "slippage_per_side": str(SLIPPAGE),
        "risk_envelope": "existing-cash-only-hard-stop-v1",
        "entry_prediction_bps": 0.0,
        "stop_atr": "1.5",
        "progress_seconds": 600,
        "maximum_hold_seconds": min(3600, config["horizon_minutes"] * 60),
    }
    if any(type(artifact.get(k)) is not type(v) or artifact.get(k) != v for k, v in fixed.items()):
        raise ValueError("Frozen numerical timing, cost or risk contract changed")
    if (
        not all(
            type(artifact.get(k)) in (int, float) and math.isfinite(artifact[k])
            for k in ("mean", "scale", "intercept", "weight", "train_end")
        )
        or artifact["scale"] <= 0
        or artifact["train_end"] <= 0
    ):
        raise ValueError("Numerical artifact is unavailable")


def signal(
    rows: list[dict[str, Any]], now: float, artifact: dict[str, Any], admitted: float
) -> dict[str, Any]:
    validate_artifact(artifact)
    result: dict[str, Any] = {
        "eligible": False,
        "version": "numeric-" + artifact["sha256"][:24],
        "reason": "Numerical input warming up or unavailable",
    }
    quotes = observation_rows(rows, now)
    if not quotes:
        return result
    last = quotes[-1]
    value = feature_value(quotes, artifact["family"])
    result["bar_open_ms"] = last["minute"] * 60000
    if value is None or not 0 <= now - last["at"] <= 90 or last["at"] <= admitted:
        return result
    prediction = (
        artifact["intercept"] + artifact["weight"] * (value - artifact["mean"]) / artifact["scale"]
    )
    mids = [Decimal(str(q["mid"])) for q in quotes[-15:]]
    atr = sum((abs(b - a) for a, b in zip(mids, mids[1:], strict=False)), Decimal(0)) / max(
        1, len(mids) - 1
    )
    return {
        **result,
        "eligible": value > 0 and prediction > 0 and atr > 0,
        "reason": "Frozen numerical forecast clears the cost hurdle"
        if value > 0 and prediction > 0
        else "Frozen numerical no-trade rule",
        "atr": str(atr),
        "prediction_net_bps": prediction,
        "artifact_sha256": artifact["sha256"],
        "family": artifact["family"],
        "input_available_at": last["at"],
        "evidence": "Prospective exploratory signal; deterministic risk checks still apply",
    }
