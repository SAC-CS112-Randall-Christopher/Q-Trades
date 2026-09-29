import copy

import pytest


@pytest.fixture
def book():
    return {
        "lastUpdateId": 17,
        "bids": [["99.90", "2.0"], ["99.80", "3.0"], ["98.00", "10"]],
        "asks": [["100.10", "2.0"], ["100.20", "3.0"], ["102.00", "10"]],
    }


@pytest.fixture
def metadata():
    return {
        "symbols": [
            {
                "symbol": "BTCUSD",
                "baseAsset": "BTC",
                "quoteAsset": "USD",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
                "filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "1.00"}],
            }
        ]
    }


@pytest.fixture
def clone():
    return copy.deepcopy
