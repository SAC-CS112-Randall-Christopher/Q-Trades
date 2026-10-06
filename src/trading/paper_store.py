"""PostgreSQL atomic projection and append-only, per-asset balanced financial journal."""

import hashlib
import json
import time
from collections.abc import Callable
from decimal import Decimal
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Concatenate

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from trading.execution_profiles import LEGACY_EXECUTION
from trading.paper_engine import PaperEngine, initial_state


def _locked[**P, R](
    method: Callable[Concatenate["PaperStore", P], R],
) -> Callable[Concatenate["PaperStore", P], R]:
    """Keep complete reader scopes outside another thread's writer transaction."""

    @wraps(method)
    def call(store: "PaperStore", /, *args: P.args, **kwargs: P.kwargs) -> R:
        with store.transaction_lock:
            return method(store, *args, **kwargs)

    return call


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
CREATE INDEX IF NOT EXISTS paper_trade_entry ON paper_events(account, (body->>'symbol'), at)
WHERE kind='fill' AND body->>'side'='buy';
CREATE INDEX IF NOT EXISTS paper_research_scope
ON paper_events(account, (body->>'symbol'), kind, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS lab_proposal_once ON paper_events ((body->>'proposal_id'))
WHERE kind='lab_trial_reserved';
CREATE INDEX IF NOT EXISTS lab_trial_events ON paper_events ((body->>'trial_id'), id DESC)
WHERE kind LIKE 'lab_%';
CREATE TABLE IF NOT EXISTS paper_lab_archives (
  account text PRIMARY KEY, trial_id text NOT NULL, retired_at double precision NOT NULL,
  state jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS lab_archives_trial ON paper_lab_archives(trial_id, account);
CREATE INDEX IF NOT EXISTS paper_learning_report ON paper_events ((body->>'request_id'))
WHERE kind='learning_report_retained';
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
CREATE OR REPLACE TRIGGER lab_archives_immutable BEFORE UPDATE OR DELETE ON paper_lab_archives
FOR EACH ROW EXECUTE FUNCTION paper_immutable();
"""


def load_dsn(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    dsn = payload.get("dsn")
    if not isinstance(dsn, str) or not dsn:
        raise ValueError("Local paper database settings are missing")
    return dsn


def _projection_float(value: str) -> float | int:
    """Match JSONB's numeric output before a cached value reaches the engine."""
    if "e" in value:
        # JSONB writes numeric without exponent notation, which can make a
        # previously floating token an integer on the ordinary database read.
        number = json.loads(format(Decimal(value), "f"))
        assert isinstance(number, (float, int))
        return number
    # PostgreSQL numeric removes the sign from zero while retaining its scale.
    return 0.0 if value == "-0.0" else float(value)


class PaperStore:
    def __init__(self, dsn: str, *, owner: bool = False, projection_cache_bytes: int = 8 * 1024**2):
        if not 0 <= projection_cache_bytes <= 8 * 1024**2:
            raise ValueError("Projection RAM cache must be bounded to at most 8 MiB")
        self.transaction_lock = RLock()
        self.owner = owner
        self._projection_cache_limit = projection_cache_bytes if owner else 0
        self._projection_cache: tuple[int, str, str, str] | None = None
        self._projection_cache_hits = 0
        self._projection_cache_misses = 0
        self.last_commit_receipt: dict[str, Any] | None = None
        self.last_transaction_diagnostics: dict[str, float] | None = None
        self._transaction_lock_wait_ms = 0.0
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

    @_locked
    def close(self) -> None:
        self._projection_cache = None
        self.connection.close()

    def projection_cache_info(self) -> dict[str, int | bool]:
        with self.transaction_lock:
            return {
                "enabled": bool(self._projection_cache_limit),
                "limit_bytes": self._projection_cache_limit,
                "cached_bytes": len(self._projection_cache[3]) if self._projection_cache else 0,
                "hits": self._projection_cache_hits,
                "misses": self._projection_cache_misses,
            }

    @_locked
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

    def _append(self, engine: PaperEngine, revision: int) -> list[dict[str, Any]]:
        references = []
        for index, event in enumerate(engine.events):
            if event["kind"] == "lab_account_archived":
                saved = event["body"]["state"]
                balances = self.connection.execute(
                    "SELECT asset,bucket,sum(amount) AS amount FROM paper_journal "
                    "WHERE account=%s GROUP BY asset,bucket",
                    (event["account"],),
                ).fetchall()
                totals = {(r["asset"], r["bucket"]): r["amount"] for r in balances}
                if (
                    saved["positions"]
                    or saved["pending"]
                    or totals.get(("USD", "reserved"), Decimal(0)) != 0
                    or totals.get(("USD", "cash"), Decimal(0)) != Decimal(saved["cash"])
                    or totals.get(("USD", "fake_funding"), Decimal(0)) != -Decimal(saved["funding"])
                    or totals.get(("USD", "fees"), Decimal(0)) != Decimal(saved["fees"])
                    or any(r["amount"] != 0 for r in balances if r["bucket"] == "inventory")
                ):
                    raise ValueError("Financial closure does not reconcile; slot remains managed")
                self.connection.execute(
                    "INSERT INTO paper_lab_archives VALUES (%s,%s,%s,%s)",
                    (event["account"], event["body"]["trial_id"], event["at"], Jsonb(saved)),
                )
            row = self.connection.execute(
                "INSERT INTO paper_events(revision, at, kind, account, body) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (revision, event["at"], event["kind"], event["account"], Jsonb(event["body"])),
            ).fetchone()
            assert row is not None
            references.append(
                {
                    "event_index": index,
                    "event_id": row["id"],
                    "revision": revision,
                    "kind": event["kind"],
                    "account": event["account"],
                }
            )
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
        return references

    def transact(
        self,
        now: float,
        work: Callable[[PaperEngine], None],
    ) -> dict[str, Any]:
        state, _ = self.transact_with_receipt(now, work)
        return state

    def transact_with_receipt(
        self,
        now: float,
        work: Callable[[PaperEngine], None],
        *,
        capture_projection: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return this commit's state and provenance together under the writer lock."""
        waiting = time.perf_counter()
        with self.transaction_lock:
            self._transaction_lock_wait_ms = (time.perf_counter() - waiting) * 1000
            try:
                state = self._transact(now, work, capture_projection=capture_projection)
            except BaseException:
                # Includes lost commit acknowledgments. The next transaction must
                # reread authoritative state instead of trusting an uncertain copy.
                self._projection_cache = None
                raise
            assert self.last_commit_receipt is not None
            return state, self.last_commit_receipt

    def _transact(
        self,
        now: float,
        work: Callable[[PaperEngine], None],
        *,
        capture_projection: bool = False,
    ) -> dict[str, Any]:
        self.require_owner()
        self.last_commit_receipt = None
        self.last_transaction_diagnostics = None
        stages = {"writer_lock_wait": self._transaction_lock_wait_ms}
        started = time.perf_counter()
        cache_safe = bool(self._projection_cache_limit) and (
            self.connection.info.transaction_status == TransactionStatus.IDLE
        )
        if not cache_safe:
            # A nested transaction may roll back after our savepoint completes.
            self._projection_cache = None
        with self.connection.transaction():
            row = self.connection.execute(
                "SELECT revision,xmin::text AS version,ctid::text AS location "
                "FROM paper_state WHERE id=1 FOR UPDATE"
                if cache_safe
                else "SELECT * FROM paper_state WHERE id=1 FOR UPDATE"
            ).fetchone()
            if not row:
                raise RuntimeError("Paper account was not initialized")
            if cache_safe:
                token = (row["revision"], row["version"], row["location"])
                cached = self._projection_cache
                if cached and cached[:3] == token:
                    # Fresh detached objects: callers and failed work cannot mutate
                    # the committed RAM copy. Row locking/version checks stay in SQL.
                    state: dict[str, Any] = json.loads(cached[3], parse_float=_projection_float)
                    self._projection_cache_hits += 1
                else:
                    self._projection_cache = None
                    stored = self.connection.execute(
                        "SELECT body FROM paper_state WHERE id=1"
                    ).fetchone()
                    assert stored is not None
                    state = stored["body"]
                    self._projection_cache_misses += 1
            else:
                state = row["body"]
            measured = time.perf_counter()
            stages["read_decode"] = (measured - started) * 1000
            if state.get("schema") != 1:
                raise RuntimeError("Unsupported paper state version")
            engine = PaperEngine(state, now)
            # Older projections duplicated complete receipts. Verify their immutable
            # journal before compacting; hashes and financial accounts are unchanged.
            from trading.paper_learning import report_summary

            for request_id, receipt in state.get("learning", {}).get("reports", {}).items():
                if receipt.get("storage") != "immutable-journal-v1":
                    retained = self.learning_report(request_id, receipt["sha256"])
                    if retained is None:
                        raise ValueError("Retained report journal missing; projection not changed")
                    state["learning"]["reports"][request_id] = report_summary(retained)
            verified = time.perf_counter()
            stages["projection_verification"] = (verified - measured) * 1000
            work(engine)
            calculated = time.perf_counter()
            stages["financial_calculation"] = (calculated - verified) * 1000
            engine.assert_invariants()
            checked = time.perf_counter()
            stages["invariant_check"] = (checked - calculated) * 1000
            revision = row["revision"] + 1
            references = self._append(engine, revision)
            appended = time.perf_counter()
            stages["journal_append"] = (appended - checked) * 1000
            encoding_ms = 0.0
            projection_sha256: str | None = None
            committed_encoding: str | None = None

            def encode_projection(value: Any) -> str:
                nonlocal encoding_ms, projection_sha256, committed_encoding
                encoding_started = time.perf_counter()
                # PostgreSQL JSONB discards whitespace/key ordering. Selected
                # capture uses the existing exact canonical evidence encoding
                # once, binding its digest to the projection actually committed.
                encoded = json.dumps(
                    value,
                    sort_keys=capture_projection,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if capture_projection:
                    projection_sha256 = hashlib.sha256(encoded.encode()).hexdigest()
                # This encoder uses ASCII JSON: character count equals payload
                # bytes. Only one bounded immutable string survives the commit.
                if cache_safe and len(encoded) <= self._projection_cache_limit:
                    committed_encoding = encoded
                encoding_ms += (time.perf_counter() - encoding_started) * 1000
                return encoded

            saved = self.connection.execute(
                "UPDATE paper_state SET revision=%s, body=%s WHERE id=1 "
                "RETURNING xmin::text AS version,ctid::text AS location",
                (revision, Jsonb(engine.state, dumps=encode_projection)),
            ).fetchone()
            assert saved is not None
            updated = time.perf_counter()
            stages["projection_encode"] = encoding_ms
            stages["projection_update"] = max(0, (updated - appended) * 1000 - encoding_ms)
        stages["database_commit"] = (time.perf_counter() - updated) * 1000
        if cache_safe and committed_encoding is not None:
            self._projection_cache = (
                revision,
                saved["version"],
                saved["location"],
                committed_encoding,
            )
        else:
            self._projection_cache = None
        self.last_transaction_diagnostics = {key: round(value, 3) for key, value in stages.items()}
        self.last_commit_receipt = {
            "revision": revision,
            "events": references,
            "committed_at": time.time(),
            "commit_mono": time.monotonic(),
        }
        if projection_sha256 is not None:
            self.last_commit_receipt["projection_sha256"] = projection_sha256
        return engine.state

    @_locked
    def read(self) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT body, revision FROM paper_state WHERE id=1"
        ).fetchone()
        if not row:
            raise RuntimeError("Missing paper account")
        return {**row["body"], "revision": row["revision"]}

    def lab_reserve(self, now: float, proposal: Any) -> dict[str, Any]:
        from trading.autonomous_finance import reserve

        result: dict[str, Any] = {}

        def apply(engine: PaperEngine) -> None:
            prior = self.connection.execute(
                "SELECT body FROM paper_events WHERE kind='lab_trial_reserved' "
                "AND body->>'proposal_id'=%s ORDER BY id LIMIT 1",
                (proposal.request_id,),
            ).fetchone()
            if prior:
                if prior["body"]["contract"]["proposal"] != proposal.model_dump():
                    raise ValueError("Accepted proposal retry differs from its permanent intent")
                result.update(status="already_reserved", trial_id=prior["body"]["id"])
            else:
                result.update(reserve(engine, proposal))

        self.transact(now, apply)
        return result

    @_locked
    def lab_history(self, before: int = 0, limit: int = 20) -> dict[str, Any]:
        rows = self.connection.execute(
            "SELECT id,at,body FROM paper_events WHERE kind='lab_trial_reserved' "
            "AND (%s=0 OR id<%s) ORDER BY id DESC LIMIT %s",
            (before, before, limit + 1),
        ).fetchall()
        page = rows[:limit]
        for row in page:
            terminal = self.connection.execute(
                "SELECT kind,at,body FROM paper_events WHERE kind IN "
                "('lab_trial_scored','lab_trial_retired') AND body->>'trial_id'=%s "
                "ORDER BY id DESC LIMIT 2",
                (row["body"]["id"],),
            ).fetchall()
            row["decisions"] = terminal
        return {
            "trials": page,
            "has_more": len(rows) > limit,
            "next_before": page[-1]["id"] if page else before,
        }

    @_locked
    def archived_account(self, name: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM paper_lab_archives WHERE account=%s", (name,)
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def learning_report(self, request_id: str, sha256: str) -> dict[str, Any] | None:
        from trading.paper_learning import verify_report

        rows = self.connection.execute(
            "SELECT body FROM paper_events WHERE kind='learning_report_retained' "
            "AND body->>'request_id'=%s ORDER BY id LIMIT 2",
            (request_id,),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("Duplicate retained report journal; no authority granted")
        return verify_report(rows[0]["body"], request_id, sha256)

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
        # The driver serializes individual commands, not whole transaction scopes.
        # Candle collection shares the sole writer connection with threaded controls.
        with self.transaction_lock, self.connection.transaction():
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

    @_locked
    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(
            self.connection.execute(
                "SELECT id, at, kind, body FROM paper_events WHERE account='primary' "
                "AND kind NOT IN ('decision','equity') ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        )

    @_locked
    def numerical_inputs(self, as_of: float) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id,at,body FROM paper_events WHERE kind='market_minute' "
            "AND at<=%s AND body->>'symbol'='BTCUSD' ORDER BY id DESC LIMIT 121",
            (as_of,),
        ).fetchall()
        return sorted(rows, key=lambda r: (r["at"], r["id"]))

    @_locked
    def forward_windows(self, now: float) -> dict[str, Any]:
        rows = self.connection.execute(
            "SELECT id,body FROM paper_events WHERE kind='economics_window' AND at<=%s "
            "ORDER BY id DESC LIMIT 513",
            (now,),
        ).fetchall()
        return {
            "windows": [r["body"] for r in reversed(rows[:512])],
            "truncated": len(rows) > 512,
            "event_ids": [r["id"] for r in rows[:512]],
        }

    @_locked
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

    @_locked
    def trade_history(
        self,
        *,
        before: int = 0,
        limit: int = 50,
        account: str | None = None,
        status: str = "all",
        frames: dict[str, dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        from trading.trade_history import closed_row, open_row

        if not 1 <= limit <= 100 or before < 0 or status not in {"all", "open", "closed"}:
            raise ValueError("Invalid trade history page")
        now = time.time() if now is None else now
        state = self.read()
        accounts = state["accounts"]
        if account is not None and account not in accounts and not self.archived_account(account):
            raise KeyError("Paper account not found")
        closed = []
        if status != "open":
            rows = self.connection.execute(
                "SELECT id,revision,account,at,body FROM paper_events WHERE kind='trade_closed' "
                "AND (%s=0 OR id<%s) AND (%s::text IS NULL OR account=%s) "
                "ORDER BY id DESC LIMIT %s",
                (before, before, account, account, limit + 1),
            ).fetchall()
            for event in rows[:limit]:
                entries = self.connection.execute(
                    "SELECT id,body FROM paper_events WHERE kind='fill' AND body->>'side'='buy' "
                    "AND account=%s AND body->>'symbol'=%s AND at=%s AND revision<=%s "
                    "ORDER BY id DESC LIMIT 2",
                    (
                        event["account"],
                        event["body"]["symbol"],
                        event["body"]["opened_at"],
                        event["revision"],
                    ),
                ).fetchall()
                closed.append(closed_row(event, entries))
        else:
            rows = []
        opened = []
        if before == 0 and status != "closed":
            for name, saved in accounts.items():
                if account is None or name == account:
                    for symbol, position in saved["positions"].items():
                        opened.append(
                            open_row(name, symbol, position, saved, (frames or {}).get(symbol), now)
                        )
        opened.sort(key=lambda r: (r["opened_at"], r["id"]), reverse=True)
        records = opened + closed
        records.sort(key=lambda r: (r["closed_at"] or r["opened_at"], r["id"]), reverse=True)
        for record in records:
            record["label"] = accounts.get(record["account"], {}).get("label", record["account"])
            record["archived"] = record["account"] not in accounts
        return {
            "records": records,
            "has_more": len(rows) > limit,
            "next_before": rows[limit - 1]["id"] if len(rows) > limit else before,
            "before": before,
            "observed_at": now,
            "revision": state["revision"],
            "open_count": len(opened),
            "closed_count": len(closed),
        }

    @_locked
    def research_account(self, account: str, cutoff: float | None = None) -> dict[str, Any]:
        """Select one durable identity without loading all account/history projections."""
        from trading.account_purpose import require_research_account

        row = self.connection.execute(
            "SELECT revision,(body->'accounts'->%s)-'recent_trades'-'economics_windows' AS account,"
            "(body->>'last_tick')::double precision AS state_at FROM paper_state WHERE id=1",
            (account,),
        ).fetchone()
        if row is None:
            raise KeyError("Paper state not found")
        if cutoff is None:
            cutoff = time.time()
        if row["state_at"] > cutoff:
            raise ValueError("Financial snapshot is later than the requested cutoff; retry")
        saved = row["account"]
        archive = None
        if saved is None:
            archive = self.connection.execute(
                "SELECT trial_id,retired_at,state-'recent_trades'-'economics_windows' AS state "
                "FROM paper_lab_archives WHERE account=%s AND retired_at<=%s",
                (account, cutoff),
            ).fetchone()
            if archive is None:
                raise KeyError("Paper account not found")
            saved = {
                k: v
                for k, v in archive["state"].items()
                if k not in {"recent_trades", "economics_windows"}
            }
        require_research_account(saved, account)
        maximum = self.connection.execute(
            "SELECT coalesce(max(id),0) AS id FROM paper_events WHERE at<=%s",
            (cutoff,),
        ).fetchone()
        return {
            "account": account,
            "state": saved,
            "revision": row["revision"],
            "cutoff": cutoff,
            "maximum_event_id": maximum["id"] if maximum else 0,
            "archived": archive is not None,
            "retired_at": archive["retired_at"] if archive else None,
            "trial_id": saved.get("lab_trial", archive["trial_id"] if archive else None),
        }

    @_locked
    def research_events(
        self,
        account: str,
        symbol: str,
        cutoff: float,
        maximum: int,
        *,
        before: int = 0,
        start: float = 0,
    ) -> dict[str, Any]:
        """Bounded permanent events pinned to immutable membership and observation cutoff."""
        rows = self.connection.execute(
            "SELECT id,revision,account,at,kind,body FROM paper_events WHERE account=%s "
            "AND body->>'symbol'=%s AND kind='trade_closed' AND id<=%s "
            "AND at>=%s AND at<=%s AND (%s=0 OR id<%s) ORDER BY id DESC LIMIT 21",
            (account, symbol, maximum, start, cutoff, before, before),
        ).fetchall()
        return {
            "events": rows[:20],
            "has_more": len(rows) > 20,
            "next_before": rows[19]["id"] if len(rows) > 20 else None,
        }

    @_locked
    def research_cost_groups(
        self, snapshot: dict[str, Any], symbol: str, *, start: float
    ) -> dict[str, Any]:
        """Bounded identical-cohort costs; absent historical policies stay unknown."""
        from trading.account_purpose import require_research_account

        require_research_account(snapshot["state"], snapshot["account"])
        rows = self.connection.execute(
            "SELECT body->>'version' AS version,body->>'execution_profile' AS execution_profile,"
            "body->>'holding_horizon' AS holding_horizon,count(*) AS trades,"
            "coalesce(sum((body->>'pnl')::numeric),0)::text AS net_pnl,"
            "coalesce(sum((body->>'fees')::numeric),0)::text AS fees "
            "FROM paper_events WHERE account=%s AND body->>'symbol'=%s "
            "AND kind='trade_closed' AND id<=%s AND at>=%s AND at<=%s "
            "GROUP BY 1,2,3 ORDER BY 1,2,3 LIMIT 17",
            (snapshot["account"], symbol, snapshot["maximum_event_id"], start, snapshot["cutoff"]),
        ).fetchall()
        return {"groups": rows[:16], "more_groups": len(rows) > 16, "maximum_groups": 16}

    @_locked
    def research_outcomes(
        self, snapshot: dict[str, Any], symbol: str, *, start: float = 0
    ) -> dict[str, Any]:
        from trading.account_purpose import require_research_account
        from trading.paper_economics import sample

        require_research_account(snapshot["state"], snapshot["account"])

        account, cutoff, maximum = (snapshot[k] for k in ("account", "cutoff", "maximum_event_id"))
        totals = self.connection.execute(
            "SELECT count(*) AS trades,coalesce(sum((body->>'pnl')::numeric),0)::text AS net_pnl,"
            "coalesce(sum((body->>'fees')::numeric),0)::text AS fees,"
            "min((body->>'opened_at')::double precision) AS first_opened_at "
            "FROM paper_events WHERE account=%s AND body->>'symbol'=%s "
            "AND kind='trade_closed' AND id<=%s AND at>=%s AND at<=%s",
            (account, symbol, maximum, start, cutoff),
        ).fetchone()
        saved = snapshot["state"]
        account_totals = sample(
            saved, cutoff, final_at=snapshot["retired_at"] if snapshot["archived"] else None
        )
        page = self.research_events(account, symbol, cutoff, maximum, start=start)
        comparison = (
            self.connection.execute(
                "SELECT id,at,body FROM paper_events WHERE kind='lab_trial_scored' "
                "AND body->>'trial_id'=%s AND id<=%s AND at<=%s ORDER BY id DESC LIMIT 1",
                (snapshot["trial_id"], maximum, cutoff),
            ).fetchone()
            if snapshot["trial_id"]
            else None
        )
        return {
            "account": account,
            "symbol": symbol,
            "archived": snapshot["archived"],
            "market_totals": dict(totals) if totals else None,
            **page,
            "account_totals": account_totals,
            "account_totals_basis": (
                "Final historical reconciled cash-only account; no current quote valuation"
                if account_totals.get("final")
                else "Cumulative whole account at captured revision; current marks may be missing"
            ),
            "accounting_at": snapshot["retired_at"]
            if account_totals.get("final")
            else saved.get("valuation_at"),
            "queried_at": cutoff,
            "open_holdings": saved["positions"],
            "pending_orders": saved["pending"],
            "max_drawdown": saved["max_drawdown"],
            "operating_daily_usd": saved.get("operating_daily_usd"),
            "trial_id": snapshot["trial_id"],
            "trial_comparison": dict(comparison) if comparison else None,
            "comparison_basis": "Recorded matched whole-account review, unavailable until maturity",
            "scope": "Permanent selected-account market events; net P/L already includes fees. "
            "Cumulative account equity includes cash and open holdings; stale valuation "
            "remains unavailable. Separate accounts have separate capital.",
            "interval": {"start": start, "end": cutoff},
            "snapshot": {k: v for k, v in snapshot.items() if k != "state"},
        }

    @_locked
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
        archived_errors = self.connection.execute(
            "WITH balances AS (SELECT account,asset,bucket,sum(amount) AS amount "
            "FROM paper_journal GROUP BY account,asset,bucket) "
            "SELECT DISTINCT a.account FROM paper_lab_archives a LEFT JOIN balances b "
            "ON b.account=a.account WHERE (b.bucket='cash' AND "
            "b.amount<>(a.state->>'cash')::numeric) OR (b.bucket='reserved' AND b.amount<>0) "
            "OR (b.bucket='inventory' AND b.amount<>0) OR (b.bucket='fees' AND "
            "b.amount<>(a.state->>'fees')::numeric) OR (b.bucket='fake_funding' AND "
            "b.amount<>-(a.state->>'funding')::numeric) LIMIT 20"
        ).fetchall()
        errors.extend(f"{r['account']}: archived financial state mismatch" for r in archived_errors)
        return {
            "balanced": bool(imbalanced and imbalanced["n"] == 0) and not errors,
            "imbalanced_events": imbalanced["n"] if imbalanced else None,
            "projection_errors": errors,
            "revision": state["revision"],
        }

    @_locked
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
