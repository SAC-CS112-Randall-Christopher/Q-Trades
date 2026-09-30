"""One outcome-blind interval/concentration policy for separated historical support."""

import math
from typing import Any


def interval(row: dict[str, Any]) -> tuple[float, float]:
    d = row.get("descriptor", row)
    start = d.get("start_at", d.get("start"))
    if start is None:
        # Legacy library entries recorded cutoff/end but omitted lookback start.
        # Eleven minute bars conservatively cover 660s; never assume a point event.
        start = float(d["at"]) - 660
    end = d.get("horizon_at", d.get("end"))
    start, end = float(start), float(end)
    if not all(math.isfinite(x) for x in (start, end)) or start >= end:
        raise ValueError("Historical support interval is unavailable")
    return start, end


def separated(row: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    start, end = interval(row)
    d = row.get("descriptor", row)
    group = d.get("group_id", d.get("group"))
    for other in selected:
        o = other.get("descriptor", other)
        lo, hi = interval(other)
        if group == o.get("group_id", o.get("group")) or not (end < lo or start > hi):
            return False
    return True
