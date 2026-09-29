"""Recompute public snapshot metrics offline; no synthetic or financial results."""

from typing import Any

from trading.market import Book, InvalidMarketData, parse_book


def replay_capture(capture: dict[str, Any]) -> dict[str, Any]:
    if capture.get("schema_version") != 1 or capture.get("source") != "binance_us_public_rest":
        raise ValueError("Unsupported capture format")
    observations = capture.get("observations")
    if not isinstance(observations, list) or len(observations) > 10000:
        raise ValueError("Capture exceeds the bounded replay format")
    valid = 0
    rejected = []
    latest = {}
    prior_books: dict[str, Book] = {}
    for record in observations:
        if record.get("kind") != "depth":
            continue
        symbol = record.get("symbol")
        if not isinstance(symbol, str):
            raise ValueError("Capture has a depth record without a symbol")
        try:
            book = parse_book(record["payload"])
            prior = prior_books.get(symbol)
            if prior and (
                book.update_id < prior.update_id
                or (book.update_id == prior.update_id and book != prior)
            ):
                raise InvalidMarketData("Sequence regression or inconsistent duplicate")
            prior_books[symbol] = book
            latest[symbol] = book.metrics()
            valid += 1
        except (InvalidMarketData, KeyError) as exc:
            rejected.append({"id": record.get("id"), "symbol": symbol, "reason": str(exc)})
    return {
        "evidence_type": "offline_public_snapshot_replay",
        "valid_depth_observations": valid,
        "rejected": rejected,
        "latest_metrics": latest,
        "retention": capture.get("retention"),
        "limitation": (
            "Sampled REST books do not prove continuous coverage, fills, or strategy returns"
        ),
    }
