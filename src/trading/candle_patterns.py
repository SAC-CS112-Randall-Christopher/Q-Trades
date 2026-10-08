"""Bounded descriptive OHLCV analytics; never an execution or research authority."""

from collections import deque
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from math import isfinite
from statistics import median
from typing import Any

from trading.market import InvalidMarketData
from trading.paper_strategy import Bar

VERSION = "candle-patterns-v1"
TIMEFRAMES = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
MAX_CANDLES = 5000
MAX_ZONES = 12
MAX_PATTERNS = 60
SMA_PERIODS = (10, 50, 100)
VWAP_WINDOW = 50
VOLUME_WINDOW = 20
VOLUME_CONFIRMATION = Decimal("1.5")
ZONE_HALF_WIDTH = Decimal("0.0015")
RETEST_CANDLES = 10


@dataclass
class _Zone:
    id: str
    kind: str
    price: Decimal
    low: Decimal
    high: Decimal
    confirmed_at_ms: int
    last_touch_ms: int
    touches: int = 1
    in_visit: bool = False
    breakout_ms: int | None = None
    away_after_breakout: bool = False


def _number(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _validate(bars: list[Bar], timeframe: str, now: float) -> int:
    if not isinstance(timeframe, str) or timeframe not in TIMEFRAMES:
        raise InvalidMarketData("Unsupported candle analysis timeframe")
    if type(now) not in (int, float) or not isfinite(now) or now < 0:
        raise InvalidMarketData("Invalid candle analysis observation time")
    if not isinstance(bars, list) or len(bars) > MAX_CANDLES:
        raise InvalidMarketData("Candle analysis permits at most 5000 native candles")
    interval = TIMEFRAMES[timeframe] * 1000
    previous: Bar | None = None
    for bar in bars:
        if not isinstance(bar, Bar):
            raise InvalidMarketData("Candle analysis requires native Bar values")
        if (
            type(bar.open_ms) is not int
            or type(bar.close_ms) is not int
            or bar.open_ms < 0
            or bar.open_ms % interval
            or bar.close_ms != bar.open_ms + interval - 1
        ):
            raise InvalidMarketData("Candle is not a complete aligned native interval")
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if any(
            not isinstance(value, Decimal)
            or not value.is_finite()
            or len(str(value)) > 64
            or abs(value.adjusted()) > 40
            for value in values
        ):
            raise InvalidMarketData("Candle prices and volume require bounded finite Decimals")
        if (
            bar.low <= 0
            or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
            or bar.volume < 0
        ):
            raise InvalidMarketData("Candle OHLC range or volume is inconsistent")
        if bar.close_ms >= now * 1000:
            raise InvalidMarketData("Forming or future candles cannot be analyzed")
        if previous is not None and bar.open_ms <= previous.open_ms:
            raise InvalidMarketData("Unordered or duplicate candle")
        previous = bar
    return interval


def _volume_ratio(bar: Bar, preceding: deque[Decimal]) -> Decimal | None:
    if len(preceding) != VOLUME_WINDOW or bar.volume <= 0 or any(v <= 0 for v in preceding):
        return None
    baseline = median(preceding)
    return bar.volume / baseline


def _pattern(kind: str, bar: Bar, zone: _Zone, ratio: Decimal | None) -> dict[str, Any]:
    reasons = {
        "support_bounce": "Separate visit to known support; bullish close above the zone",
        "resistance_breakout": (
            "Previous close at or below known resistance; closed candle above the zone"
        ),
        "breakout_retest": (
            "Earlier breakout and a full candle above the zone; later bullish retest holds"
        ),
    }
    volume = (
        "previous-20 volume baseline unavailable"
        if ratio is None
        else f"volume {ratio} times the preceding-20 median"
    )
    return {
        "id": f"{kind}:{bar.open_ms}:{zone.id}",
        "kind": kind,
        "bar_open_ms": bar.open_ms,
        "level_id": zone.id,
        "level_price": str(zone.price),
        "volume_ratio": _number(ratio),
        "volume_confirmed": None if ratio is None else ratio >= VOLUME_CONFIRMATION,
        "reason": f"{reasons[kind]}; {volume}. Descriptive, not a trade instruction.",
    }


def _visit(
    zone: _Zone, bar: Bar, previous: Bar, ratio: Decimal | None, interval: int
) -> list[dict[str, Any]]:
    overlaps = bar.low <= zone.high and bar.high >= zone.low
    separate = overlaps and not zone.in_visit
    if separate:
        zone.touches += 1
    if overlaps:
        zone.last_touch_ms = bar.open_ms
    zone.in_visit = overlaps
    found = []
    if zone.kind == "support":
        if (
            separate
            and previous.low > zone.high
            and bar.low >= zone.low
            and bar.close > zone.high
            and bar.close > bar.open
        ):
            found.append(_pattern("support_bounce", bar, zone, ratio))
        return found
    if zone.breakout_ms is not None:
        expired = bar.open_ms - zone.breakout_ms > RETEST_CANDLES * interval
        if expired or bar.close < zone.low:
            zone.breakout_ms = None
            zone.away_after_breakout = False
        elif (
            separate
            and zone.away_after_breakout
            and bar.open_ms > zone.breakout_ms
            and bar.low >= zone.low
            and bar.close > zone.high
            and bar.close > bar.open
        ):
            found.append(_pattern("breakout_retest", bar, zone, ratio))
            zone.breakout_ms = None
            zone.away_after_breakout = False
        elif bar.low > zone.high:
            zone.away_after_breakout = True
    if previous.close <= zone.high and bar.close > zone.high:
        found.append(_pattern("resistance_breakout", bar, zone, ratio))
        zone.breakout_ms = bar.open_ms
        zone.away_after_breakout = bar.low > zone.high
    return found


def _confirm_zones(recent: deque[Bar], zones: deque[_Zone]) -> None:
    if len(recent) != 5:
        return
    rows = list(recent)
    pivot, confirmed = rows[2], rows[4]
    others = rows[:2] + rows[3:]
    for kind, price, qualifies in (
        ("support", pivot.low, all(pivot.low < other.low for other in others)),
        ("resistance", pivot.high, all(pivot.high > other.high for other in others)),
    ):
        if not qualifies or any(z.kind == kind and z.low <= price <= z.high for z in zones):
            continue
        low, high = price * (1 - ZONE_HALF_WIDTH), price * (1 + ZONE_HALF_WIDTH)
        touching = True
        touches = 1
        last_touch_ms = pivot.open_ms
        for row in rows[3:]:
            intersects = row.low <= high and row.high >= low
            if intersects:
                if not touching:
                    touches += 1
                last_touch_ms = row.open_ms
            touching = intersects
        zones.append(
            _Zone(
                id=f"{kind}:{pivot.open_ms}",
                kind=kind,
                price=price,
                low=low,
                high=high,
                confirmed_at_ms=confirmed.close_ms,
                last_touch_ms=last_touch_ms,
                touches=touches,
                in_visit=touching,
            )
        )


def analyze_candles(bars: list[Bar], timeframe: str, now: float) -> dict[str, Any]:
    """Analyze supplied native closed candles without resampling or financial effects.

    Prices/indicators cross the wire as Decimal strings. Gaps reset all windows
    and active levels; returned historical pattern records remain bounded and
    carry their original level price even if that level later leaves the display.
    """
    interval = _validate(bars, timeframe, now)
    with localcontext(Context(prec=38, rounding=ROUND_HALF_EVEN)):
        closes: deque[Decimal] = deque(maxlen=100)
        preceding_volume: deque[Decimal] = deque(maxlen=VOLUME_WINDOW)
        weighted: deque[tuple[Decimal, Decimal]] = deque(maxlen=VWAP_WINDOW)
        recent: deque[Bar] = deque(maxlen=5)
        zones: deque[_Zone] = deque(maxlen=MAX_ZONES)
        patterns: deque[dict[str, Any]] = deque(maxlen=MAX_PATTERNS)
        points: list[dict[str, Any]] = []
        gaps = []
        previous: Bar | None = None
        segment_size = 0
        patterns_observed = 0
        for bar in bars:
            if previous is not None and bar.open_ms - previous.open_ms != interval:
                gaps.append(
                    {
                        "after_close_ms": previous.close_ms,
                        "before_open_ms": bar.open_ms,
                        "missing_candles": (bar.open_ms - previous.open_ms) // interval - 1,
                    }
                )
                closes.clear()
                preceding_volume.clear()
                weighted.clear()
                recent.clear()
                zones.clear()
                previous = None
                segment_size = 0
            segment_size += 1
            ratio = _volume_ratio(bar, preceding_volume)
            closes.append(bar.close)
            weighted.append(((bar.high + bar.low + bar.close) / 3 * bar.volume, bar.volume))
            total_volume = sum((volume for _, volume in weighted), Decimal(0))
            vwap = (
                sum((value for value, _ in weighted), Decimal(0)) / total_volume
                if len(weighted) == VWAP_WINDOW and total_volume > 0
                else None
            )
            point: dict[str, Any] = {"open_ms": bar.open_ms}
            values = list(closes)
            for period in SMA_PERIODS:
                point[f"sma{period}"] = (
                    str(sum(values[-period:], Decimal(0)) / period)
                    if len(values) >= period
                    else None
                )
            points.append({**point, "vwap": _number(vwap), "volume_ratio": _number(ratio)})
            if previous is not None:
                for zone in zones:
                    found = _visit(zone, bar, previous, ratio, interval)
                    patterns_observed += len(found)
                    patterns.extend(found)
            # Current candle may confirm a pivot, but that level cannot be used
            # for this candle's decision; it first exists for the next candle.
            recent.append(bar)
            _confirm_zones(recent, zones)
            preceding_volume.append(bar.volume)
            previous = bar
        return {
            "version": VERSION,
            "timeframe": timeframe,
            "seconds": TIMEFRAMES[timeframe],
            "candles": [
                {
                    "open_ms": bar.open_ms,
                    "close_ms": bar.close_ms,
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": str(bar.volume),
                }
                for bar in bars
            ],
            "indicators": {"points": points},
            "zones": [
                {
                    "id": zone.id,
                    "kind": zone.kind,
                    "price": str(zone.price),
                    "low": str(zone.low),
                    "high": str(zone.high),
                    "touches": zone.touches,
                    "confirmed_at_ms": zone.confirmed_at_ms,
                    "last_touch_ms": zone.last_touch_ms,
                }
                for zone in zones
            ],
            "patterns": list(patterns),
            "coverage": {
                "state": "empty" if not bars else "gapped" if gaps else "contiguous",
                "input_candles": len(bars),
                "segments": 0 if not bars else len(gaps) + 1,
                "latest_segment_candles": segment_size,
                "latest_close_age_seconds": None if not bars else now - bars[-1].close_ms / 1000,
                "warmup": {
                    **{f"sma{period}": segment_size >= period for period in SMA_PERIODS},
                    "vwap": bool(points and points[-1]["vwap"] is not None),
                    "volume_ratio": bool(points and points[-1]["volume_ratio"] is not None),
                },
                "zones_retained": len(zones),
                "patterns_retained": len(patterns),
                "patterns_observed": patterns_observed,
                "patterns_omitted_from_display": patterns_observed - len(patterns),
            },
            "gaps": gaps,
            "parameters": {
                "sma_periods": list(SMA_PERIODS),
                "vwap_window_candles": VWAP_WINDOW,
                "vwap_method": "Trailing native-candle HLC3 times volume / total volume",
                "volume_baseline_candles": VOLUME_WINDOW,
                "volume_baseline_method": (
                    "Median previous 20 same-frame positive volumes; excludes current"
                ),
                "volume_confirmation_multiple": str(VOLUME_CONFIRMATION),
                "zero_volume_confirmation": (
                    "Unknown until current and all previous 20 volumes are positive"
                ),
                "pivot_left_candles": 2,
                "pivot_right_candles": 2,
                "zone_half_width_fraction": str(ZONE_HALF_WIDTH),
                "visit_rule": "A full candle range must leave the zone before another visit",
                "retest_max_candles": RETEST_CANDLES,
                "max_candles": MAX_CANDLES,
                "max_zones": MAX_ZONES,
                "max_patterns": MAX_PATTERNS,
                "decimal_precision": 38,
            },
            "limitations": [
                "Descriptive advisory overlays; no probabilities, profitability or authority.",
                "Only supplied native timeframe candles are used; no manufactured OHLC resampling.",
                "Two closed right-hand candles confirm a pivot; its level is usable afterward.",
                "VWAP is a trailing HLC3/volume candle approximation, not full-session trade VWAP.",
                "Zero volume and incomplete volume windows provide no volume confirmation.",
                "Gaps reset indicators/active levels; bounded patterns can refer to older levels.",
                "Repeated touches and overlapping patterns are not independent research evidence.",
                "Candle touches do not prove executable orders or fills.",
            ],
        }
