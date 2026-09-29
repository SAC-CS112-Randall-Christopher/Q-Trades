"""Registered, bounded numerical experiment over observed quotes, never account fills."""

import hashlib
import json
import math
import statistics
from bisect import bisect_left
from collections import Counter
from decimal import Decimal
from typing import Any

EXPERIMENT_VERSION = "quote-ridge-v1"
FEATURES = {"momentum_1", "momentum_5", "volatility_5", "spread_bps"}
FEE = Decimal("0.001")
SLIPPAGE = Decimal("0.0002")
MAX_ROWS = 12000


def examples(rows: list[dict[str, Any]], feature: str, horizon: int) -> dict[str, Any]:
    """Feature at persistence time; entry/exit quotes must be observed strictly later.

    Minute samples cannot establish a fill or continuous execution coverage. This is
    a forecasting label under a fixed cost hurdle, not a paper-trade simulator.
    """
    if feature not in FEATURES or horizon not in (5, 15, 60):
        raise ValueError("Unregistered feature or horizon")
    if len(rows) > MAX_ROWS:
        raise ValueError("Dataset exceeds registered bound")
    quotes: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    seen: set[int] = set()
    for row in sorted(rows, key=lambda r: r["at"]):
        body = row["body"]
        if body["symbol"] != "BTCUSD":
            continue
        minute = int(body["minute"])
        if minute in seen:
            excluded["duplicate_minute"] += 1
            continue
        seen.add(minute)
        observed = float(body["last_observed_at"])
        available = float(row["at"])
        bid = Decimal(body["last_depth"]["bid"])
        ask = Decimal(body["last_depth"]["ask"])
        if not bid.is_finite() or not ask.is_finite() or bid <= 0 or ask < bid:
            excluded["invalid_quote"] += 1
            continue
        if not math.isfinite(observed) or not math.isfinite(available):
            excluded["invalid_time"] += 1
            continue
        if not 0 <= available - observed <= 90:
            excluded["late_or_future_record"] += 1
            continue
        quotes.append(
            {
                "id": row["id"],
                "available": available,
                "observed": observed,
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2,
                "minute": minute,
            }
        )
    quotes.sort(key=lambda q: q["observed"])
    times = [q["observed"] for q in quotes]
    samples: list[dict[str, Any]] = []
    for index, current in enumerate(quotes):
        if index < 5:
            excluded["warmup"] += 1
            continue
        history = quotes[index - 5 : index + 1]
        if any(
            b["minute"] - a["minute"] != 1
            for a, b in zip(history[:-1], history[1:], strict=True)
        ):
            excluded["feature_gap"] += 1
            continue
        if any(q["available"] > current["available"] for q in history):
            excluded["feature_not_available"] += 1
            continue
        entry_index = bisect_left(times, current["available"] + 0.001)
        if entry_index >= len(quotes):
            excluded["unmatured"] += 1
            continue
        entry = quotes[entry_index]
        exit_index = bisect_left(times, entry["observed"] + horizon * 60)
        if exit_index >= len(quotes):
            excluded["unmatured"] += 1
            continue
        end = quotes[exit_index]
        if entry["observed"] - current["available"] > 90 or (
            end["observed"] - entry["observed"] - horizon * 60 > 90
        ):
            excluded["label_gap"] += 1
            continue
        if feature == "momentum_1":
            value = float((current["mid"] / history[-2]["mid"] - 1) * 10000)
        elif feature == "momentum_5":
            value = float((current["mid"] / history[0]["mid"] - 1) * 10000)
        elif feature == "volatility_5":
            returns = [
                float((b["mid"] / a["mid"] - 1) * 10000)
                for a, b in zip(history[:-1], history[1:], strict=True)
            ]
            value = statistics.pstdev(returns)
        else:
            value = float((current["ask"] - current["bid"]) / current["mid"] * 10000)
        net = (
            end["bid"] * (1 - SLIPPAGE) * (1 - FEE) / (entry["ask"] * (1 + SLIPPAGE) * (1 + FEE))
            - 1
        ) * 10000
        samples.append(
            {
                "feature_event": current["id"],
                "entry_event": entry["id"],
                "exit_event": end["id"],
                "at": current["available"],
                "entry_at": entry["observed"],
                "end_at": end["observed"],
                "label_available_at": end["available"],
                "x": value,
                "y": float(net),
                "net_bps": str(net),
            }
        )
    return {"samples": samples, "excluded": dict(excluded), "quotes": len(quotes)}


def run_experiment(
    rows: list[dict[str, Any]],
    feature: str,
    horizon: int,
    prior_test_end: float = 0,
) -> dict[str, Any]:
    data_hash = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    built = examples(rows, feature, horizon)
    samples = built["samples"]
    report: dict[str, Any] = {
        "version": EXPERIMENT_VERSION,
        "dataset_sha256": data_hash,
        "feature": feature,
        "horizon_minutes": horizon,
        "symbol": "BTCUSD",
        "samples": len(samples),
        "excluded": built["excluded"],
        "cost_version": "quote-cost-v1-0.10pct-per-side-2bps-adverse",
        "limitations": [
            "Historical observed quote labels; no simulated fills or account returns.",
            "Minute samples cannot establish intraminute execution or queue position.",
            "Overlapping labels and a short market history limit independent evidence.",
            "One fixed ridge coefficient penalty; no hyperparameter search or primary promotion.",
        ],
    }
    if len(samples) < 300:
        return dict(report, status="insufficient_data", reason="Fewer than 300 matured examples")
    split_at = max(samples[int(len(samples) * 0.7)]["at"], prior_test_end + horizon * 60 + 1)
    train = [s for s in samples if s["label_available_at"] < split_at - horizon * 60]
    test = [s for s in samples if s["at"] >= split_at]
    report.update(train_samples=len(train), test_samples=len(test), split_at=split_at)
    if len(train) < 200 or len(test) < 50:
        return dict(
            report,
            status="insufficient_data",
            reason="Need 200 training and 50 new purged test examples",
        )
    x_mean = statistics.mean(s["x"] for s in train)
    x_scale = statistics.pstdev(s["x"] for s in train) or 1.0
    y_mean = statistics.mean(s["y"] for s in train)
    cross = sum(((s["x"] - x_mean) / x_scale) * (s["y"] - y_mean) for s in train)
    squares = sum(((s["x"] - x_mean) / x_scale) ** 2 for s in train)
    weight = cross / (squares + 1.0)
    predictions = [y_mean + weight * (s["x"] - x_mean) / x_scale for s in test]
    mse = statistics.mean((p - s["y"]) ** 2 for p, s in zip(predictions, test, strict=True))
    baseline_mse = statistics.mean((y_mean - s["y"]) ** 2 for s in test)
    selected = [s for p, s in zip(predictions, test, strict=True) if p > 0]
    report.update(
        status="completed",
        test_start=test[0]["at"],
        test_end=max(s["end_at"] for s in test),
        train_end=max(s["label_available_at"] for s in train),
        model={
            "x_mean": x_mean,
            "x_scale": x_scale,
            "intercept": y_mean,
            "weight": weight,
            "ridge_penalty": 1.0,
        },
        metrics={
            "model_mse_bps_squared": format(mse, ".8f"),
            "baseline_mse_bps_squared": format(baseline_mse, ".8f"),
            "mse_improvement_percent": format((1 - mse / baseline_mse) * 100, ".6f")
            if baseline_mse
            else "0",
            "positive_predictions": len(selected),
            "selected_mean_net_bps": format(statistics.mean(s["y"] for s in selected), ".8f")
            if selected
            else None,
        },
        eligible_for_forward_review=bool(
            mse < baseline_mse
            and len(selected) >= 30
            and statistics.mean(s["y"] for s in selected) > 0
        ),
        primary_changed=False,
    )
    return report
