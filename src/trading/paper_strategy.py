"""Frozen candidates and closed-bar features. No fitting to future observations."""

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Any

from trading.market import InvalidMarketData, decimal_string

D = Decimal
VARIANTS: dict[str, dict[str, Any]] = {
    "breakout-v1": {"lookback": 10, "volume_multiple": "2", "stop_atr": "1.5"},
    "responsive-v1": {"lookback": 7, "volume_multiple": "1.5", "stop_atr": "1.5"},
    "selective-v1": {"lookback": 15, "volume_multiple": "2.5", "stop_atr": "1.5"},
}


@dataclass(frozen=True)
class Bar:
    open_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_ms: int


def parse_bars(raw: Any, now: float) -> list[Bar]:
    if not isinstance(raw, list) or len(raw) > 1000:
        raise InvalidMarketData("Invalid candle response")
    result: list[Bar] = []
    for row in raw:
        if not isinstance(row, list) or len(row) < 7:
            raise InvalidMarketData("Incomplete candle")
        start, end = row[0], row[6]
        if type(start) is not int or type(end) is not int:
            raise InvalidMarketData("Invalid candle time")
        if start % 60000 or end != start + 59999:
            raise InvalidMarketData("Candle is not a complete UTC minute")
        o, h, low, c = [decimal_string(v) for v in row[1:5]]
        volume = decimal_string(row[5], positive=False)
        if not low <= min(o, c) <= max(o, c) <= h:
            raise InvalidMarketData("Candle range is inconsistent")
        if end >= int(now * 1000):
            continue  # The currently forming candle is never a feature.
        if result and start <= result[-1].open_ms:
            raise InvalidMarketData("Unordered or repeated candle")
        result.append(Bar(start, o, h, low, c, volume, end))
    return result


def ema(values: list[Decimal], period: int) -> list[Decimal]:
    value = sum(values[:period], D(0)) / period
    output = [value]
    alpha = D(2) / (period + 1)
    for item in values[period:]:
        value += alpha * (item - value)
        output.append(value)
    return output


def features(bars: list[Bar], now: float, version: str) -> dict[str, Any]:
    rules = VARIANTS[version]
    result: dict[str, Any] = {"version": version, "eligible": False}
    if len(bars) < 305:
        return {**result, "reason": "Warming up: need 60 complete five-minute bars"}
    bars = bars[-600:]
    if any(b.open_ms - a.open_ms != 60000 for a, b in zip(bars, bars[1:], strict=False)):
        return {**result, "reason": "Candle gap: entries paused until contiguous history"}
    last = bars[-1]
    result["bar_open_ms"] = last.open_ms
    if not 0 < now * 1000 - last.close_ms <= 90000:
        return {**result, "reason": "Closed candle is stale"}
    groups: dict[int, list[Bar]] = {}
    for bar in bars:
        groups.setdefault(bar.open_ms // 300000, []).append(bar)
    closes = [rows[-1].close for rows in groups.values() if len(rows) == 5]
    if len(closes) < 60:
        return {**result, "reason": "Five-minute trend warmup incomplete"}
    trend = ema(closes, 20)
    ranges = [
        max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
        for a, b in zip(bars, bars[1:], strict=False)
    ]
    atr = sum(ranges[:14], D(0)) / 14
    for value in ranges[14:]:
        atr = (atr * 13 + value) / 14
    lookback = int(rules["lookback"])
    preceding = bars[-lookback - 1 : -1]
    breakout = max(b.high for b in preceding)
    typical_volume = median(b.volume for b in preceding)
    volume_ratio = last.volume / typical_volume if typical_volume else D(0)
    trend_ok = closes[-1] > trend[-1] and trend[-1] > trend[-4]
    reasons = []
    if atr <= 0:
        reasons.append("No measurable volatility")
    if not trend_ok:
        reasons.append("Five-minute uptrend not confirmed")
    if last.close <= breakout:
        reasons.append("No closed-bar breakout")
    if typical_volume <= 0 or volume_ratio <= D(rules["volume_multiple"]):
        reasons.append("Volume confirmation absent")
    if last.close - breakout > D("1.5") * atr:
        reasons.append("Breakout already extended")
    return {
        **result,
        "eligible": not reasons,
        "reason": "; ".join(reasons) or "Confirmed breakout",
        "atr": str(atr),
        "close": str(last.close),
        "breakout": str(breakout),
        "volume_ratio": str(volume_ratio),
        "trend_up": trend_ok,
        "ema20_5m": str(trend[-1]),
        "closed_bars": len(bars),
    }
