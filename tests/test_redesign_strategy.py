"""Synthetic entry-contract checks; none measures market profitability."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from trading.paper_strategy import Bar
from trading.redesign_strategy import (
    MAXIMUM_HOLD_SECONDS,
    PROGRESS_SECONDS,
    REDESIGN_VERSION,
    STRATEGIES,
    features,
)


def candle(index: int, close: str | D = "100", *, volume: str = "10") -> Bar:
    price = D(close)
    return Bar(
        index * 300000,
        price,
        price + D("0.2"),
        price - D("0.2"),
        price,
        D(volume),
        index * 300000 + 299999,
    )


def change(bar: Bar, *, open: str, high: str, low: str, close: str, volume: str = "10") -> Bar:
    return replace(bar, open=D(open), high=D(high), low=D(low), close=D(close), volume=D(volume))


def minutes(bars: list[Bar]) -> list[Bar]:
    # Constant within each synthetic five-minute interval. These observations
    # demonstrate the declared predicate, not plausible executions or an edge.
    return [
        replace(
            bar,
            open_ms=bar.open_ms + i * 60000,
            close_ms=bar.open_ms + i * 60000 + 59999,
            volume=bar.volume / 5,
        )
        for bar in bars
        for i in range(5)
    ]


def fixture(version: str) -> list[Bar]:
    bars = [candle(i) for i in range(61)]
    if version in {
        "cost-breakout-v1",
        "breakout-retest-v1",
        "trend-pullback-v1",
        "momentum-followthrough-v1",
    }:
        bars = [candle(i, D(100) + D(i) / 10) for i in range(61)]
    if version == "cost-breakout-v1":
        bars[-1] = change(
            bars[-1], open="106.1", high="106.4", low="106", close="106.25", volume="30"
        )
    elif version == "breakout-retest-v1":
        bars[-2] = change(
            bars[-2], open="106.1", high="106.4", low="105.95", close="106.3", volume="20"
        )
        bars[-1] = change(bars[-1], open="106.05", high="106.35", low="105.95", close="106.25")
    elif version == "trend-pullback-v1":
        bars[-1] = change(bars[-1], open="105.5", high="106", low="104.9", close="105.85")
    elif version == "vwap-reclaim-v1":
        bars[-2] = change(bars[-2], open="100", high="100", low="99.6", close="99.7")
        bars[-1] = change(
            bars[-1], open="99.8", high="100.5", low="99.7", close="100.3", volume="15"
        )
    elif version == "range-fade-v1":
        bars[42] = replace(bars[42], high=D("103"))
        bars[45] = replace(bars[45], low=D("97"))
        bars[-1] = change(bars[-1], open="97.3", high="98.3", low="97", close="98.2")
    elif version == "momentum-followthrough-v1":
        bars[-3] = change(bars[-3], open="105.3", high="105.9", low="105.2", close="105.7")
        bars[-2] = change(bars[-2], open="105.7", high="106.2", low="105.6", close="106.1")
        bars[-1] = change(
            bars[-1], open="106.1", high="106.55", low="106", close="106.5", volume="20"
        )
    elif version == "compression-breakout-v1":
        bars = [replace(bar, high=D("101"), low=D("99")) for bar in bars]
        for i in range(54, 60):
            bars[i] = replace(bars[i], high=D("100.1"), low=D("99.9"))
        bars[-1] = change(bars[-1], open="100", high="100.6", low="100", close="100.5", volume="30")
    elif version == "washout-rebound-v1":
        bars[-2] = change(bars[-2], open="99.7", high="99.8", low="98", close="98.5", volume="30")
        bars[-1] = change(bars[-1], open="98.6", high="99.4", low="98.4", close="99.3", volume="15")
    return minutes(bars)


def observed_at(bars: list[Bar]) -> float:
    return bars[-1].close_ms / 1000 + 1


@pytest.mark.parametrize("version", STRATEGIES)
def test_each_distinct_frozen_hypothesis_has_a_positive_contract_fixture(version: str) -> None:
    bars = fixture(version)
    result = features(bars, observed_at(bars), version)
    assert result["eligible"] is True
    assert result["version"] == version
    assert result["redesign_version"] == REDESIGN_VERSION
    assert result["reason"] == STRATEGIES[version]
    assert result["bar_open_ms"] == 60 * 300000
    assert result["input_available_at"] < observed_at(bars)
    assert D(result["atr"]) > 0
    assert D(result["movement_proxy"]) == D(result["atr"]) * D("1.5")
    assert result["maximum_hold_seconds"] == MAXIMUM_HOLD_SECONDS == 21600
    assert result["progress_seconds"] == PROGRESS_SECONDS == 7200
    assert "no forecast or profitability claim" in result["economics_basis"]
    assert not {"expected_return", "profit", "win_probability", "order", "risk"} & result.keys()


@pytest.mark.parametrize("version", STRATEGIES)
def test_flat_market_is_not_an_entry_for_any_hypothesis(version: str) -> None:
    bars = minutes([candle(i) for i in range(61)])
    result = features(bars, observed_at(bars), version)
    assert result["eligible"] is False
    assert result["reason"] == "Frozen entry hypothesis is not present"


@pytest.mark.parametrize("version", STRATEGIES)
def test_each_hypothesis_rejects_a_nearby_missing_defining_condition(version: str) -> None:
    bars = fixture(version)
    aggregated = [bars[i] for i in range(0, len(bars), 5)]
    # Restore the aggregate volume used by the fixture generator.
    aggregated = [replace(bar, volume=bar.volume * 5) for bar in aggregated]
    if version == "cost-breakout-v1":
        aggregated[-1] = change(
            aggregated[-1], open="106.1", high="110.2", low="106", close="110", volume="30"
        )
    elif version == "breakout-retest-v1":
        aggregated[-2] = change(
            aggregated[-2], open="105.9", high="106.1", low="105.7", close="105.9", volume="20"
        )
    elif version == "trend-pullback-v1":
        aggregated[-1] = replace(aggregated[-1], low=D("105.5"))
    elif version == "vwap-reclaim-v1":
        aggregated[-2] = change(aggregated[-2], open="100", high="100.3", low="99.6", close="100.2")
    elif version == "range-fade-v1":
        aggregated[-1] = change(aggregated[-1], open="97.3", high="100.2", low="97", close="100.1")
    elif version == "momentum-followthrough-v1":
        aggregated[-1] = replace(aggregated[-1], low=D("105.5"))
    elif version == "compression-breakout-v1":
        for i in range(54, 60):
            aggregated[i] = replace(aggregated[i], high=D("101"), low=D("99"))
    elif version == "washout-rebound-v1":
        aggregated[-2] = replace(aggregated[-2], volume=D("10"))
    changed = minutes(aggregated)
    result = features(changed, observed_at(changed), version)
    assert result["eligible"] is False
    assert result["reason"] == "Frozen entry hypothesis is not present"


@pytest.mark.parametrize("version", STRATEGIES)
def test_unclosed_or_future_tail_cannot_change_a_closed_signal(version: str) -> None:
    bars = fixture(version)
    now = observed_at(bars)
    forming = Bar(305 * 60000, D("1000"), D("10000"), D("1"), D("9000"), D("9999"), 306 * 60000 - 1)
    later = replace(forming, open_ms=306 * 60000, close_ms=307 * 60000 - 1)
    before = features(bars, now, version)
    assert features(bars + [forming, later], now, version) == before


@pytest.mark.parametrize("version", STRATEGIES)
def test_new_closed_minute_does_not_repeat_the_strategy_bar_identity(version: str) -> None:
    bars = fixture(version)
    result = features(bars, observed_at(bars), version)
    next_minute = replace(
        bars[-1],
        open_ms=305 * 60000,
        close_ms=306 * 60000 - 1,
        open=D("101"),
        high=D("500"),
        low=D("1"),
        close=D("200"),
    )
    following = features(bars + [next_minute], observed_at([next_minute]), version)
    assert following == result


@pytest.mark.parametrize("version", STRATEGIES)
def test_gap_and_stale_observation_fail_closed(version: str) -> None:
    bars = fixture(version)
    gap = bars[:100] + bars[101:]
    assert features(gap, observed_at(bars), version)["eligible"] is False
    assert "gap" in features(gap, observed_at(bars), version)["reason"]
    assert "stale" in features(bars, observed_at(bars) + 90, version)["reason"]


@pytest.mark.parametrize("version", STRATEGIES)
def test_zero_volume_and_zero_volatility_are_unavailable(version: str) -> None:
    bars = fixture(version)
    zero_volume = [replace(bar, volume=D(0)) for bar in bars]
    assert "volume" in features(zero_volume, observed_at(bars), version)["reason"]
    zero_volatility = [
        replace(bar, open=D(100), high=D(100), low=D(100), close=D(100)) for bar in bars
    ]
    assert "volatility" in features(zero_volatility, observed_at(bars), version)["reason"]


@pytest.mark.parametrize("version", STRATEGIES)
def test_price_scale_and_volatile_inputs_do_not_invent_profitability(version: str) -> None:
    bars = fixture(version)
    scaled = [
        replace(
            bar, open=bar.open * 100, high=bar.high * 100, low=bar.low * 100, close=bar.close * 100
        )
        for bar in bars
    ]
    result = features(bars, observed_at(bars), version)
    large = features(scaled, observed_at(scaled), version)
    assert large["eligible"] == result["eligible"]
    assert D(large["atr"]) == D(result["atr"]) * 100
    assert D(large["movement_proxy_bps"]) == D(result["movement_proxy_bps"])
    assert large["economics_basis"] == result["economics_basis"]


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity", "0", "-1"])
def test_invalid_original_price_cannot_be_a_valid_entry(invalid: str) -> None:
    bars = fixture("cost-breakout-v1")
    bars[0] = replace(bars[0], close=D(invalid))
    result = features(bars, observed_at(bars), "cost-breakout-v1")
    assert result["eligible"] is False
    assert result["reason"] == "Invalid original minute observation"


def test_history_bounds_and_unknown_strategy_are_explicit() -> None:
    bars = fixture("cost-breakout-v1")
    assert "305" in features(bars[:300], observed_at(bars), "cost-breakout-v1")["reason"]
    oversized = minutes([candle(i) for i in range(121)])
    assert "600" in features(oversized, observed_at(oversized), "cost-breakout-v1")["reason"]
    assert "Unknown" in features(bars, observed_at(bars), "invented-v1")["reason"]


@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), 0, -1])
def test_invalid_clock_is_unavailable(bad_time: float) -> None:
    bars = fixture("cost-breakout-v1")
    assert features(bars, bad_time, "cost-breakout-v1")["reason"] == "Invalid observation time"


def test_mutating_the_previous_closed_range_changes_only_future_evaluation() -> None:
    bars = fixture("cost-breakout-v1")
    original = features(bars, observed_at(bars), "cost-breakout-v1")
    changed = [
        replace(bar, high=D("110")) if 55 * 300000 <= bar.open_ms < 56 * 300000 else bar
        for bar in bars
    ]
    assert features(changed, observed_at(changed), "cost-breakout-v1")["eligible"] is False
    assert original["eligible"] is True


def test_bank_and_observations_are_not_mutable_learning_state() -> None:
    with pytest.raises(TypeError):
        STRATEGIES["cost-breakout-v1"] = "learned from the latest loss"  # type: ignore[index]
    bars = fixture("cost-breakout-v1")
    original = list(bars)
    first = features(bars, observed_at(bars), "cost-breakout-v1")
    second = features(bars, observed_at(bars), "cost-breakout-v1")
    assert bars == original
    assert first == second
