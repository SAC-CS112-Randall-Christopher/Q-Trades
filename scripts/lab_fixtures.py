"""Explicit synthetic QA observations, never a production fallback."""

import math

from trading.experiment_registry import PREFLIGHT_END


def synthetic_rows(count=1200, start=None):
    start = int((PREFLIGHT_END + 3000) // 60) * 60 if start is None else start
    rows = []
    for i in range(count):
        mid = 100 + i * 0.015 + math.sin(i / 17) * 1.5 + math.sin(i / 73) * 0.3
        at = float(start + (i + 1) * 60)
        rows.append(
            {
                "id": i + 1,
                "at": at,
                "body": {
                    "symbol": "BTCUSD",
                    "minute": (start // 60) + i,
                    "last_observed_at": at - 1,
                    "synthetic_qa": True,
                    "last_depth": {"bid": str(mid - 0.01), "ask": str(mid + 0.01)},
                },
            }
        )
    return rows
