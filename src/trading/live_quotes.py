"""Small, read-only view of the paper worker's existing market observations."""

import time
from typing import Any

from trading.stream_feed import StreamFeed


def quote_snapshot(
    stream: StreamFeed,
    fallback: dict[str, dict[str, Any]],
    previous: dict[str, Any],
    running: bool,
    error: str | None,
) -> dict[str, Any]:
    # No venue requests, journal reads, captures, or execution-state updates here.
    fresh = stream.fresh_books()
    now, mono = time.time(), time.monotonic()
    rows = []
    for symbol, interval in list(stream.plan.items())[:8]:
        pushed = stream.books.get(symbol)
        polled = fallback.get(symbol)
        frame = fresh.get(symbol)
        if frame is None and polled and 0 <= mono - polled["received_mono"] <= 1:
            frame = polled
        if frame is None:
            retained = [value for value in (pushed, polled) if value]
            frame = max(retained, key=lambda value: value["received_mono"], default=None)

        reason = "Waiting for a market observation"
        age = remaining = None
        if frame:
            age = (mono - frame["received_mono"]) * 1000
            if frame["source"] == "binance.us-depth-websocket":
                threshold = 1000 if interval == 100 else 2500
                remaining = min(
                    threshold - frame["event_age_ms"] - frame["clock_uncertainty_ms"] - age,
                    (stream.clock.checked_mono + 180 - mono) * 1000,
                )
                if not stream.clock.valid(now, mono):
                    remaining = 0
                    reason = "Exchange clock is not validated"
                else:
                    reason = "WebSocket observation expired"
            else:
                # REST has a receipt time, never an invented exchange event time.
                remaining = 1000 - age
                reason = "REST observation expired"
            if age < 0:
                remaining = 0
                reason = "Observation clock is invalid"
            if symbol in previous and frame["book"].update_id < previous[symbol][0]:
                remaining = 0
                reason = "Book sequence is behind the paper worker"
        if not running or error:
            remaining = 0
            reason = error or "Paper worker is stopped"
        usable = frame is not None and remaining is not None and remaining > 0
        intervals = sorted(stream.stats.get(symbol, {}).get("intervals_ms", []))
        rows.append(
            {
                "symbol": symbol,
                "source": frame["source"] if frame else "unavailable",
                "state": "fresh" if usable else "stale" if frame else "unavailable",
                "reason": None if usable else reason,
                "bid": str(frame["book"].bids[0][0]) if frame else None,
                "ask": str(frame["book"].asks[0][0]) if frame else None,
                "book_update_id": frame["book"].update_id if frame else None,
                "observed_at": frame["observed"] if frame else None,
                "exchange_event_ms": frame.get("exchange_event_ms") if frame else None,
                "received_age_ms": round(max(0, age), 2) if age is not None else None,
                "valid_for_ms": max(0, remaining or 0),
                "interval_ms": interval,
                "interval_p50_ms": round(intervals[len(intervals) // 2], 2)
                if intervals
                else None,
            }
        )
    return {
        "enabled": True,
        "running": running,
        "error": error,
        "generated_at": now,
        "display_refresh_ms": 1000,
        "markets": rows,
        "omitted_markets": max(0, len(stream.plan) - len(rows)),
    }
