import pytest
from pydantic import ValidationError

from trading.config import Settings


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "live"},
        {"live_enabled": True},
        {"ai_enabled": True},
        {"ai_daily_budget_usd": "1.00"},
        {"approved_symbols": ["BTCUSD"]},
        {"monitored_symbols": ["BTCUSD", "BTCUSD"]},
        {"monitored_symbols": ["btc/usd"]},
        {"poll_seconds": 1},
        {"stale_after_seconds": 15},
        {"allow_margin": True},
    ],
)
def test_unsupported_permissions_and_unsafe_configuration_rejected(changes):
    with pytest.raises(ValidationError):
        Settings(**changes)


def test_empty_watchlist_is_empty_not_all_symbols():
    assert Settings().monitored_symbols == []
    assert Settings().approved_symbols == []
