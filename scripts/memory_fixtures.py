"""Declared synthetic estimator data; not captured venue or executable-return proof."""

import math
import time

from trading.experiment_registry import ExperimentPlan


def memory_fixture():
    now = time.time()
    plan = ExperimentPlan(
        request_id="memory-quality-fixture",
        name="Memory quality QA",
        mechanism="Frozen comparable history might improve entry quality.",
        falsification="Retain insufficient and negative account evidence.",
        experiment_mode="memory_entry",
        horizon_minutes=45,
        test_start=now - 80000,
        test_end=now - 30,
        as_of=now,
        evidence_kind="synthetic_qa",
    )
    cal = plan.test_start - 7 * 86400
    times = [cal - 70000 + i * 5000 for i in range(12)]
    times += [cal + 5000 + i * 5000 for i in range(6)]
    times += [plan.test_start + 1000 + i * 5000 for i in range(8)]
    rows = []
    for i, at in enumerate(times):
        phase = i % 6
        d = {
            "status": "available",
            "cutoff": at,
            "start_at": at - 600,
            "horizon_at": at + 2700,
            "expires_at": at + 90,
            "group_id": f"BTCUSD:{int(at // 3300)}",
            "data_mode": "synthetic",
            "returns_bps": [math.sin(phase + j) + j * 0.2 for j in range(10)],
            "volatility_bps": 1 + phase * 0.1,
            "context": {
                "book": {
                    "spread_bps": str(1 + phase * 0.1),
                    "visible_depth_imbalance": str(math.sin(phase) * 0.2),
                }
            },
        }
        rows.append(
            {
                "episode": f"episode-{i}",
                "available_at": at,
                "descriptor": d,
                "executable_label": {
                    "status": "available",
                    "version": "executed-trade-net-v1",
                    "horizon_seconds": 2700,
                    "available_at": at + 2701,
                    "net_bps": 20.0 if i % 3 else -40.0,
                },
            }
        )
    return plan, rows
