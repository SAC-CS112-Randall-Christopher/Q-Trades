"""Recorded representation availability, separate from market cutoff and later labels."""

import math
from typing import Any


def prediction_time(row: dict[str, Any], delay_seconds: float = 0) -> float:
    d = row["descriptor"]
    times = [float(d["cutoff"]), float(row.get("available_at", math.inf))]
    if "result_available_at" in row:
        times.append(float(row["result_available_at"]))
    if (
        not all(math.isfinite(t) for t in times)
        or not math.isfinite(delay_seconds)
        or delay_seconds < 0
    ):
        return math.inf
    return max(times) + delay_seconds


def actionable(row: dict[str, Any], delay_seconds: float = 0) -> bool:
    at = prediction_time(row, delay_seconds)
    expiry = row["descriptor"].get("expires_at")
    return isinstance(expiry, (int, float)) and math.isfinite(expiry) and at <= expiry
