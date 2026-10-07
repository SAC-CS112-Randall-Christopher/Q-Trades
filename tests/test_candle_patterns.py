"""Pure native-candle fixtures; these do not establish strategy profitability."""

import json
from copy import deepcopy
from dataclasses import replace
from decimal import ROUND_DOWN, Context, Decimal, Inexact, localcontext
from typing import Any

import pytest

from trading.candle_patterns import MAX_CANDLES, TIMEFRAMES, analyze_candles
from trading.market import InvalidMarketData
from trading.paper_strategy import Bar

D = Decimal


def candle(
    index: int,
    *,
    seconds: int = 300,
    opening: str = "100",
    high: str = "101",
    low: str = "99",
    close: str = "100",
    volume: str = "10",
) -> Bar:
    start = index * seconds * 1000
    return Bar(start, D(opening), D(high), D(low), D(close), D(volume), start + seconds * 1000 - 1)


def analyze(rows: list[Bar], timeframe: str = "5m") -> dict[str, Any]:
    now = 1.0 if not rows else (rows[-1].close_ms + 1000) / 1000
    return analyze_candles(rows, timeframe, now)


def support_rows() -> list[Bar]:
    rows = [candle(i) for i in range(28)]
    rows[20] = candle(20, opening="97", high="99", low="95", close="98")
    rows[24] = candle(24, opening="96", high="98", low="95.05", close="97", volume="30")
    rows[25] = candle(25, opening="96", high="98", low="95.1", close="97")
    rows[27] = candle(27, opening="96", high="98", low="95.05", close="97", volume="15")
    return rows


def resistance_rows() -> list[Bar]:
    rows = [candle(i) for i in range(28)]
    rows[20] = candle(20, opening="101", high="105", low="99", close="100")
    rows[24] = candle(24, opening="104", high="108", low="103", close="107", volume="30")
    rows[25] = candle(25, opening="107", high="109", low="106", close="108")
    rows[26] = candle(26, opening="105.4", high="107.5", low="105.1", close="107", volume="20")
    return rows


def of_kind(result: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [record for record in result["patterns"] if record["kind"] == kind]


def test_empty_and_short_history_are_explicit_without_invented_indicators() -> None:
    empty = analyze([])
    assert empty["coverage"]["state"] == "empty"
    assert empty["coverage"]["segments"] == 0
    assert empty["coverage"]["latest_close_age_seconds"] is None
    assert not any(empty["coverage"]["warmup"].values())
    assert empty["candles"] == empty["patterns"] == empty["zones"] == []
    short = analyze([candle(i) for i in range(9)])
    assert all(
        point[name] is None
        for point in short["indicators"]["points"]
        for name in ("sma10", "sma50", "sma100", "vwap", "volume_ratio")
    )
    assert short["zones"] == short["patterns"] == []  # Equal lows/highs are not strict pivots.


@pytest.mark.parametrize("timeframe,seconds", TIMEFRAMES.items())
def test_smas_count_native_chart_candles_and_never_resample(timeframe: str, seconds: int) -> None:
    rows = [
        candle(
            i,
            seconds=seconds,
            opening=str(100 + i),
            high=str(101 + i),
            low=str(99 + i),
            close=str(100 + i),
        )
        for i in range(100)
    ]
    result = analyze(rows, timeframe)
    assert result["seconds"] == seconds
    assert len(result["candles"]) == len(result["indicators"]["points"]) == 100
    assert result["candles"][12] == {
        "open_ms": rows[12].open_ms,
        "close_ms": rows[12].close_ms,
        "open": "112",
        "high": "113",
        "low": "111",
        "close": "112",
        "volume": "10",
    }
    points = result["indicators"]["points"]
    assert points[8]["sma10"] is None and D(points[9]["sma10"]) == D("104.5")
    assert points[48]["sma50"] is None and D(points[49]["sma50"]) == D("124.5")
    assert points[98]["sma100"] is None and D(points[99]["sma100"]) == D("149.5")
    assert D(points[-1]["sma10"]) == D("194.5")
    assert result["parameters"]["sma_periods"] == [10, 50, 100]


def test_vwap_is_actual_trailing_50_hlc3_volume_approximation() -> None:
    rows = [
        candle(
            i,
            opening=str(100 + i),
            high=str(105 + i),
            low=str(98 + i),
            close=str(102 + i),
            volume=str(i + 1),
        )
        for i in range(60)
    ]
    points = analyze(rows)["indicators"]["points"]
    assert points[48]["vwap"] is None
    with localcontext(Context(prec=38)):
        for index in (49, 59):
            window = rows[index - 49 : index + 1]
            expected = sum(((r.high + r.low + r.close) / 3 * r.volume for r in window), D(0)) / sum(
                (r.volume for r in window), D(0)
            )
            assert D(points[index]["vwap"]) == expected
        assert D(points[59]["vwap"]) != sum((r.close for r in rows[10:]), D(0)) / 50


def test_volume_median_excludes_current_and_uses_exact_confirmation_boundary() -> None:
    rows = [candle(i, volume=str(i + 1)) for i in range(20)] + [candle(20, volume="1050")]
    result = analyze(rows)
    assert result["indicators"]["points"][19]["volume_ratio"] is None
    assert D(result["indicators"]["points"][20]["volume_ratio"]) == 100
    # The second separate support visit is exactly 1.5 times its preceding median.
    bounce = of_kind(analyze(support_rows()), "support_bounce")[-1]
    assert D(bounce["volume_ratio"]) == D("1.5")
    assert bounce["volume_confirmed"] is True


def test_zero_volume_is_unknown_until_the_prior_window_recovers() -> None:
    rows = [candle(i) for i in range(43)]
    rows[21] = candle(21, volume="0")
    result = analyze(rows)
    points = result["indicators"]["points"]
    assert points[20]["volume_ratio"] == "1"
    assert all(point["volume_ratio"] is None for point in points[21:42])
    assert points[42]["volume_ratio"] == "1"
    zero = analyze([candle(i, volume="0") for i in range(100)])
    assert zero["indicators"]["points"][-1]["vwap"] is None
    assert zero["coverage"]["warmup"]["vwap"] is False
    retest_rows = resistance_rows()
    retest_rows[26] = replace(retest_rows[26], volume=D(0))
    retest = of_kind(analyze(retest_rows), "breakout_retest")[0]
    assert retest["volume_ratio"] is None and retest["volume_confirmed"] is None


def test_support_visits_require_leaving_and_do_not_move_the_frozen_zone() -> None:
    result = analyze(support_rows())
    bounces = of_kind(result, "support_bounce")
    assert [b["bar_open_ms"] for b in bounces] == [24 * 300_000, 27 * 300_000]
    assert [b["volume_confirmed"] for b in bounces] == [True, True]
    zone = next(z for z in result["zones"] if z["id"] == "support:6000000")
    assert D(zone["price"]) == 95 and D(zone["low"]) == D("94.8575")
    assert D(zone["high"]) == D("95.1425")
    assert zone["touches"] == 3 and zone["last_touch_ms"] == 27 * 300_000
    assert len([z for z in result["zones"] if z["kind"] == "support"]) == 1
    assert all("Descriptive, not a trade instruction" in b["reason"] for b in bounces)


@pytest.mark.parametrize(
    "change",
    [
        {"open": D("97.5"), "close": D("97")},  # Bearish, even though above the zone.
        {"low": D("94")},  # Crossed below the fixed zone.
        {"volume": D("5")},  # Price pattern remains, volume fails confirmation.
    ],
)
def test_support_price_and_volume_negatives_remain_distinct(change: dict[str, Decimal]) -> None:
    rows = support_rows()[:25]
    rows[24] = replace(rows[24], **change)
    bounces = of_kind(analyze(rows), "support_bounce")
    if "volume" in change:
        assert len(bounces) == 1 and bounces[0]["volume_confirmed"] is False
        assert D(bounces[0]["volume_ratio"]) == D("0.5")
    else:
        assert bounces == []


def test_resistance_breakout_then_later_retest_uses_previously_confirmed_level() -> None:
    result = analyze(resistance_rows())
    breakout = of_kind(result, "resistance_breakout")
    retest = of_kind(result, "breakout_retest")
    assert len(breakout) == len(retest) == 1
    assert breakout[0]["bar_open_ms"] == 24 * 300_000
    assert retest[0]["bar_open_ms"] == 26 * 300_000
    assert breakout[0]["level_id"] == retest[0]["level_id"] == "resistance:6000000"
    assert D(breakout[0]["volume_ratio"]) == 3 and D(retest[0]["volume_ratio"]) == 2
    assert breakout[0]["volume_confirmed"] is retest[0]["volume_confirmed"] is True
    assert not of_kind(analyze(resistance_rows()[:25]), "breakout_retest")


@pytest.mark.parametrize("negative", ["no_departure", "failed_hold", "expired"])
def test_retest_refuses_continuous_touch_failed_hold_and_expired_breakout(negative: str) -> None:
    rows = resistance_rows()[:27]
    if negative == "no_departure":
        rows[25] = replace(rows[25], low=D("105.1"))
    elif negative == "failed_hold":
        rows[26] = replace(rows[26], low=D("104"))
    else:
        rows = rows[:26] + [
            candle(i, opening="107", high="109", low="106", close="108") for i in range(26, 36)
        ]
        rows.append(candle(36, opening="105.4", high="108", low="105.1", close="107"))
    result = analyze(rows)
    assert of_kind(result, "resistance_breakout")
    assert not of_kind(result, "breakout_retest")


def test_pivot_needs_two_right_closed_candles_and_never_uses_future_levels() -> None:
    rows = support_rows()
    assert not analyze(rows[:22])["zones"]
    confirmed = analyze(rows[:23])["zones"]
    assert len(confirmed) == 1 and confirmed[0]["confirmed_at_ms"] == rows[22].close_ms
    assert not analyze(rows[:24])["patterns"]
    result = analyze(rows)
    zones = {z["id"]: z for z in result["zones"]}
    for pattern in result["patterns"]:
        assert zones[pattern["level_id"]]["confirmed_at_ms"] < pattern["bar_open_ms"]
    # Appending later candles cannot alter earlier indicator or pattern decisions.
    prefix = analyze(rows[:25])
    assert prefix["indicators"]["points"] == result["indicators"]["points"][:25]
    assert prefix["patterns"] == [
        p for p in result["patterns"] if p["bar_open_ms"] <= rows[24].open_ms
    ]


def test_gap_reports_missing_native_candles_and_resets_all_causal_windows() -> None:
    first = support_rows()[:25]
    later = [candle(i, opening="96", high="98", low="95.05", close="97") for i in range(27, 36)]
    result = analyze(first + later)
    assert result["gaps"] == [
        {
            "after_close_ms": first[-1].close_ms,
            "before_open_ms": later[0].open_ms,
            "missing_candles": 2,
        }
    ]
    assert result["coverage"]["state"] == "gapped"
    assert result["coverage"]["segments"] == 2
    assert result["coverage"]["latest_segment_candles"] == 9
    assert not any(result["coverage"]["warmup"].values())
    assert all(
        p["sma10"] is None and p["volume_ratio"] is None
        for p in result["indicators"]["points"][25:]
    )
    assert result["zones"] == []
    assert result["patterns"] == analyze(first)["patterns"]  # No cross-gap bounce.


def test_decimal_context_independence_json_safety_and_source_immutability() -> None:
    rows = resistance_rows()
    snapshot = deepcopy(rows)
    expected = analyze(rows)
    with localcontext() as context:
        context.prec = 7
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert analyze(rows) == expected
    assert rows == snapshot
    assert json.loads(json.dumps(expected)) == expected


def test_maximum_native_history_keeps_explicit_pattern_and_zone_bounds() -> None:
    rows = support_rows()[:24]
    for i in range(24, MAX_CANDLES):
        rows.append(
            candle(i) if i % 2 else candle(i, opening="96", high="98", low="95.05", close="97")
        )
    result = analyze(rows)
    assert len(result["candles"]) == len(result["indicators"]["points"]) == MAX_CANDLES
    assert 0 < len(result["zones"]) <= 12
    assert len(result["patterns"]) == 60
    assert result["coverage"]["patterns_observed"] > 60
    assert (
        result["coverage"]["patterns_omitted_from_display"]
        == result["coverage"]["patterns_observed"] - 60
    )
    # Distinct successive pivots also keep only the bounded level display.
    waves = []
    for i in range(200):
        center = D(100 + i // 6 * 2)
        low = center - (D(5) if i % 6 == 2 else D(1))
        high = center + (D(5) if i % 6 == 5 else D(1))
        waves.append(
            candle(i, opening=str(center), high=str(high), low=str(low), close=str(center))
        )
    assert len(analyze(waves)["zones"]) == 12


@pytest.mark.parametrize(
    "bad",
    [
        {"volume": None},
        {"volume": 10},
        {"open": D("NaN")},
        {"high": D("Infinity")},
        {"low": D(0)},
        {"volume": D(-1)},
        {"close": D(105)},
        {"high": D(98)},
        {"open_ms": True},
        {"close_ms": True},
        {"open_ms": -300_000},
        {"open_ms": 1},
        {"close_ms": 300_000},
        {"high": D("1e41")},
        {"volume": D("1e-41")},
    ],
)
def test_malformed_native_candle_refuses(bad: dict[str, Any]) -> None:
    with pytest.raises(InvalidMarketData):
        analyze([replace(candle(0), **bad)])


@pytest.mark.parametrize("timeframe", ["1m", "2h", "", "5M"])
def test_unsupported_timeframe_refuses(timeframe: str) -> None:
    with pytest.raises(InvalidMarketData):
        analyze_candles([], timeframe, 1.0)


@pytest.mark.parametrize("now", [True, -1.0, float("nan"), float("inf")])
def test_invalid_observation_time_refuses(now: float) -> None:
    with pytest.raises(InvalidMarketData):
        analyze_candles([], "5m", now)


def test_future_forming_duplicate_unordered_wrong_interval_and_oversize_refuse() -> None:
    with pytest.raises(InvalidMarketData):
        analyze_candles([candle(0)], "5m", candle(0).close_ms / 1000)
    with pytest.raises(InvalidMarketData):
        analyze_candles([candle(1)], "5m", 1.0)
    for rows in ([candle(0), candle(0)], [candle(1), candle(0)], [candle(0, seconds=60)]):
        with pytest.raises(InvalidMarketData):
            analyze(rows)
    with pytest.raises(InvalidMarketData):
        analyze([candle(i) for i in range(MAX_CANDLES + 1)])
    with pytest.raises(InvalidMarketData):
        analyze_candles([{}], "5m", 1.0)  # type: ignore[list-item]
