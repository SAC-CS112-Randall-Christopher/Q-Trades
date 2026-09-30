"""Append-only, capacity-stopping local evidence. Never financial authority."""

import hashlib
import json
import math
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from trading.market import parse_book

VERSION = "causal-evidence-v1"
MAX_PACKET = 2 * 1024 * 1024


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@lru_cache(maxsize=128)
def _small_descriptor(body: str, sha256: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(body)
    if digest(value) != sha256:
        raise ValueError("Episode descriptor corrupted; no replacement inferred")
    return value


def _descriptor(body: str, sha256: str) -> dict[str, Any]:
    # Both immutable text and hash form the key; a changed row cannot hit an old
    # cached validation. Cap keys at eight KiB and 128 entries (one MiB of text).
    if len(body) <= 8192:
        return _small_descriptor(body, sha256)
    value: dict[str, Any] = json.loads(body)
    if digest(value) != sha256:
        raise ValueError("Episode descriptor corrupted; no replacement inferred")
    return value


@dataclass(frozen=True)
class EvidencePlan:
    max_bytes: int = 64 * 1024 * 1024
    max_rows: int = 20_000
    period_seconds: int = 300
    window_seconds: int = 10
    summary_seconds: int = 60
    max_episodes: int = 512

    def __post_init__(self) -> None:
        if (
            any(type(v) is not int for v in asdict(self).values())
            or not 1024 * 1024 <= self.max_bytes <= 128 * 1024 * 1024
            or not 1 <= self.max_rows <= 50_000
            or not 1 <= self.window_seconds <= self.period_seconds <= 3600
            or not 1 <= self.summary_seconds <= 300
            or not 1 <= self.max_episodes <= 512
        ):
            raise ValueError("Invalid bounded evidence plan")

    def selected(self, at: float) -> bool:
        return math.isfinite(at) and at % self.period_seconds < self.window_seconds


class EvidenceArchive:
    def __init__(self, path: Path, plan: EvidencePlan | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, timeout=0.25, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA wal_autocheckpoint=128")
            self.connection.execute("PRAGMA journal_size_limit=1048576")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS evidence_meta (
                    id INTEGER PRIMARY KEY CHECK(id=1), version TEXT NOT NULL,
                    plan TEXT NOT NULL, rows INTEGER NOT NULL, bytes INTEGER NOT NULL,
                    dropped INTEGER NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_records (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_pins (
                    reference TEXT PRIMARY KEY, record_id INTEGER NOT NULL,
                    sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_episodes (
                    episode TEXT PRIMARY KEY, opportunity TEXT NOT NULL UNIQUE,
                    record_id INTEGER NOT NULL UNIQUE, available_at REAL NOT NULL,
                    cutoff REAL NOT NULL, horizon_at REAL NOT NULL, descriptor TEXT NOT NULL,
                    descriptor_sha256 TEXT NOT NULL, outcome_id INTEGER
                );
            """)
            meta = self.connection.execute("SELECT * FROM evidence_meta WHERE id=1").fetchone()
            if meta is None:
                if self.connection.execute("SELECT count(*) FROM evidence_records").fetchone()[0]:
                    raise ValueError("Incomplete archive metadata; existing inputs preserved")
                self.plan = plan or EvidencePlan()
                self.connection.execute(
                    "INSERT INTO evidence_meta VALUES (1,?,?,?,?,?,?)",
                    (VERSION, canonical(asdict(self.plan)), 0, 0, 0, "recording"),
                )
            else:
                if meta["version"] != VERSION:
                    raise ValueError("Unsupported evidence archive; preserved without migration")
                self.plan = EvidencePlan(**json.loads(meta["plan"]))
                if plan is not None and plan != self.plan:
                    raise ValueError("Frozen retention plan differs; existing archive preserved")
                count, size = self.connection.execute(
                    "SELECT count(*),coalesce(sum(bytes),0) FROM evidence_records"
                ).fetchone()
                if (count, size) != (meta["rows"], meta["bytes"]):
                    raise ValueError("Incomplete archive; optional acquisition stopped")
            if self.connection.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise ValueError("Corrupt evidence archive")
            # Reserve space for status/pins/indexes; physical/WAL admission also checked.
            self.connection.execute(f"PRAGMA max_page_count={self.plan.max_bytes // 4096}")
            self.connection.commit()
        except Exception:
            self.connection.close()
            raise

    def append(self, packets: list[dict[str, Any]], *, disk_available: bool = True) -> None:
        if len(packets) > 128:
            raise ValueError("Evidence batch exceeds the bounded writer")
        packets = [dict(packet) for packet in packets]
        with self.connection:
            meta = self.connection.execute("SELECT state FROM evidence_meta WHERE id=1").fetchone()
            if meta[0] == "capacity" or not disk_available:
                cause = "capacity" if meta[0] == "capacity" else "disk_pressure"
                self.connection.execute(
                    "UPDATE evidence_meta SET dropped=dropped+?,state=? WHERE id=1",
                    (len(packets), cause),
                )
                return
            if meta[0] == "disk_pressure":
                self.connection.execute("UPDATE evidence_meta SET state='recording' WHERE id=1")
            for packet in packets:
                if packet.get("schema") == VERSION and packet["kind"] == "decision":
                    self._describe(packet)
                record_id = self._store(packet, disk_available)
                if record_id is None:
                    continue
                episode = packet.get("episode")
                if isinstance(episode, dict) and episode.get("new"):
                    self.connection.execute(
                        "INSERT INTO evidence_episodes VALUES (?,?,?,?,?,?,?,?,NULL)",
                        (
                            episode["episode"],
                            episode["opportunity"],
                            record_id,
                            episode["available_at"],
                            packet["at"],
                            episode["descriptor"].get("horizon_at", packet["at"]),
                            canonical(episode["descriptor"]),
                            digest(episode["descriptor"]),
                        ),
                    )
                if packet["kind"] == "outcome":
                    self.connection.execute(
                        "UPDATE evidence_episodes SET outcome_id=? "
                        "WHERE episode=? AND outcome_id IS NULL",
                        (record_id, packet["episode"]),
                    )
            # Maturation is optional archive work after committed financial processing.
            # Each batch processes at most sixteen due episodes, without dropping the rest.
            if disk_available:
                decisions = [
                    p for p in packets if p.get("schema") == VERSION and p["kind"] == "decision"
                ]
                if decisions:
                    self._mature(decisions[-1])

    def _store(self, packet: dict[str, Any], disk_available: bool) -> int | None:
        body = canonical(packet)
        size = len(body.encode())
        at = packet["at"]
        if type(at) not in (float, int) or not math.isfinite(at):
            raise ValueError("Invalid local availability timestamp")
        meta = self.connection.execute("SELECT * FROM evidence_meta WHERE id=1").fetchone()
        assert meta is not None
        cause = None
        if meta["state"] == "capacity":
            cause = "capacity"  # Full remains latched through disk-pressure changes/restarts.
        elif not disk_available:
            cause = "disk_pressure"
        elif size > MAX_PACKET:
            cause = "packet_capacity"
        elif (
            meta["rows"] >= self.plan.max_rows
            or meta["bytes"] + size > self.plan.max_bytes - 131072
            or self.physical_bytes() + size * 2 > self.plan.max_bytes - 65536
        ):
            cause = "capacity"
        if cause:
            self.connection.execute(
                "UPDATE evidence_meta SET dropped=dropped+1,state=? WHERE id=1", (cause,)
            )
            return None
        row = self.connection.execute(
            "INSERT INTO evidence_records(at,kind,payload,sha256,bytes) "
            "VALUES (?,?,?,?,?) RETURNING id",
            (at, packet["kind"], body, hashlib.sha256(body.encode()).hexdigest(), size),
        ).fetchone()
        self.connection.execute(
            "UPDATE evidence_meta SET rows=rows+1,bytes=bytes+?,state='recording' WHERE id=1",
            (size,),
        )
        return int(row[0])

    def _library(self, cutoff: float) -> list[dict[str, Any]]:
        result = []
        for row in self.connection.execute(
            "SELECT * FROM evidence_episodes WHERE available_at<=? AND cutoff<=? ORDER BY episode",
            (cutoff, cutoff),
        ):
            d = _descriptor(row["descriptor"], row["descriptor_sha256"])
            outcome = None
            if row["outcome_id"] is not None:
                saved = self.connection.execute(
                    "SELECT * FROM evidence_records WHERE id=? AND at<=?",
                    (row["outcome_id"], cutoff),
                ).fetchone()
                if saved is not None:
                    outcome = _checked_record(saved)["payload"]
            result.append(
                {
                    "episode": row["episode"],
                    "record_id": row["record_id"],
                    "available_at": row["available_at"],
                    "descriptor": d,
                    "descriptor_sha256": row["descriptor_sha256"],
                    "outcome": outcome,
                }
            )
        return result

    def _describe(self, packet: dict[str, Any]) -> None:
        from trading.pattern_memory import descriptor, lookup

        packet.pop("episode", None)
        packet.pop("episode_reference", None)
        packet.pop("memory_status", None)
        if "BTCUSD" not in packet.get("frames", {}):
            packet["memory_status"] = "BTCUSD inputs unavailable; no episode inferred"
            return
        rows = packet["bars"].get("BTCUSD", [])
        origin = packet["feature_origin"].get("BTCUSD", {})
        opportunity = f"BTCUSD:{rows[-1]['open_ms'] if rows else -1}:{origin.get('computed_at')}"
        existing = self.connection.execute(
            "SELECT episode,record_id FROM evidence_episodes WHERE opportunity=?", (opportunity,)
        ).fetchone()
        if existing:
            packet["episode_reference"] = dict(existing)
            packet["memory_status"] = "Same as-seen opportunity; original receipt retained"
            return
        if (
            self.connection.execute("SELECT count(*) FROM evidence_episodes").fetchone()[0]
            >= self.plan.max_episodes
        ):
            packet["memory_status"] = "Episode capacity; existing memory preserved, no eviction"
            return
        context = {
            "book": packet["book_features"].get("BTCUSD"),
            "closed_bar": packet["study"].get("BTCUSD", {}).get("breakout-v1"),
            "observed_order_flow": "unavailable",
        }
        mode = (
            "synthetic"
            if "synthetic" in packet["frames"]["BTCUSD"].get("source", "")
            else "forward-paper"
        )
        d = descriptor(rows, packet["at"], context, mode)
        wall = time.time()
        episode: dict[str, Any] = {
            "episode": digest({"opportunity": opportunity, "descriptor": d}),
            "new": True,
            "opportunity": opportunity,
            "available_at": wall,
            "descriptor": d,
            "action": "Shadow only; did not change baseline decision",
        }
        started = time.perf_counter()
        episode["retrieval"] = lookup(d, self._library(packet["at"]), wall)
        episode["retrieval_ms"] = (time.perf_counter() - started) * 1000
        completed = time.time()
        episode["retrieval"].update(completed_at=completed, earliest_action_at=completed)
        if d.get("expires_at") is not None and completed > d["expires_at"]:
            episode["retrieval"]["status"] = "result_too_late"
        packet["episode"] = episode

    def _mature(self, packet: dict[str, Any]) -> None:
        from trading.pattern_memory import market_outcome

        rows = packet["bars"].get("BTCUSD", [])
        due = self.connection.execute(
            "SELECT * FROM evidence_episodes WHERE horizon_at<=? AND outcome_id IS NULL "
            "AND json_extract(descriptor,'$.status')='available' ORDER BY horizon_at LIMIT 16",
            (packet["at"],),
        ).fetchall()
        for row in due:
            d = json.loads(row["descriptor"])
            if d["status"] != "available":
                continue
            wall = time.time()
            if wall < d["horizon_at"]:
                continue
            outcome = market_outcome(
                {"episode": row["episode"], "descriptor": d}, rows, packet["at"], wall
            )
            record_id = self._store(outcome, True)
            if record_id is not None:
                self.connection.execute(
                    "UPDATE evidence_episodes SET outcome_id=? "
                    "WHERE episode=? AND outcome_id IS NULL",
                    (record_id, row["episode"]),
                )

    def pin(self, reference: str, record_id: int, sha256: str) -> None:
        if not reference or len(reference) > 128:
            raise ValueError("Invalid retained-input reference")
        row = self.connection.execute(
            "SELECT sha256 FROM evidence_records WHERE id=?", (record_id,)
        ).fetchone()
        if row is None or row[0] != sha256:
            raise ValueError("Retained input is missing or changed")
        with self.connection:
            existing = self.connection.execute(
                "SELECT record_id,sha256 FROM evidence_pins WHERE reference=?", (reference,)
            ).fetchone()
            if existing and tuple(existing) != (record_id, sha256):
                raise ValueError("A frozen reference cannot be redirected")
            if (
                not existing
                and self.connection.execute("SELECT count(*) FROM evidence_pins").fetchone()[0]
                >= 512
            ):
                raise ValueError("Retained-reference capacity reached")
            self.connection.execute(
                "INSERT OR IGNORE INTO evidence_pins VALUES (?,?,?)", (reference, record_id, sha256)
            )

    def physical_bytes(self) -> int:
        return sum(
            p.stat().st_size
            for p in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm"))
            if p.exists()
        )

    def snapshot(self) -> dict[str, Any]:
        meta = dict(self.connection.execute("SELECT * FROM evidence_meta WHERE id=1").fetchone())
        meta["plan"] = json.loads(meta["plan"])
        return {
            **meta,
            "physical_bytes": self.physical_bytes(),
            "retention": "No eviction; capacity stops optional acquisition",
            "financial_authority": False,
            "redistribution": "Local internal use only",
            "episodes": self.connection.execute(
                "SELECT count(*) FROM evidence_episodes"
            ).fetchone()[0],
            "outcomes": self.connection.execute(
                "SELECT count(*) FROM evidence_episodes WHERE outcome_id IS NOT NULL"
            ).fetchone()[0],
        }

    def close(self) -> None:
        self.connection.close()


def evidence_page(
    path: Path, before: int = 0, limit: int = 20, kind: str = "decision"
) -> dict[str, Any]:
    if type(before) is not int or before < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Invalid evidence page")
    if not path.is_file():
        return {"records": [], "has_more": False, "status": "not_captured"}
    if kind not in {"decision", "summary", "wire", "outcome", "all"}:
        raise ValueError("Unknown evidence selection")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id,at,kind,sha256,bytes FROM evidence_records "
            "WHERE (?=0 OR id<?) AND (?='all' OR kind=?) ORDER BY id DESC LIMIT ?",
            (before, before, kind, kind, limit + 1),
        ).fetchall()
        return {
            "records": [dict(r) for r in rows[:limit]],
            "has_more": len(rows) > limit,
            "next_before": rows[limit - 1]["id"] if len(rows) > limit else None,
        }


def evidence_record(path: Path, record_id: int) -> dict[str, Any]:
    if type(record_id) is not int or not 1 <= record_id <= 2**63 - 1:
        raise ValueError("Invalid evidence reference")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM evidence_records WHERE id=?", (record_id,)
        ).fetchone()
        if row is None:
            raise LookupError("Evidence is unavailable; no input was substituted")
        record = _checked_record(row)
        reference = record["payload"].get("episode_reference", {}).get("episode")
        own = record["payload"].get("episode")
        if isinstance(own, dict):
            reference = own["episode"]
        elif isinstance(own, str) and record["payload"].get("kind") == "outcome":
            reference = own
        if reference:
            episode = connection.execute(
                "SELECT record_id,outcome_id FROM evidence_episodes WHERE episode=?", (reference,)
            ).fetchone()
            if episode is None:
                raise ValueError("Required episode reference missing")
            if episode["record_id"] != record_id:
                first = connection.execute(
                    "SELECT * FROM evidence_records WHERE id=?", (episode["record_id"],)
                ).fetchone()
                if first is None:
                    raise ValueError("Required as-seen prefix missing")
                record["original_episode"] = _checked_record(first)["payload"]["episode"]
            if episode["outcome_id"] is not None:
                outcome = connection.execute(
                    "SELECT * FROM evidence_records WHERE id=?", (episode["outcome_id"],)
                ).fetchone()
                if outcome is None:
                    raise ValueError("Required outcome reference missing")
                record["subsequent_outcome"] = _checked_record(outcome)
            else:
                record["subsequent_outcome"] = {"status": "outcome_pending"}
        return record


def _checked_record(row: sqlite3.Row) -> dict[str, Any]:
    body = row["payload"]
    if (
        len(body.encode()) > MAX_PACKET
        or hashlib.sha256(body.encode()).hexdigest() != row["sha256"]
    ):
        raise ValueError("Recorded evidence is corrupt; no replay was inferred")
    return {"id": row["id"], "sha256": row["sha256"], "payload": json.loads(body)}


def book_features(frame: dict[str, Any], at: float) -> dict[str, Any]:
    """Same causal snapshot function for recorded research and later challengers."""
    if frame["observed"] > at or at - frame["observed"] > 3:
        return {"version": VERSION, "status": "unavailable", "reason": "Future or stale receipt"}
    book = parse_book(frame["raw"], 1000)
    bid, ask = book.bids[0][0], book.asks[0][0]
    bid_size = sum((q for _, q in book.bids), Decimal(0))
    ask_size = sum((q for _, q in book.asks), Decimal(0))
    return {
        "version": VERSION,
        "status": "available",
        "sequence": book.update_id,
        "spread_bps": str((ask - bid) / ((ask + bid) / 2) * 10000),
        "visible_depth_imbalance": str((bid_size - ask_size) / (bid_size + ask_size)),
        "coverage": "Recorded visible depth only; no hidden liquidity or queue position",
    }
