"""Persistent advisory-tool receipts, isolated from money and bounded without pruning."""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Any

from trading.station import VERSION

MAX_RESULT_BYTES = 131072
MAX_RUNS = 5000


class ToolJournal:
    def __init__(self, path: Path):
        self.lock = Lock()
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=1)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA max_page_count=16384")
        self.connection.execute("PRAGMA journal_size_limit=8388608")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS tool_runs (
                id INTEGER PRIMARY KEY, started REAL NOT NULL, finished REAL,
                tool TEXT NOT NULL, symbol TEXT NOT NULL, version TEXT NOT NULL,
                actor TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                result_sha256 TEXT, error TEXT
            )
        """)
        with self.connection:
            self.connection.execute(
                "UPDATE tool_runs SET status='interrupted',finished=?,"
                "error='Service restarted before a completed receipt was saved' "
                "WHERE status='running'",
                (time.time(),),
            )

    def start(self, tool: str, symbol: str) -> int:
        with self.lock, self.connection:
            count = self.connection.execute("SELECT count(*) FROM tool_runs").fetchone()[0]
            if count >= MAX_RUNS:
                raise ValueError(
                    "Tool journal capacity reached; preserve/export receipts before extending it"
                )
            cursor = self.connection.execute(
                "INSERT INTO tool_runs(started,tool,symbol,version,actor,status) "
                "VALUES (?,?,?,?, 'local_operator','running')",
                (time.time(), tool, symbol, VERSION),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def finish(self, run_id: int, result: dict[str, Any] | None, error: str | None) -> None:
        body = json.dumps(result, sort_keys=True, separators=(",", ":")) if result else None
        if body and len(body.encode()) > MAX_RESULT_BYTES:
            body, error = None, "Result exceeded the registered evidence size limit"
        digest = hashlib.sha256(body.encode()).hexdigest() if body else None
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE tool_runs SET finished=?,status=?,result=?,result_sha256=?,error=? "
                "WHERE id=? AND status='running'",
                (time.time(), "failed" if error else "completed", body, digest, error, run_id),
            )

    def recent(self) -> dict[str, Any]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT id,started,finished,tool,symbol,status,error FROM tool_runs "
                "ORDER BY id DESC LIMIT 20"
            ).fetchall()
            total = self.connection.execute("SELECT count(*) FROM tool_runs").fetchone()[0]
        return {"runs": [dict(r) for r in rows], "total": total, "capacity": MAX_RUNS}

    def get(self, run_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM tool_runs WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def close(self) -> None:
        self.connection.close()
