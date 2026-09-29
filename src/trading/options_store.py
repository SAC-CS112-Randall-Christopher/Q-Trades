"""Options own a separate schema, projection, writer lock and append-only journal."""

import re
from collections.abc import Callable
from decimal import Decimal as D
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from trading.options_engine import OptionsEngine, initial_state, reserved
from trading.paper_store import PaperStore


class OptionsStore:
    def __init__(self, dsn: str, *, schema: str = "options_paper", owner: bool = True):
        if schema != "options_paper" and not re.fullmatch(r"test_options_[a-f0-9]{32}", schema):
            raise ValueError("Unsupported options namespace")
        if owner:
            with psycopg.connect(dsn, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
                )
        self.ledger = PaperStore(
            make_conninfo(dsn, options=f"-c search_path={schema}"), owner=owner
        )
        self.connection = self.ledger.connection

    def close(self) -> None:
        self.ledger.close()

    def initialize(self, now: float) -> None:
        self.ledger.require_owner()
        with self.connection.transaction():
            inserted = self.connection.execute(
                "INSERT INTO paper_state VALUES (1,0,%s) ON CONFLICT DO NOTHING RETURNING id",
                (Jsonb(initial_state(now)),),
            ).fetchone()
            if inserted:
                engine = OptionsEngine(initial_state(now), now)
                engine.seed()
                self.ledger._append(engine, 0)
        if self.read().get("kind") != "cash_options_research":
            raise ValueError("Options must not share the spot projection")

    def read(self) -> dict[str, Any]:
        return self.ledger.read()

    def transact(self, now: float, work: Callable[[OptionsEngine], None]) -> dict[str, Any]:
        self.ledger.require_owner()
        with self.connection.transaction():
            row = self.connection.execute(
                "SELECT * FROM paper_state WHERE id=1 FOR UPDATE"
            ).fetchone()
            if not row or row["body"].get("kind") != "cash_options_research":
                raise ValueError("Options projection missing or wrong account type")
            engine = OptionsEngine(row["body"], now)
            work(engine)
            engine.assert_invariants()
            revision = row["revision"] + 1
            self.ledger._append(engine, revision)
            self.connection.execute(
                "UPDATE paper_state SET revision=%s,body=%s WHERE id=1",
                (revision, Jsonb(engine.state)),
            )
        return {**engine.state, "revision": revision}

    def reconcile(self) -> dict[str, Any]:
        state = self.read()
        row = self.connection.execute(
            "SELECT count(*) AS n FROM (SELECT event_id,asset FROM paper_journal "
            "GROUP BY event_id,asset HAVING sum(amount)<>0) x"
        ).fetchone()
        sums = self.connection.execute(
            "SELECT account,asset,bucket,sum(amount) AS balance FROM paper_journal "
            "GROUP BY account,asset,bucket"
        ).fetchall()
        balances = {(r["account"], r["asset"], r["bucket"]): r["balance"] for r in sums}
        errors = []
        for name, a in state["accounts"].items():
            expected = {
                "cash": D(a["cash"]) - reserved(a),
                "reserved": reserved(a),
                "unsettled": sum((D(x["amount"]) for x in a["unsettled"]), D(0)),
                "fake_funding": -D(a["funding"]),
                "fees": D(a["fees"]),
            }
            for bucket, amount in expected.items():
                if balances.get((name, "USD", bucket), D(0)) != amount:
                    errors.append(f"{name}: USD {bucket} mismatch")
            instruments = set(a["positions"]) | {
                asset
                for owner, asset, bucket in balances
                if owner == name and bucket == "inventory"
            }
            for instrument in instruments:
                quantity = D(a["positions"].get(instrument, {}).get("quantity", "0"))
                if balances.get((name, instrument, "inventory"), D(0)) != quantity:
                    errors.append(f"{name}: {instrument} inventory mismatch")
        return {
            "balanced": bool(row and row["n"] == 0) and not errors,
            "imbalanced_events": row["n"] if row else None,
            "projection_errors": errors,
            "revision": state["revision"],
        }

    def export(self, after: int, limit: int) -> dict[str, Any]:
        return self.ledger.export(after, limit)

    def recent(self) -> list[dict[str, Any]]:
        return self.ledger.recent()
