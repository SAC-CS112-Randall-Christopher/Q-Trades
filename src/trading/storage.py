"""Bounded public observation storage. This is not a financial ledger."""

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


class MonitorStore:
    def __init__(self, path: Path, capacity: int = 2000, byte_budget: int = 16_000_000):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.capacity = capacity
        self.byte_budget = byte_budget
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL, symbol TEXT, observed_at TEXT NOT NULL,
                payload TEXT NOT NULL, config_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_at TEXT NOT NULL, message TEXT NOT NULL
            );
        """)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def get(self, key: str, default: Any = None) -> Any:
        with self.lock:
            row = self.db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key: str, value: Any) -> None:
        with self.lock, self.db:
            self._set(key, value)

    def _set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO state VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, separators=(",", ":"))),
        )

    def record(
        self,
        kind: str,
        symbol: str | None,
        observed_at: str,
        payload: dict[str, Any],
        config_hash: str,
        latest_key: str | None = None,
    ) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO observations(kind,symbol,observed_at,payload,config_hash) "
                "VALUES (?,?,?,?,?)",
                (
                    kind,
                    symbol,
                    observed_at,
                    json.dumps(payload, separators=(",", ":")),
                    config_hash,
                ),
            )
            self._set("observations_total", self.get("observations_total", 0) + 1)
            if latest_key:
                self._set(latest_key, {"observed_at": observed_at, "payload": payload})
            self.db.execute(
                "DELETE FROM observations WHERE id NOT IN "
                "(SELECT id FROM observations ORDER BY id DESC LIMIT ?)",
                (self.capacity,),
            )
            payload_bytes = self.db.execute(
                "SELECT COALESCE(SUM(LENGTH(payload)),0) FROM observations"
            ).fetchone()[0]
            while payload_bytes > self.byte_budget:
                oldest = self.db.execute(
                    "SELECT id, LENGTH(payload) FROM observations ORDER BY id LIMIT 1"
                ).fetchone()
                self.db.execute("DELETE FROM observations WHERE id=?", (oldest[0],))
                payload_bytes -= oldest[1]

    def event(self, observed_at: str, message: str, *, paused: bool | None = None) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO events(observed_at,message) VALUES (?,?)",
                (observed_at, message),
            )
            self._set("events_total", self.get("events_total", 0) + 1)
            if paused is not None:
                self._set("paused", paused)
            self.db.execute(
                "DELETE FROM events WHERE id NOT IN "
                "(SELECT id FROM events ORDER BY id DESC LIMIT 200)"
            )

    def events(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 20")
            ]

    def observation_stats(self) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute(
                "SELECT COUNT(*) AS retained, MIN(observed_at) AS oldest, "
                "MAX(observed_at) AS newest FROM observations"
            ).fetchone()
            total = self.get("observations_total", 0)
            return {
                **dict(row),
                "total": total,
                "evicted": total - row["retained"],
                "capacity": self.capacity,
                "payload_byte_budget": self.byte_budget,
            }

    def export(self) -> dict[str, Any]:
        with self.lock:
            observations = []
            for row in self.db.execute("SELECT * FROM observations ORDER BY id"):
                entry = dict(row)
                entry["payload"] = json.loads(entry["payload"])
                observations.append(entry)
            return {
                "schema_version": 1,
                "source": "binance_us_public_rest",
                "evidence_type": "observed_public_data_not_strategy_performance",
                "retention": self.observation_stats(),
                "configurations": {
                    fingerprint: self.get("config:" + fingerprint)
                    for fingerprint in {entry["config_hash"] for entry in observations}
                },
                "observations": observations,
                "events": [
                    dict(row) for row in self.db.execute("SELECT * FROM events ORDER BY id")
                ],
                "events_total": self.get("events_total", 0),
            }
