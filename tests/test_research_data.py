import pytest
from psycopg.types.json import Jsonb
from test_paper_store import pg_store as _pg_store

from trading.research_data import quote_snapshot

pg_store = _pg_store


def test_snapshot_preserves_history_and_excludes_future_other_market_and_excess_rows(pg_store):
    store, dsn = pg_store
    before = store.read()
    # These observations exist only in this test's disposable PostgreSQL schema.
    for at, symbol in [(10, "BTCUSD"), (20, "BTCUSD"), (25, "ETHUSD"), (30, "BTCUSD")]:
        store.connection.execute(
            "INSERT INTO paper_events(revision, at, kind, account, body) "
            "VALUES (1, %s, 'market_minute', 'test-only', %s)",
            (at, Jsonb({"symbol": symbol, "last_depth": {"bid": "10.00", "ask": "10.01"}})),
        )
    snapshot = quote_snapshot(dsn, 26.0, limit=1)
    assert snapshot["manifest"]["read_only"] is True
    assert snapshot["manifest"]["older_rows_omitted"] is True
    assert [row["at"] for row in snapshot["rows"]] == [20.0]
    assert snapshot["rows"][0]["body"]["last_depth"]["bid"] == "10.00"
    assert store.read() == before
    assert store.connection.execute(
        "SELECT count(*) AS n FROM paper_events WHERE kind='market_minute'"
    ).fetchone()["n"] == 4


def test_snapshot_rejects_unbounded_or_invalid_requests_before_connecting():
    for cutoff, limit in [(float("nan"), 1), (10.0, 12001), (10.0, 0)]:
        with pytest.raises(ValueError):
            quote_snapshot("never connected", cutoff, limit)
