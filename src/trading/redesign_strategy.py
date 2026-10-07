"""Frozen prospective hypotheses, not fitted models or evidence of profitability.

All entry signals use complete UTC five-minute bars made from at most 600
causal minute observations. Execution, funding and risk remain with the paper
engine. The ATR movement proxy is a scale check, not an expected return.
"""

import math
from decimal import Decimal
from statistics import median
from types import MappingProxyType
from typing import Any

from trading.paper_strategy import Bar, ema

D = Decimal
REDESIGN_VERSION = "original-account-redesign-v1"
MAXIMUM_HOLD_SECONDS = 21600
PROGRESS_SECONDS = 7200
STRATEGIES = MappingProxyType(
    {
        "cost-breakout-v1": "Confirmed trend breakout with volume, without an extended entry",
        "breakout-retest-v1": "First complete-bar retest after a prior range breakout",
        "trend-pullback-v1": "Bullish recovery from the moving average in an established uptrend",
        "vwap-reclaim-v1": "Recovery above the preceding hour's volume-weighted typical price",
        "range-fade-v1": "Bullish lower-range reversal while the moving average is relatively flat",
        "momentum-followthrough-v1": (
            "Three rising bullish bars with higher lows and renewed volume"
        ),
        "compression-breakout-v1": "Volume-backed escape from a recently compressed price range",
        "washout-rebound-v1": "Higher-low recovery after an unusually deep, high-volume down bar",
    }
)


def _invalid(version: str, reason: str) -> dict[str, Any]:
    return {"version": version, "eligible": False, "reason": reason}


def _aggregated(bars: list[Bar], now: float) -> tuple[list[Bar], str | None]:
    if not math.isfinite(now) or now <= 0:
        return [], "Invalid observation time"
    if len(bars) > 600:
        return [], "History exceeds the declared 600-minute bound"
    closed = [bar for bar in bars if bar.close_ms < now * 1000]
    for bar in closed:
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if (
            type(bar.open_ms) is not int
            or type(bar.close_ms) is not int
            or bar.open_ms % 60000
            or bar.close_ms != bar.open_ms + 59999
            or any(not value.is_finite() for value in values)
            or min(bar.open, bar.high, bar.low, bar.close) <= 0
            or bar.volume < 0
            or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        ):
            return [], "Invalid original minute observation"
    if any(b.open_ms - a.open_ms != 60000 for a, b in zip(closed, closed[1:], strict=False)):
        return [], "Candle gap or repeated/unordered minute: entries unavailable"
    if len(closed) < 305:
        return [], "Warming up: need 305 causal closed minute bars"
    if not 0 < now * 1000 - closed[-1].close_ms <= 90000:
        return [], "Latest closed minute is stale"
    groups: dict[int, list[Bar]] = {}
    for bar in closed:
        groups.setdefault(bar.open_ms // 300000, []).append(bar)
    result = [
        Bar(
            key * 300000,
            rows[0].open,
            max(bar.high for bar in rows),
            min(bar.low for bar in rows),
            rows[-1].close,
            sum((bar.volume for bar in rows), D(0)),
            key * 300000 + 299999,
        )
        for key, rows in groups.items()
        if len(rows) == 5 and rows[0].open_ms == key * 300000
    ]
    if len(result) < 60:
        return [], "Warming up: need 60 complete UTC five-minute bars"
    return result, None


def _atr(bars: list[Bar]) -> Decimal:
    ranges = [
        max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
        for a, b in zip(bars, bars[1:], strict=False)
    ]
    value = sum(ranges[:14], D(0)) / 14
    for item in ranges[14:]:
        value = (value * 13 + item) / 14
    return value


def features(bars: list[Bar], now: float, version: str) -> dict[str, Any]:
    """Evaluate one fixed entry hypothesis without execution or mutable learning.

    A signal repeats the same bar identity until the next five-minute closure.
    The caller must use that identity for once-per-bar decisions and check the
    movement proxy against the actual fee/slippage/spread observation separately.
    """
    if version not in STRATEGIES:
        return _invalid(version, "Unknown frozen redesign strategy")
    aggregated, reason = _aggregated(bars, now)
    if reason:
        return _invalid(version, reason)
    last, previous = aggregated[-1], aggregated[-2]
    prior = aggregated[-21:-1]
    typical_volume = median(bar.volume for bar in prior)
    atr = _atr(aggregated)
    if atr <= 0:
        return _invalid(version, "No measurable five-minute volatility")
    if typical_volume <= 0 or last.volume <= 0:
        return _invalid(version, "Positive current and preceding volume observations required")
    averages = ema([bar.close for bar in aggregated], 20)
    trend_up = averages[-2] > averages[-5] and last.close > averages[-1]
    bullish = last.close > last.open
    high, low = max(bar.high for bar in prior), min(bar.low for bar in prior)
    signal = False
    if version == "cost-breakout-v1":
        signal = (
            trend_up
            and last.close > high
            and last.close - high <= atr * D("0.75")
            and last.volume >= typical_volume * D("1.5")
        )
    elif version == "breakout-retest-v1":
        level = max(bar.high for bar in aggregated[-22:-2])
        signal = (
            trend_up
            and previous.close > level
            and level - atr * D("0.5") <= last.low <= level + atr * D("0.25")
            and last.close > level
            and bullish
            and last.volume >= typical_volume * D("0.5")
        )
    elif version == "trend-pullback-v1":
        signal = (
            trend_up
            and last.low <= averages[-2] + atr * D("0.25")
            and last.close > averages[-1] + atr * D("0.05")
            and bullish
        )
    elif version == "vwap-reclaim-v1":
        hour = aggregated[-13:-1]
        volume = sum((bar.volume for bar in hour), D(0))
        vwap = (
            sum(((bar.high + bar.low + bar.close) / 3 * bar.volume for bar in hour), D(0)) / volume
        )
        signal = (
            previous.close <= vwap < last.close
            and last.low <= vwap
            and bullish
            and last.volume >= typical_volume
        )
    elif version == "range-fade-v1":
        signal = (
            abs(averages[-1] - averages[-4]) <= atr * D("0.25")
            and high - low >= atr * 2
            and low - atr * D("0.5") <= last.low <= low + atr * D("0.25")
            and low + atr * D("0.25") < last.close < (high + low) / 2
            and bullish
        )
    elif version == "momentum-followthrough-v1":
        first = aggregated[-3]
        signal = (
            all(bar.close - bar.open > atr * D("0.25") for bar in (first, previous, last))
            and first.close < previous.close < last.close
            and first.low < previous.low < last.low
            and last.close >= last.low + (last.high - last.low) * D("0.7")
            and last.volume >= typical_volume * D("1.25")
        )
    elif version == "compression-breakout-v1":
        compressed = aggregated[-7:-1]
        earlier = aggregated[-21:-7]
        recent_range = sum((bar.high - bar.low for bar in compressed), D(0)) / 6
        earlier_range = sum((bar.high - bar.low for bar in earlier), D(0)) / 14
        signal = (
            0 < recent_range <= earlier_range * D("0.6")
            and max(bar.high for bar in compressed) - min(bar.low for bar in compressed)
            <= atr * D("1.5")
            and last.close > max(bar.high for bar in compressed)
            and last.high - last.low >= recent_range * D("1.5")
            and last.volume >= typical_volume * D("1.5")
        )
    elif version == "washout-rebound-v1":
        earlier = aggregated[-22:-2]
        earlier_volume = median(bar.volume for bar in earlier)
        signal = (
            previous.close < previous.open
            and previous.low < min(bar.low for bar in earlier) - atr * D("0.5")
            and earlier_volume > 0
            and previous.volume >= earlier_volume * 2
            and last.low >= previous.low
            and last.close > (previous.open + previous.close) / 2
            and bullish
        )
    movement = atr * D("1.5")
    return {
        "version": version,
        "redesign_version": REDESIGN_VERSION,
        "eligible": signal,
        "reason": STRATEGIES[version] if signal else "Frozen entry hypothesis is not present",
        "bar_open_ms": last.open_ms,
        "input_available_at": last.close_ms / 1000,
        "close": str(last.close),
        "atr": str(atr),
        "feature_seconds": 300,
        "closed_bars": len(aggregated),
        "movement_proxy": str(movement),
        "movement_proxy_bps": str(movement / last.close * 10000),
        "economics_basis": "ATR movement proxy only; no forecast or profitability claim",
        "maximum_hold_seconds": MAXIMUM_HOLD_SECONDS,
        "progress_seconds": PROGRESS_SECONDS,
    }
