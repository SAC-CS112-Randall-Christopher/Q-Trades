from decimal import Decimal as D

import pytest

from trading.market import InvalidMarketData
from trading.paper_strategy import Bar, features, parse_bars


def test_open_candle_excluded_and_invalid_time_rejected():
    raw = [
        [60000, "100", "101", "99", "100", "1", 119999],
        [120000, "100", "101", "99", "100", "1", 179999],
    ]
    assert len(parse_bars(raw, 130)) == 1
    raw[0][6] = 120000
    with pytest.raises(InvalidMarketData, match="complete UTC minute"):
        parse_bars(raw, 130)


def test_features_use_complete_trend_and_reject_gaps_staleness_zero_volume():
    bars = []
    for i in range(400):
        p = D(100) + D(i) / 100
        bars.append(Bar(i * 60000, p, p + D(".005"), p - D(".01"), p, D(10), i * 60000 + 59999))
    last = bars[-1]
    bars[-1] = Bar(last.open_ms, last.open, last.high, last.low, last.close, D(30), last.close_ms)
    now = (bars[-1].close_ms + 1000) / 1000
    result = features(bars, now, "breakout-v1")
    assert result["trend_up"] and result["eligible"]
    assert not features(bars, now + 120, "breakout-v1")["eligible"]
    assert not features(bars[:200], now, "breakout-v1")["eligible"]
    assert "gap" in features(bars[:210] + bars[211:], now, "breakout-v1")["reason"]
    empty = [Bar(b.open_ms, b.open, b.high, b.low, b.close, D(0), b.close_ms) for b in bars]
    assert not features(empty, now, "breakout-v1")["eligible"]
