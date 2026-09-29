from decimal import Decimal

import pytest

from trading.market import InvalidMarketData, decimal_string, parse_book, parse_instruments


@pytest.mark.parametrize("value", [0.1, 1, True, "NaN", "Infinity", "-1", "0", "1e100", "x"])
def test_invalid_financial_quantities_are_rejected(value):
    with pytest.raises(InvalidMarketData):
        decimal_string(value)


def test_exact_spread_and_depth_without_usdt_conversion(book):
    metrics = parse_book(book).metrics()
    assert Decimal(metrics["mid"]) == Decimal("100")
    assert Decimal(metrics["spread_bps"]) == Decimal("20")
    assert Decimal(metrics["bid_depth_quote"]) == Decimal("499.2")
    assert Decimal(metrics["ask_depth_quote"]) == Decimal("500.8")
    assert "usd_equity" not in metrics


@pytest.mark.parametrize(
    "problem", ["crossed", "empty", "unsorted", "duplicate", "sequence", "huge"]
)
def test_invalid_order_books_fail_closed(book, problem):
    if problem == "crossed":
        book["bids"][0][0] = "100.11"
    elif problem == "empty":
        book["asks"] = []
    elif problem == "unsorted":
        book["bids"].reverse()
    elif problem == "duplicate":
        book["asks"].append(book["asks"][-1])
    elif problem == "sequence":
        book["lastUpdateId"] = True
    else:
        book["asks"] = book["asks"] * 100
    with pytest.raises(InvalidMarketData):
        parse_book(book)


def test_minimum_notional_is_not_full_trade_eligibility(metadata):
    instruments = parse_instruments(metadata, ["BTCUSD", "MISSING"])
    assert instruments["BTCUSD"]["minimum_notional"] == "1.00"
    assert "MISSING" not in instruments
    metadata["symbols"][0].pop("isSpotTradingAllowed")
    assert not parse_instruments(metadata, ["BTCUSD"])["BTCUSD"]["spot_allowed"]
