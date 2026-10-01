"""Scoped receipts, owned leases and verified rollover through existing research storage."""

import base64
import copy
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Any

from trading.research_storage import ResearchStorage, StoragePlan
from trading.station import VERSION

MAX_RESULT_BYTES = 131072
MAX_RUNS = 5000
LEASE_SECONDS = 60


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ToolJournal:
    def __init__(self, path: Path, storage_plan: StoragePlan | None = None):
        self.lock = RLock()
        self.owner = secrets.token_hex(16)
        self.storage_plan = storage_plan
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=1)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA max_page_count=16384;
            PRAGMA journal_size_limit=8388608;
            CREATE TABLE IF NOT EXISTS tool_runs (
                id INTEGER PRIMARY KEY, started REAL NOT NULL, finished REAL,
                tool TEXT NOT NULL, symbol TEXT NOT NULL, version TEXT NOT NULL,
                actor TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                result_sha256 TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS tool_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(tool_runs)")}
        with self.connection:
            for name, definition in {
                "owner": "TEXT",
                "lease_until": "REAL",
                "request_id": "TEXT",
                "query": "TEXT",
                "account": "TEXT NOT NULL DEFAULT 'primary'",
            }.items():
                if name not in columns:
                    self.connection.execute(f"ALTER TABLE tool_runs ADD COLUMN {name} {definition}")
            self.connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS tool_request ON tool_runs(request_id)"
            )
            for name, value in {
                "namespace": secrets.token_hex(16),
                "cursor_key": secrets.token_hex(32),
            }.items():
                self.connection.execute(
                    "INSERT OR IGNORE INTO tool_meta VALUES(?,?)", (name, value)
                )
            self.connection.execute(
                "INSERT OR IGNORE INTO tool_meta VALUES('next_id',"
                "(SELECT CAST(coalesce(max(id),0)+1 AS TEXT) FROM tool_runs))"
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO tool_meta VALUES('logical_count',"
                "(SELECT CAST(count(*) AS TEXT) FROM tool_runs))"
            )
        self.namespace = self._meta("namespace")
        self.key = bytes.fromhex(self._meta("cursor_key"))
        # Readers never interrupt a different live owner merely by opening storage.

    def _meta(self, key: str) -> str:
        return str(
            self.connection.execute("SELECT value FROM tool_meta WHERE key=?", (key,)).fetchone()[0]
        )

    def _storage(self) -> ResearchStorage:
        if self.storage_plan is None:
            raise ValueError("Tool journal capacity requires configured research storage")
        store = ResearchStorage(self.storage_plan)
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS tool_receipt_index(
                namespace TEXT NOT NULL, id INTEGER NOT NULL, reference TEXT NOT NULL,
                metadata TEXT NOT NULL, request_id TEXT, query TEXT,
                PRIMARY KEY(namespace,id));
            CREATE UNIQUE INDEX IF NOT EXISTS cold_tool_request
              ON tool_receipt_index(namespace,request_id);
        """)
        return store

    def _rollover(self) -> None:
        page_size = self.connection.execute("PRAGMA page_size").fetchone()[0]
        pages = self.connection.execute("PRAGMA page_count").fetchone()[0]
        free = self.connection.execute("PRAGMA freelist_count").fetchone()[0]
        if (
            self.connection.execute("SELECT count(*) FROM tool_runs").fetchone()[0] < MAX_RUNS
            and (pages - free) * page_size < 48 * 1024**2
        ):
            return
        store = self._storage()
        try:
            rows = self.connection.execute(
                "SELECT * FROM tool_runs WHERE status IN ('completed','failed','interrupted') "
                "ORDER BY id LIMIT 8"
            ).fetchall()
            if not rows:
                raise ValueError("Tool journal capacity awaits owned work finalization")
            for row in rows:
                packet = {
                    "kind": "tool_receipt",
                    "at": row["finished"] or row["started"],
                    "namespace": self.namespace,
                    "receipt": dict(row),
                }
                reference = store.append([packet], time.time())[0]
                if store.reopen(reference) != packet:
                    raise ValueError("Archived tool receipt verification failed")
                with store.db:
                    store.db.execute(
                        "INSERT OR IGNORE INTO tool_receipt_index VALUES(?,?,?,?,?,?)",
                        (
                            self.namespace,
                            row["id"],
                            reference,
                            encoded(self._metadata(dict(row))),
                            row["request_id"],
                            row["query"],
                        ),
                    )
                    saved = store.db.execute(
                        "SELECT reference FROM tool_receipt_index WHERE namespace=? AND id=?",
                        (self.namespace, row["id"]),
                    ).fetchone()
                    if saved is None or store.reopen(saved[0]) != packet:
                        raise ValueError("Archived receipt index differs; hot receipt retained")
                # Exact cold commit precedes hot removal; restart accepts either copy.
                with self.connection:
                    self.connection.execute("DELETE FROM tool_runs WHERE id=?", (row["id"],))
        finally:
            store.close()

    def start(
        self,
        tool: str,
        symbol: str,
        *,
        account: str = "primary",
        request_id: str | None = None,
        query: dict[str, Any] | None = None,
    ) -> int:
        identity = encoded(query or {"tool": tool, "symbol": symbol, "account": account})
        with self.lock:
            if request_id:
                old = self.connection.execute(
                    "SELECT id,query FROM tool_runs WHERE request_id=?", (request_id,)
                ).fetchone()
                if old is None and self.storage_plan:
                    store = self._storage()
                    try:
                        old = store.db.execute(
                            "SELECT id,query FROM tool_receipt_index "
                            "WHERE namespace=? AND request_id=?",
                            (self.namespace, request_id),
                        ).fetchone()
                    finally:
                        store.close()
                if old:
                    if old["query"] != identity:
                        raise ValueError("Request ID belongs to a different evidence scope")
                    self._recover()
                    return int(old["id"])
            self._recover()
            self._rollover()
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                run_id = int(self._meta("next_id"))
                self.connection.execute(
                    "INSERT INTO tool_runs(id,started,tool,symbol,version,actor,status,owner,"
                    "lease_until,request_id,query,account) "
                    "VALUES(?,?,?,?,?,'local_operator','running',?,?,?,?,?)",
                    (
                        run_id,
                        time.time(),
                        tool,
                        symbol,
                        VERSION,
                        self.owner,
                        time.time() + LEASE_SECONDS,
                        request_id,
                        identity,
                        account,
                    ),
                )
                self.connection.execute(
                    "UPDATE tool_meta SET value=? WHERE key='next_id'", (str(run_id + 1),)
                )
                self.connection.execute(
                    "UPDATE tool_meta SET value=CAST(value AS INTEGER)+1 WHERE key='logical_count'"
                )
            return run_id

    def _recover(self) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE tool_runs SET status='interrupted',finished=?,"
                "error='Owned tool lease expired before answer persistence' "
                "WHERE status='running' AND coalesce(lease_until,0)<?",
                (time.time(), time.time()),
            )
        for row in self.connection.execute(
            "SELECT id FROM tool_runs WHERE status='finalizing' "
            "AND (owner=? OR coalesce(lease_until,0)<?) ORDER BY id LIMIT 8",
            (self.owner, time.time()),
        ).fetchall():
            self._finalize(row[0])

    def finish(self, run_id: int, result: dict[str, Any] | None, error: str | None) -> None:
        body = encoded(result) if result is not None else None
        if body and len(body.encode("utf-8")) > MAX_RESULT_BYTES:
            body, error = None, "Result exceeded the registered evidence size limit"
        with self.lock:
            with self.connection:
                self.connection.execute(
                    "UPDATE tool_runs SET finished=?,status='finalizing',result=?,result_sha256=?,"
                    "error=?,lease_until=? WHERE id=? AND status='running' AND owner=?",
                    (
                        time.time(),
                        body,
                        hashlib.sha256(body.encode()).hexdigest() if body else None,
                        error,
                        time.time() + LEASE_SECONDS,
                        run_id,
                        self.owner,
                    ),
                )
            self._finalize(run_id)

    def _finalize(self, run_id: int) -> None:
        row = self.connection.execute("SELECT * FROM tool_runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["status"] != "finalizing":
            return
        if row["owner"] != self.owner and row["lease_until"] > time.time():
            return
        body = row["result"]
        result = json.loads(body) if body else None
        if self.storage_plan and result and result.get("envelope"):
            store = self._storage()
            try:
                packet = {
                    "kind": "tool_detail",
                    "at": row["finished"],
                    "namespace": self.namespace,
                    "run_id": run_id,
                    "result": copy.deepcopy(result),
                }
                reference = store.append([packet], time.time())[0]
                if store.reopen(reference) != packet:
                    raise ValueError("Exact tool detail verification failed")
                result["envelope"]["detail_reference"] = reference
                if row["tool"] == "market_evidence":
                    facts = result["result"]
                    detail = facts["detail"]
                    detail["candles"] = detail["candles"][-1:]
                    detail["indicators"]["points"] = detail["indicators"]["points"][-1:]
                    detail["experiments"] = {"scope": "Captured comparison in exact detail"}
                    detail["paper_events"] = []
                    facts["live"]["trades"] = facts["live"]["trades"][-1:]
                    if facts["live"]["book"]:
                        for side in ("bids", "asks"):
                            facts["live"]["book"][side] = facts["live"]["book"][side][:1]
                    result["envelope"]["overview_scope"] = (
                        "Latest captured point; all saved rows remain in exact detail"
                    )
                elif row["tool"] == "outcome_review":
                    result["result"]["events"] = []
                    result["envelope"]["overview_scope"] = (
                        "Durable totals; captured event page remains in exact detail"
                    )
                body = encoded(result)
            finally:
                store.close()
        if result and result.get("envelope"):
            result["envelope"]["overview_utf8_bytes"] = 0
            for _ in range(4):
                result["envelope"]["overview_utf8_bytes"] = len(encoded(result).encode("utf-8"))
            body = encoded(result)
        if body and len(body.encode()) > MAX_RESULT_BYTES:
            raise ValueError("Final receipt exceeds the registered evidence size limit")
        with self.connection:
            self.connection.execute(
                "UPDATE tool_runs SET status=?,result=?,result_sha256=? "
                "WHERE id=? AND status='finalizing'",
                (
                    "failed" if row["error"] else "completed",
                    body,
                    hashlib.sha256(body.encode()).hexdigest() if body else None,
                    run_id,
                ),
            )

    def cursor(self, claims: dict[str, Any]) -> str:
        payload = encoded(
            dict(
                claims, namespace=self.namespace, actor="local_operator", expires=time.time() + 3600
            )
        ).encode()
        return (
            base64.urlsafe_b64encode(payload).decode()
            + "."
            + hmac.new(self.key, payload, hashlib.sha256).hexdigest()
        )

    def claims(self, cursor: str, *, kind: str) -> dict[str, Any]:
        try:
            body, signature = cursor.split(".")
            payload = base64.b64decode(body, altchars=b"-_", validate=True)
            if not hmac.compare_digest(
                hmac.new(self.key, payload, hashlib.sha256).hexdigest(), signature
            ):
                raise ValueError("signature")
            value: dict[str, Any] = json.loads(payload)
            if (
                value["namespace"] != self.namespace
                or value["actor"] != "local_operator"
                or value["kind"] != kind
                or value["expires"] < time.time()
            ):
                raise ValueError("scope/expiry")
            return value
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(
                "Evidence cursor is invalid, expired or belongs to another scope"
            ) from exc

    @staticmethod
    def _metadata(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: row[key]
            for key in (
                "id",
                "started",
                "finished",
                "tool",
                "symbol",
                "actor",
                "account",
                "status",
                "error",
            )
        }

    def recent(self, cursor: str | None = None) -> dict[str, Any]:
        with self.lock:
            before = (
                int(self.claims(cursor, kind="runs")["before"])
                if cursor
                else int(self._meta("next_id"))
            )
            rows = self.connection.execute(
                "SELECT * FROM tool_runs WHERE id<? ORDER BY id DESC LIMIT 21", (before,)
            ).fetchall()
            merged = {row["id"]: self._metadata(dict(row)) for row in rows}
            if self.storage_plan:
                store = self._storage()
                try:
                    for row in store.db.execute(
                        "SELECT id,metadata FROM tool_receipt_index WHERE namespace=? AND id<? "
                        "ORDER BY id DESC LIMIT 21",
                        (self.namespace, before),
                    ).fetchall():
                        merged.setdefault(row["id"], json.loads(row["metadata"]))
                finally:
                    store.close()
            page = sorted(merged.values(), key=lambda row: row["id"], reverse=True)
            return {
                "runs": page[:20],
                "total": int(self._meta("logical_count")),
                "capacity": MAX_RUNS,
                "capacity_basis": "hot index; verified archive extends logical history",
                "next_cursor": self.cursor({"kind": "runs", "before": page[19]["id"]})
                if len(page) > 20
                else None,
            }

    def get(self, run_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM tool_runs WHERE id=?", (run_id,)
            ).fetchone()
            value = dict(row) if row else None
            if value is None and self.storage_plan:
                store = self._storage()
                try:
                    cold = store.db.execute(
                        "SELECT reference FROM tool_receipt_index WHERE namespace=? AND id=?",
                        (self.namespace, run_id),
                    ).fetchone()
                    if cold:
                        packet = store.reopen(cold[0])
                        if (
                            packet["namespace"] != self.namespace
                            or packet["receipt"]["id"] != run_id
                        ):
                            raise ValueError("Archived receipt membership differs")
                        value = packet["receipt"]
                finally:
                    store.close()
            if value is None:
                return None
            body = value["result"]
            if body and hashlib.sha256(body.encode()).hexdigest() != value["result_sha256"]:
                raise ValueError("Tool receipt checksum differs; no live substitute")
            for key in ("owner", "lease_until"):
                value.pop(key, None)
            value["result"] = json.loads(body) if body else None
            return value

    def detail(self, run_id: int, cursor: str | None = None) -> dict[str, Any]:
        with self.lock:
            receipt = self.get(run_id)
            if not receipt or not receipt["result"]:
                raise LookupError("Captured tool detail is unavailable")
            reference = receipt["result"].get("envelope", {}).get("detail_reference")
            scope = {
                "run_id": run_id,
                "reference": reference,
                "account": receipt["account"],
                "query": receipt["query"],
                "sha256": receipt["result_sha256"],
            }
            offset = 0
            if cursor:
                claims = self.claims(cursor, kind="detail")
                if any(claims.get(key) != value for key, value in scope.items()):
                    raise ValueError("Evidence cursor belongs to a different receipt/snapshot")
                offset = int(claims["offset"])
            result = receipt["result"]
            if reference:
                store = self._storage()
                try:
                    packet = store.reopen(reference)
                    if packet["namespace"] != self.namespace or packet["run_id"] != run_id:
                        raise ValueError("Captured detail membership differs")
                    result = packet["result"]
                finally:
                    store.close()
            facts = copy.deepcopy(result["result"])
            total = 1
            if receipt["tool"] == "market_evidence":
                detail = facts["detail"]
                total = len(detail["candles"])
                detail["candles"] = detail["candles"][offset : offset + 30]
                times = {bar["open_ms"] for bar in detail["candles"]}
                detail["indicators"]["points"] = [
                    point for point in detail["indicators"]["points"] if point["open_ms"] in times
                ]
            return {
                "scope": scope,
                "facts": facts,
                "offset": offset,
                "total": total,
                "next_cursor": self.cursor(dict(scope, kind="detail", offset=offset + 30))
                if offset + 30 < total
                else None,
            }

    def close(self) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE tool_runs SET status='interrupted',finished=?,"
                "error='Owned tool worker closed before answer persistence' "
                "WHERE status='running' AND owner=?",
                (time.time(), self.owner),
            )
        self.connection.close()
