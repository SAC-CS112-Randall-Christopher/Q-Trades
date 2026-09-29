"""Sequence-checked bounded local book, with explicit snapshot coverage boundaries."""

from decimal import Decimal
from typing import Any

from trading.market import Book, decimal_string, parse_book


class StreamGap(ValueError):
    """Discard this book and bootstrap again; never guess missing updates."""


class DepthBook:
    def __init__(self, snapshot: dict[str, Any]):
        book = parse_book(snapshot, 1000)
        self.update_id = book.update_id
        self.bids = dict(book.bids)
        self.asks = dict(book.asks)
        # A snapshot cannot tell us about unchanged levels beyond these boundaries.
        self.bid_boundary = book.bids[-1][0]
        self.ask_boundary = book.asks[-1][0]
        self.event_ms = 0

    def apply(self, event: dict[str, Any]) -> Book | None:
        first, last, stamp = event.get("U"), event.get("u"), event.get("E")
        if (
            type(first) is not int
            or type(last) is not int
            or type(stamp) is not int
            or min(first, last, stamp) < 0
            or first > last
        ):
            raise StreamGap("Invalid depth sequence or exchange event timestamp")
        if last <= self.update_id:
            return None  # Duplicate or older event; never freshen its observation time.
        if first > self.update_id + 1:
            raise StreamGap("Missing depth sequence; rebuilding book")
        if stamp < self.event_ms:
            raise StreamGap("Exchange depth timestamp regressed")
        changes: list[list[tuple[Decimal, Decimal]]] = []
        for key in ("b", "a"):
            rows = event.get(key)
            if not isinstance(rows, list) or len(rows) > 5000:
                raise StreamGap("Invalid or oversized depth change")
            parsed = []
            for row in rows:
                if not isinstance(row, list) or len(row) != 2:
                    raise StreamGap("Malformed depth change")
                parsed.append((decimal_string(row[0]), decimal_string(row[1], positive=False)))
            if len({p for p, _ in parsed}) != len(parsed):
                raise StreamGap("Duplicate price in depth change")
            changes.append(parsed)
        for levels, updates, is_bid in (
            (self.bids, changes[0], True),
            (self.asks, changes[1], False),
        ):
            for price, quantity in updates:
                # Do not retain unbounded levels or pretend the unseen region is complete.
                covered = price >= self.bid_boundary if is_bid else price <= self.ask_boundary
                if not covered:
                    continue
                if quantity:
                    levels[price] = quantity
                else:
                    levels.pop(price, None)
            if len(levels) > 5000:
                raise StreamGap("Local book capacity reached; rebuilding book")
        if not self.bids or not self.asks or max(self.bids) >= min(self.asks):
            raise StreamGap("Empty, crossed, or locked local book")
        if len(self.bids) < 20 or len(self.asks) < 20:
            raise StreamGap("Top twenty levels exceed known snapshot coverage")
        self.update_id = last
        self.event_ms = stamp
        return Book(
            last,
            tuple((p, self.bids[p]) for p in sorted(self.bids, reverse=True)[:20]),
            tuple((p, self.asks[p]) for p in sorted(self.asks)[:20]),
        )


def book_payload(book: Book) -> dict[str, Any]:
    return {
        "lastUpdateId": book.update_id,
        "bids": [[str(p), str(q)] for p, q in book.bids],
        "asks": [[str(p), str(q)] for p, q in book.asks],
    }
