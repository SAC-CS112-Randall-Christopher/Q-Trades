"""Causal inspection overlays; never alter an account's frozen strategy."""

from decimal import Decimal
from typing import Any

from trading.paper_strategy import Bar


def overlays(bars: list[Bar], period: int = 20) -> dict[str, Any]:
    if not 2 <= period <= 100 or len(bars) > 600:
        raise ValueError("Chart calculation exceeds its declared bounds")
    points: list[dict[str, Any]] = []
    closes: list[Decimal] = []
    weighted = volume = Decimal(0)
    average: Decimal | None = None
    previous: int | None = None
    anchor: int | None = None
    alpha = Decimal(2) / (period + 1)
    for bar in bars:
        if previous is not None and bar.open_ms <= previous:
            raise ValueError("Chart candles must be ordered and unique")
        if not all(v.is_finite() for v in (bar.open, bar.high, bar.low, bar.close, bar.volume)):
            raise ValueError("Invalid chart candle")
        if not 0 < bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
            raise ValueError("Invalid chart candle range")
        if bar.volume < 0:
            raise ValueError("Invalid chart volume")
        if previous is None or bar.open_ms - previous != 60000:
            closes, average, weighted, volume = [], None, Decimal(0), Decimal(0)
            anchor = bar.open_ms
        previous = bar.open_ms
        closes.append(bar.close)
        closes = closes[-period:]
        weighted += (bar.high + bar.low + bar.close) / 3 * bar.volume
        volume += bar.volume
        point: dict[str, Any] = dict.fromkeys(("sma", "ema", "bb_upper", "bb_lower"))
        point.update(open_ms=bar.open_ms, vwap=str(weighted / volume) if volume else None)
        if len(closes) == period:
            mean = sum(closes, Decimal(0)) / period
            deviation = (sum(((v - mean) ** 2 for v in closes), Decimal(0)) / period).sqrt()
            average = mean if average is None else average + alpha * (bar.close - average)
            point.update(
                sma=str(mean),
                ema=str(average),
                bb_upper=str(mean + 2 * deviation),
                bb_lower=str(mean - 2 * deviation),
            )
        points.append(point)
    return {
        "version": "closed-minute-overlays-v1",
        "period": period,
        "bb_deviations": 2,
        "vwap_scope": "Typical-price volume-weighted average from recorded contiguous history",
        "vwap_anchor_ms": anchor,
        "ema_seed": "First contiguous period-close simple average",
        "gap_behavior": "Restart warmup and volume anchor after every missing minute",
        "financial_authority": False,
        "points": points,
    }
