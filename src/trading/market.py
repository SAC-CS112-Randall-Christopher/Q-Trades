"""Pure snapshot validation and Decimal calculations; no trading decisions."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


class InvalidMarketData(ValueError):
    pass


def decimal_string(value: object, *, positive: bool = True) -> Decimal:
    if not isinstance(value, str) or len(value) > 64:
        raise InvalidMarketData("Prices and quantities must be bounded decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise InvalidMarketData("Invalid decimal") from exc
    if not number.is_finite() or abs(number.adjusted()) > 24:
        raise InvalidMarketData("Nonfinite or unsupported decimal magnitude")
    if number < 0 or (positive and number == 0):
        raise InvalidMarketData("Nonpositive price or quantity")
    return number


@dataclass(frozen=True)
class Book:
    update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

    def metrics(self) -> dict[str, str]:
        with localcontext() as ctx:
            ctx.prec = 50
            bid, ask = self.bids[0][0], self.asks[0][0]
            mid = (bid + ask) / 2
            return {
                "bid": str(bid),
                "ask": str(ask),
                "mid": str(mid),
                "spread_bps": str((ask - bid) / mid * 10000),
                "bid_depth_quote": str(
                    sum(
                        (p * q for p, q in self.bids if p >= bid * Decimal("0.995")),
                        Decimal(0),
                    )
                ),
                "ask_depth_quote": str(
                    sum(
                        (p * q for p, q in self.asks if p <= ask * Decimal("1.005")),
                        Decimal(0),
                    )
                ),
            }


def parse_book(payload: Any, limit: int = 100) -> Book:
    if not isinstance(payload, dict):
        raise InvalidMarketData("Order book must be an object")
    update_id = payload.get("lastUpdateId")
    if type(update_id) is not int or update_id < 0:
        raise InvalidMarketData("Missing or invalid book sequence")
    sides = []
    for name in ("bids", "asks"):
        raw = payload.get(name)
        if not isinstance(raw, list) or not 1 <= len(raw) <= limit:
            raise InvalidMarketData("Missing, empty, or oversized book side")
        levels = []
        for row in raw:
            if not isinstance(row, list) or len(row) != 2:
                raise InvalidMarketData("Malformed book level")
            levels.append((decimal_string(row[0]), decimal_string(row[1])))
        prices = [p for p, _ in levels]
        if len(set(prices)) != len(prices) or prices != sorted(prices, reverse=name == "bids"):
            raise InvalidMarketData("Unordered or repeated book prices")
        sides.append(tuple(levels))
    book = Book(update_id, sides[0], sides[1])
    if book.bids[0][0] >= book.asks[0][0]:
        raise InvalidMarketData("Crossed or locked book")
    return book


def parse_instruments(payload: Any, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise InvalidMarketData("Missing market metadata")
    result = {}
    for item in payload["symbols"]:
        if not isinstance(item, dict) or item.get("symbol") not in symbols:
            continue
        symbol = item["symbol"]
        if symbol in result:
            raise InvalidMarketData("Duplicate instrument metadata")
        for field in ("baseAsset", "quoteAsset", "status"):
            if not isinstance(item.get(field), str) or not item[field]:
                raise InvalidMarketData("Incomplete instrument metadata")
        filters = item.get("filters")
        if not isinstance(filters, list) or any(not isinstance(f, dict) for f in filters):
            raise InvalidMarketData("Missing market filters")
        minimums = [
            decimal_string(f["minNotional"], positive=False)
            for f in filters
            if f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL") and "minNotional" in f
        ]
        result[symbol] = {
            "symbol": symbol,
            "base": item["baseAsset"],
            "quote": item["quoteAsset"],
            "venue_status": item["status"],
            "spot_allowed": item.get("isSpotTradingAllowed") is True,
            "minimum_notional": str(max(minimums)) if minimums else None,
            "filters": filters,
        }
    return result
