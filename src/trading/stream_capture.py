"""Bounded raw research observations, separate from the permanent financial journal."""

import json
import sqlite3
from pathlib import Path
from typing import Any


class StreamCapture:
    def __init__(self, path: Path, max_bytes: int = 64 * 1024 * 1024, max_rows: int = 20_000):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.max_bytes, self.max_rows = max_bytes, max_rows
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA max_page_count=32768")  # 128 MiB at default 4 KiB pages.
        self.connection.execute("PRAGMA journal_size_limit=8388608")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, received REAL NOT NULL,
                kind TEXT NOT NULL, body TEXT NOT NULL, bytes INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS counters (
                id INTEGER PRIMARY KEY CHECK(id=1), captured INTEGER NOT NULL,
                pruned INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO counters VALUES (1,0,0);
        """)
        self.connection.commit()

    def append(self, records: list[dict[str, Any]]) -> dict[str, int]:
        rows = []
        for record in records:
            body = json.dumps(record, separators=(",", ":"))
            rows.append((record["received_at"], record["kind"], body, len(body.encode())))
        with self.connection:
            self.connection.executemany(
                "INSERT INTO observations(received,kind,body,bytes) VALUES (?,?,?,?)", rows
            )
            self.connection.execute("UPDATE counters SET captured=captured+?", (len(rows),))
            count, size = self.connection.execute(
                "SELECT count(*),coalesce(sum(bytes),0) FROM observations"
            ).fetchone()
            if count > self.max_rows or size > self.max_bytes:
                cutoff = self.connection.execute(
                    "SELECT min(id) FROM (SELECT id,row_number() OVER (ORDER BY id DESC) n,"
                    "sum(bytes) OVER (ORDER BY id DESC) size FROM observations) "
                    "WHERE n <= ? AND size <= ?",
                    (self.max_rows, self.max_bytes),
                ).fetchone()[0]
                deleted = self.connection.execute(
                    "DELETE FROM observations WHERE ? IS NULL OR id < ?", (cutoff, cutoff)
                ).rowcount
                self.connection.execute("UPDATE counters SET pruned=pruned+?", (deleted,))
        captured, pruned = self.connection.execute(
            "SELECT captured,pruned FROM counters"
        ).fetchone()
        retained, size = self.connection.execute(
            "SELECT count(*),coalesce(sum(bytes),0) FROM observations"
        ).fetchone()
        physical = sum(
            p.stat().st_size
            for p in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm"))
            if p.exists()
        )
        return {
            "captured": captured,
            "pruned": pruned,
            "retained": retained,
            "bytes": size,
            "max_bytes": self.max_bytes,
            "max_rows": self.max_rows,
            "physical_bytes": physical,
        }

    def close(self) -> None:
        self.connection.close()
