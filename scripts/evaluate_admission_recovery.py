"""Finite offline policy fixtures plus summaries of two immutable local receipts.

No network, database, model, subprocess, scheduler or operating configuration.
Wall-clock retained windows are summarized, never replayed as monotonic traces.
"""

import argparse
import hashlib
import json
import math
import statistics
from collections import deque
from pathlib import Path
from typing import Any

from trading.engine_diagnostics import EngineWorkPressurePolicy


class BaselinePressurePolicy:
    """Offline reference for the accepted 6265240 observer, never a runtime gate.

    Keep its strict >100-ms/new-pass/4-of-20 trigger and >=1000-ms severe
    trigger, both renewing a 300-second hold. This reference retains historical
    comparisons after the production owner adopts the reviewed successor.
    """

    def __init__(self) -> None:
        self._loop_ms: deque[float] = deque(maxlen=20)
        self._constrained_until = 0.0
        self.qualifying_triggers = 0

    def observe_engine_work(self, elapsed_ms: float, now_mono: float) -> None:
        self._loop_ms.append(elapsed_ms)
        repeated = (
            elapsed_ms > 100
            and len(self._loop_ms) == 20
            and sum(value > 100 for value in self._loop_ms) >= 4
        )
        if repeated or elapsed_ms >= 1000:
            self._constrained_until = now_mono + 300
            self.qualifying_triggers += 1


def summarize_window(window: list[dict[str, Any]]) -> dict[str, Any]:
    if not window or len(window) > 20:
        raise ValueError("Expected one bounded retained current window, not stitched snapshots")
    durations = [sample["elapsed_ms"] for sample in window]
    stamps = [sample["at"] for sample in window]
    if any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0
        for value in durations + stamps
    ) or any(b <= a for a, b in zip(stamps, stamps[1:], strict=False)):
        raise ValueError("Invalid retained work observations; no recovery inferred")
    clean_tail = 0
    for duration in reversed(durations):
        if duration >= 500:
            break
        clean_tail += 1
    return {
        "samples": len(window),
        "target_exceedances_over100": sum(value > 100 for value in durations),
        "blocking_samples_at_or_above500": sum(value >= 500 for value in durations),
        "severe_samples": sum(value >= 1000 for value in durations),
        "median_ms": statistics.median(durations),
        "wall_clock_span_seconds": stamps[-1] - stamps[0],
        "sub500_suffix_samples": clean_tail,
        "candidate_recovery_evidence": (
            "insufficient_sub500_suffix_even_if_clock_and_coverage_were_valid"
            if clean_tail < 20
            else "unknown_monotonic_clock_and_prior_severity_not_retained"
        ),
        "candidate_admission_replayed": False,
        "coverage": "One retained window; no missing work or clock continuity inferred",
    }


def fixture_comparison(values: list[float | None], *, step: float = 0.5) -> dict[str, Any]:
    current = BaselinePressurePolicy()
    candidate = EngineWorkPressurePolicy()
    current_allows = candidate_allows = earlier_recovery = 0
    for index, duration in enumerate(values):
        now = 1000 + index * step
        if duration is not None:
            current.observe_engine_work(duration, now)
        candidate.observe(duration, now)
        a, b = now >= current._constrained_until, candidate.evaluate(now).pressure_allows
        current_allows += a
        candidate_allows += b
        earlier_recovery += b and not a
    return {
        "fixture_observations": len(values),
        "completed_work_observations": sum(value is not None for value in values),
        "step_seconds": step,
        "current_pressure_allows_at_observation": current_allows,
        "candidate_pressure_allows_at_observation": candidate_allows,
        "candidate_allows_while_current_pressure_blocks": earlier_recovery,
        "current_qualifying_trigger_count": current.qualifying_triggers,
        "final_current_pressure_allows": a,
        "final_candidate_pressure_allows": b,
    }


def load_receipt(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2:
        raise ValueError("Retained receipt exceeds bounded read budget")
    return json.loads(raw.decode("utf-8")), {
        "filename": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def evaluate(current_path: Path, earlier_path: Path) -> dict[str, Any]:
    current, current_identity = load_receipt(current_path)
    earlier, earlier_identity = load_receipt(earlier_path)
    guard = current["paper"]["performance"]["resource_guard"]
    old_guard = earlier["resource_guard"]
    return {
        "format": "qtrades-offline-admission-evaluation-v3",
        "base_commit": "6265240d64a932d987a763d106726675a1a18019",
        "candidate": "engine-work-pressure-v3",
        "new_operating_guard_checks": 0,
        "new_model_calls": 0,
        "original_attempt_consumed": False,
        "installed_policy_changed": False,
        "retained_inputs": [earlier_identity, current_identity],
        "retained_earlier": {
            "trigger_number": old_guard["last_trigger"]["trigger_number"],
            "trigger_at": old_guard["last_trigger"]["at"],
            "current_window": summarize_window(old_guard["current_window"]),
        },
        "retained_latest": {
            "guard_admitted": current["guard_admitted"],
            "trigger_number": guard["last_trigger"]["trigger_number"],
            "trigger_at": guard["last_trigger"]["at"],
            "trigger_slow_samples_retained": len(guard["last_trigger"]["slow_window"]),
            "trigger_total_samples": guard["last_trigger"]["window_samples"],
            "trigger_fast_samples_not_retained": True,
            "current_window": summarize_window(guard["current_window"]),
        },
        "fixtures": {
            "normal_work": fixture_comparison([50] * 100),
            "sub500_target_miss_burst": fixture_comparison([50] * 21 + [150] * 4 + [50] * 100),
            "blocking_burst_then_target_misses": fixture_comparison(
                [50] * 21 + [600] * 4 + [150] * 100
            ),
            "sustained_sub500_target_misses": fixture_comparison([150] * 200),
            "sustained_blocking_pressure": fixture_comparison([600] * 200),
            "severe_stall_then_calm": fixture_comparison([1000] + [50] * 601),
            "severe_stall_then_sub500_target_misses": fixture_comparison([1000] + [150] * 601),
            "missing_observation_then_recovery": fixture_comparison([50] * 21 + [None] + [50] * 21),
            "startup_before_minimum_coverage": fixture_comparison([50] * 20, step=0.1),
            "repeated_oscillation": fixture_comparison(
                [50] * 21 + [600] * 4 + ([150] * 19 + [600]) * 10
            ),
        },
        "interpretation": {
            "availability": "Counts at synthetic observation points; not elapsed availability",
            "baseline": "Offline pinned 6265240 pressure reference; not a reachable runtime guard",
            "coexistence_safety": (
                "Unmeasured; no trained model or active operating positions tested"
            ),
            "pressure_only": (
                "Does not represent complete guard, memory, inputs, storage or ownership"
            ),
            "retained_coverage": (
                "Two separate sparse windows; no uninterrupted trace reconstructed"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-receipt", type=Path, required=True)
    parser.add_argument("--earlier-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.current_receipt, args.earlier_receipt)
    # Exclusive creation preserves input receipts and every previous result.
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"Offline evaluation saved: {args.output}")


if __name__ == "__main__":
    main()
