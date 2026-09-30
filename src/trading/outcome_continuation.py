"""Bounded delayed labels in a new archive; acquisition and old archives are independent."""

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from trading.research_evidence import MAX_PACKET, canonical, digest

NAME = "mature-outcomes-v2.sqlite"
VERSION = "delayed-outcome-continuation-v2"


def continued_outcome(
    directory: Path, source: str, episode: str, sha: str, as_of: float
) -> dict[str, Any] | None:
    path = directory / NAME
    if not path.exists():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute(
            "SELECT body,sha FROM continued_outcomes WHERE source=? AND episode=? "
            "AND source_sha=? AND available<=?",
            (source, episode, sha, as_of),
        ).fetchone()
        if row is None:
            return None
        value: dict[str, Any] = json.loads(row[0])
        if digest(value) != row[1]:
            raise ValueError("Continued outcome checksum differs; no replacement inferred")
        return value


class OutcomeContinuation:
    def __init__(self, directory: Path, maximum_bytes: int = 64 * 1024**2):
        self.path = directory / NAME
        self.maximum_bytes = maximum_bytes
        self.db = sqlite3.connect(self.path, timeout=0.1, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA wal_autocheckpoint=32;
            CREATE TABLE IF NOT EXISTS continued_outcomes(
                source TEXT NOT NULL, episode TEXT NOT NULL, source_sha TEXT NOT NULL,
                available REAL NOT NULL, body TEXT NOT NULL, sha TEXT NOT NULL,
                PRIMARY KEY(source,episode,source_sha));
            CREATE INDEX IF NOT EXISTS continued_available ON continued_outcomes(source,available);
            CREATE TABLE IF NOT EXISTS continuation_work(
                source TEXT PRIMARY KEY, cursor INTEGER NOT NULL, next_due REAL NOT NULL);
            INSERT OR IGNORE INTO continuation_work VALUES('full',0,0);
            INSERT OR IGNORE INTO continuation_work VALUES('compact',0,0);
            CREATE TRIGGER IF NOT EXISTS continued_update BEFORE UPDATE ON continued_outcomes
                BEGIN SELECT RAISE(ABORT,'Original delayed receipts are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS continued_delete BEFORE DELETE ON continued_outcomes
                BEGIN SELECT RAISE(ABORT,'Delayed receipts are retained'); END;
        """)
        self.db.execute(f"PRAGMA max_page_count={maximum_bytes // 4096}")

    def process(
        self,
        full_path: Path,
        compact_path: Path,
        packets: list[dict[str, Any]],
        now: float,
        admission: Callable[[int], None],
    ) -> dict[str, Any]:
        from trading.compact_memory import journal_target
        from trading.pattern_memory import market_outcome

        processed = 0
        unavailable = 0
        for source, path in (("full", full_path), ("compact", compact_path)):
            work = self.db.execute(
                "SELECT * FROM continuation_work WHERE source=?", (source,)
            ).fetchone()
            if now < work["next_due"] or not path.exists():
                continue
            # One bounded queue advances durably; already emitted labels never gain
            # a new availability time on retry, restart or a later archive append.
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as old:
                old.row_factory = sqlite3.Row
                old.execute("PRAGMA query_only=ON")
                old.execute("BEGIN")
                if source == "full":
                    rows = old.execute(
                        "SELECT * FROM evidence_episodes WHERE record_id>? AND horizon_at<=? "
                        "ORDER BY record_id LIMIT 16",
                        (work["cursor"], now),
                    ).fetchall()
                else:
                    rows = old.execute(
                        "SELECT p.*,o.episode AS original_outcome FROM compact_prefixes p "
                        "LEFT JOIN compact_outcomes o ON o.episode=p.episode "
                        "WHERE p.seq>? AND p.cutoff+2700<=? ORDER BY p.seq LIMIT 16",
                        (work["cursor"], now),
                    ).fetchall()
                receipts = []
                for row in rows:
                    sha = row["descriptor_sha256"] if source == "full" else row["sha256"]
                    body = row["descriptor"] if source == "full" else row["body"]
                    if len(body.encode()) > MAX_PACKET or digest(json.loads(body)) != sha:
                        raise ValueError("Original delayed-label input checksum differs")
                    existing = row["outcome_id"] if source == "full" else row["original_outcome"]
                    if existing is not None:
                        continue
                    if self.db.execute(
                        "SELECT 1 FROM continued_outcomes WHERE source=? AND episode=? "
                        "AND source_sha=?",
                        (source, row["episode"], sha),
                    ).fetchone():
                        continue
                    if source == "full":
                        original = old.execute(
                            "SELECT payload,sha256 FROM evidence_records WHERE id=?",
                            (row["record_id"],),
                        ).fetchone()
                        if original is None or digest(json.loads(original[0])) != original[1]:
                            raise ValueError("Original full episode record missing or changed")
                        descriptor = json.loads(body)
                        if descriptor.get("status") != "available":
                            continue
                        bars = self._bars(old, packets, descriptor["horizon_at"], now)
                        target = market_outcome(
                            {"episode": row["episode"], "descriptor": descriptor}, bars, now, now
                        )
                    else:
                        original = (body, sha)
                        target = journal_target(old, row["cutoff"], now, now)
                    target.update(
                        continuation_version=VERSION,
                        original_reference={
                            "archive": source,
                            "episode": row["episode"],
                            "sha256": original[1],
                            "descriptor_sha256": sha,
                            "record_id": row["record_id"] if source == "full" else row["seq"],
                        },
                        maturity_observed_at=now,
                    )
                    receipts.append(
                        (source, row["episode"], sha, now, canonical(target), digest(target))
                    )
                    unavailable += target["status"] != "available"
                amount = sum(len(r[4].encode()) * 3 for r in receipts) + 65536
                admission(amount)
                physical = sum(
                    p.stat().st_size
                    for p in (self.path, Path(str(self.path) + "-wal"))
                    if p.exists()
                )
                if physical + amount > self.maximum_bytes:
                    raise OSError("Delayed outcome continuation quota; due outcomes remain pending")
                cursor = (
                    (rows[-1]["record_id"] if source == "full" else rows[-1]["seq"])
                    if rows
                    else work["cursor"]
                )
                with self.db:
                    self.db.executemany(
                        "INSERT OR IGNORE INTO continued_outcomes VALUES(?,?,?,?,?,?)", receipts
                    )
                    self.db.execute(
                        "UPDATE continuation_work SET cursor=?,next_due=? WHERE source=?",
                        (cursor, now if len(rows) == 16 else now + 30, source),
                    )
                processed += len(receipts)
        return {
            "version": VERSION,
            "state": "observed",
            "checked_at": now,
            "processed_this_pass": processed,
            "unavailable_this_pass": unavailable,
            "reason": "Bounded due-outcome check is independent of acquisition admission",
            "latest_available_at": self.db.execute(
                "SELECT max(available) FROM continued_outcomes"
            ).fetchone()[0],
            "next_check_at": self.db.execute(
                "SELECT min(next_due) FROM continuation_work WHERE next_due>0"
            ).fetchone()[0] or now + 30,
        }

    @staticmethod
    def _bars(
        old: sqlite3.Connection, packets: list[dict[str, Any]], horizon: float, now: float
    ) -> list[dict[str, Any]]:
        # At most two bounded dependency bundles. Never rerun history as fresh
        # evidence or replace its original per-candle availability timestamp.
        saved = old.execute(
            "SELECT payload,sha256 FROM evidence_records WHERE kind='decision' AND at>=? "
            "AND at<=? ORDER BY at,id LIMIT 1",
            (horizon, now),
        ).fetchone()
        inputs = []
        if saved:
            value = json.loads(saved[0])
            if len(saved[0].encode()) > MAX_PACKET or digest(value) != saved[1]:
                raise ValueError("Original candle dependency checksum differs")
            inputs.append(value)
        fresh = [p for p in packets if p.get("kind") == "decision" and p["at"] <= now]
        if fresh:
            inputs.append(fresh[-1])
        bars: dict[int, dict[str, Any]] = {}
        for packet in inputs:
            for bar in packet.get("bars", {}).get("BTCUSD", [])[-600:]:
                if bar.get("available_at", now + 1) <= now:
                    key = bar["open_ms"]
                    previous = bars.get(key)
                    if previous is not None and (
                        {k: v for k, v in previous.items() if k != "available_at"}
                        != {k: v for k, v in bar.items() if k != "available_at"}
                    ):
                        raise ValueError("Retained candle versions differ; no label inferred")
                    if previous is None or bar["available_at"] < previous["available_at"]:
                        bars[key] = bar
        return [bars[k] for k in sorted(bars)]

    def close(self) -> None:
        self.db.close()
