"""PostgreSQL atomic projection and append-only, per-asset balanced financial journal."""

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from trading.execution_profiles import LEGACY_EXECUTION
from trading.paper_engine import PaperEngine, initial_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_state (
  id integer PRIMARY KEY CHECK (id = 1), revision bigint NOT NULL, body jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_events (
  id bigserial PRIMARY KEY, revision bigint NOT NULL, at double precision NOT NULL,
  kind text NOT NULL, account text NOT NULL, body jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_events_recent ON paper_events(account, id DESC);
CREATE INDEX IF NOT EXISTS paper_events_kind ON paper_events(kind, id DESC);
CREATE TABLE IF NOT EXISTS paper_journal (
  event_id bigint NOT NULL REFERENCES paper_events(id), line_no integer NOT NULL,
  account text NOT NULL, asset text NOT NULL, bucket text NOT NULL, amount numeric NOT NULL,
  PRIMARY KEY(event_id, line_no)
);
CREATE TABLE IF NOT EXISTS paper_bars (
  symbol text NOT NULL, open_ms bigint NOT NULL, observed_at double precision NOT NULL,
  bootstrap boolean NOT NULL, body jsonb NOT NULL, PRIMARY KEY(symbol, open_ms)
);
CREATE OR REPLACE FUNCTION paper_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Paper audit records are append-only'; END; $$;
CREATE OR REPLACE TRIGGER paper_events_immutable BEFORE UPDATE OR DELETE ON paper_events
FOR EACH ROW EXECUTE FUNCTION paper_immutable();
CREATE OR REPLACE TRIGGER paper_journal_immutable BEFORE UPDATE OR DELETE ON paper_journal
FOR EACH ROW EXECUTE FUNCTION paper_immutable();
CREATE OR REPLACE TRIGGER paper_bars_immutable BEFORE UPDATE OR DELETE ON paper_bars
FOR EACH ROW EXECUTE FUNCTION paper_immutable();
"""


def load_dsn(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    dsn = payload.get("dsn")
    if not isinstance(dsn, str) or not dsn:
        raise ValueError("Local paper database settings are missing")
    return dsn


class PaperStore:
    def __init__(self, dsn: str, *, owner: bool = False):
        self.owner = owner
        self.connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self.connection.execute("SET statement_timeout = '5s'")
        self.connection.execute("SET lock_timeout = '3s'")
        if owner:
            # Session lock also distinguishes test schemas on the same database.
            row = self.connection.execute(
                "SELECT pg_try_advisory_lock(hashtext(current_database() || current_schema()), "
                "734921) AS acquired"
            ).fetchone()
            if not row or not row["acquired"]:
                self.connection.close()
                raise RuntimeError("Another paper engine owns this database")
        if owner:
            self.connection.execute(SCHEMA)

    def require_owner(self) -> None:
        if not self.owner:
            raise RuntimeError("Financial mutation requires the exclusive engine writer lock")

    def close(self) -> None:
        self.connection.close()

    def initialize(
        self, now: float, starting_cash: str = "100", execution_profile: str = LEGACY_EXECUTION
    ) -> None:
        self.require_owner()
        initial = initial_state(now, starting_cash, execution_profile)
        with self.connection.transaction():
            inserted = self.connection.execute(
                "INSERT INTO paper_state VALUES (1, 0, %s) ON CONFLICT DO NOTHING RETURNING id",
                (Jsonb(initial),),
            ).fetchone()
            if inserted:
                engine = PaperEngine(initial, now)
                engine.seed()
                self._append(engine, 0)

    def _append(self, engine: PaperEngine, revision: int) -> None:
        for event in engine.events:
            row = self.connection.execute(
                "INSERT INTO paper_events(revision, at, kind, account, body) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (revision, event["at"], event["kind"], event["account"], Jsonb(event["body"])),
            ).fetchone()
            assert row is not None
            for index, line in enumerate(event["lines"]):
                self.connection.execute(
                    "INSERT INTO paper_journal VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        row["id"],
                        index,
                        event["account"],
                        line["asset"],
                        line["bucket"],
                        Decimal(line["amount"]),
                    ),
                )

    def transact(self, now: float, work: Callable[[PaperEngine], None]) -> dict[str, Any]:
        self.require_owner()
        with self.connection.transaction():
            row = self.connection.execute(
                "SELECT * FROM paper_state WHERE id=1 FOR UPDATE"
            ).fetchone()
            if not row:
                raise RuntimeError("Paper account was not initialized")
            state: dict[str, Any] = row["body"]
            if state.get("schema") != 1:
                raise RuntimeError("Unsupported paper state version")
            engine = PaperEngine(state, now)
            work(engine)
            engine.assert_invariants()
            revision = row["revision"] + 1
            self._append(engine, revision)
            self.connection.execute(
                "UPDATE paper_state SET revision=%s, body=%s WHERE id=1",
                (revision, Jsonb(engine.state)),
            )
        return engine.state

    def read(self) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT body, revision FROM paper_state WHERE id=1"
        ).fetchone()
        if not row:
            raise RuntimeError("Missing paper account")
        return {**row["body"], "revision": row["revision"]}

    def bars(
        self,
        symbol: str,
        raw: list[list[Any]],
        now: float,
        bootstrap: bool,
        *,
        closed_before_ms: float | None = None,
    ) -> int:
        self.require_owner()
        inserted = 0
        cutoff = now * 1000 if closed_before_ms is None else closed_before_ms
        with self.connection.transaction():
            for row in raw:
                if row[6] >= cutoff:
                    continue
                result = self.connection.execute(
                    "INSERT INTO paper_bars VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING open_ms",
                    (symbol, row[0], now, bootstrap, Jsonb(row)),
                ).fetchone()
                inserted += int(result is not None)
                if result is None:
                    previous = self.connection.execute(
                        "SELECT body FROM paper_bars WHERE symbol=%s AND open_ms=%s",
                        (symbol, row[0]),
                    ).fetchone()
                    if previous and previous["body"] != row:
                        raise ValueError("Stored closed candle differs from newly received data")
        return inserted

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(
            self.connection.execute(
                "SELECT id, at, kind, body FROM paper_events WHERE account='primary' "
                "AND kind NOT IN ('decision','equity') ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        )

    def numerical_inputs(self, as_of: float) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id,at,body FROM paper_events WHERE kind='market_minute' "
            "AND at<=%s AND body->>'symbol'='BTCUSD' ORDER BY id DESC LIMIT 121", (as_of,),
        ).fetchall()
        return sorted(rows, key=lambda r: (r["at"], r["id"]))

    def export(self, after: int, limit: int, account: str | None = None) -> dict[str, Any]:
        rows = list(
            self.connection.execute(
                "SELECT e.*, COALESCE((SELECT jsonb_agg(jsonb_build_object("
                "'asset',j.asset,'bucket',j.bucket,'amount',j.amount::text) ORDER BY j.line_no) "
                "FROM paper_journal j WHERE j.event_id=e.id),'[]'::jsonb) AS journal "
                "FROM paper_events e WHERE e.id > %s "
                "AND (%s::text IS NULL OR e.account=%s) ORDER BY e.id LIMIT %s",
                (after, account, account, limit + 1),
            ).fetchall()
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        return {
            "records": page,
            "has_more": has_more,
            "next_after": page[-1]["id"] if page else after,
        }

    def reconcile(self) -> dict[str, Any]:
        state = self.read()
        imbalanced = self.connection.execute(
            "SELECT count(*) AS n FROM (SELECT event_id,asset FROM paper_journal "
            "GROUP BY event_id,asset HAVING sum(amount)<>0) x"
        ).fetchone()
        rows = self.connection.execute(
            "SELECT account,asset,bucket,sum(amount) AS balance FROM paper_journal "
            "WHERE bucket IN ('cash','reserved','inventory','fees','fake_funding') "
            "GROUP BY account,asset,bucket"
        ).fetchall()
        balances = {(r["account"], r["asset"], r["bucket"]): r["balance"] for r in rows}
        errors = []
        for name, a in state["accounts"].items():
            reserved = sum((Decimal(o["reserved"]) for o in a["pending"].values()), Decimal(0))
            for bucket, expected in (
                ("cash", Decimal(a["cash"]) - reserved),
                ("reserved", reserved),
                ("fees", Decimal(a["fees"])),
                ("fake_funding", -Decimal(a["funding"])),
            ):
                if balances.get((name, "USD", bucket), Decimal(0)) != expected:
                    errors.append(f"{name}: USD {bucket} mismatch")
            inventory = {
                pos.get("base", symbol.removesuffix("USD")): Decimal(pos["quantity"])
                for symbol, pos in a["positions"].items()
            }
            bases = set(inventory) | {
                asset
                for (owner, asset, bucket) in balances
                if owner == name and bucket == "inventory"
            }
            for base in bases:
                expected = inventory.get(base, Decimal(0))
                if balances.get((name, base, "inventory"), Decimal(0)) != expected:
                    errors.append(f"{name}: {base} inventory mismatch")
        return {
            "balanced": bool(imbalanced and imbalanced["n"] == 0) and not errors,
            "imbalanced_events": imbalanced["n"] if imbalanced else None,
            "projection_errors": errors,
            "revision": state["revision"],
        }

    def storage_usage(self) -> dict[str, int]:
        row = self.connection.execute(
            "SELECT pg_database_size(current_database()) AS database_bytes, "
            "(SELECT count(*) FROM paper_bars) AS candles, "
            "(SELECT count(*) FROM paper_events) AS events, "
            "(SELECT count(*) FROM paper_journal) AS journal_lines, "
            "pg_total_relation_size('paper_bars') AS candle_table_bytes, "
            "pg_total_relation_size('paper_events') + "
            "pg_total_relation_size('paper_journal') AS journal_table_bytes"
        ).fetchone()
        return {k: int(v) for k, v in row.items()} if row else {}
