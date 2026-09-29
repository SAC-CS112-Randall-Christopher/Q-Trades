"""Bounded, read-only public quote snapshots from the existing immutable journal."""

import hashlib
import json
import math
from typing import Any

import psycopg
from psycopg.rows import dict_row

from trading.research_experiment import MAX_ROWS


def quote_snapshot(dsn: str, as_of: float, limit: int = MAX_ROWS) -> dict[str, Any]:
    if not math.isfinite(as_of) or not 1 <= limit <= MAX_ROWS:
        raise ValueError("Invalid quote snapshot boundary")
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=4) as connection:
        # Retains any caller-supplied test search_path. No writer lock or initialization.
        connection.read_only = True
        connection.execute("SET LOCAL statement_timeout = '4s'")
        connection.execute("SET LOCAL lock_timeout = '1s'")
        mode = connection.execute("SHOW transaction_read_only").fetchone()
        if mode is None or mode["transaction_read_only"] != "on":
            raise RuntimeError("Research requires a read-only database transaction")
        rows = connection.execute(
            "SELECT id, at, body FROM paper_events WHERE kind = %s AND at <= %s "
            "AND body->>'symbol' = %s ORDER BY id DESC LIMIT %s",
            ("market_minute", as_of, "BTCUSD", limit + 1),
        ).fetchall()
    truncated = len(rows) > limit
    rows = sorted(rows[:limit], key=lambda row: (row["at"], row["id"]))
    return {
        "rows": rows,
        "manifest": {
            "version": "observed-quotes-v1",
            "source": "paper_events.market_minute",
            "symbol": "BTCUSD",
            "as_of": as_of,
            "read_only": True,
            "rows": len(rows),
            "row_limit": limit,
            "older_rows_omitted": truncated,
            "event_ids": [row["id"] for row in rows],
            "first_available_at": rows[0]["at"] if rows else None,
            "last_available_at": rows[-1]["at"] if rows else None,
            "dataset_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        },
    }
