"""Small first-seen prefixes and committed journal links; no execution authority."""

import json
import sqlite3
import time
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.pattern_memory import descriptor
from trading.research_evidence import canonical, digest

CONTRACT = {
    "version": "journal-linked-memory-v1",
    "selection": "First valid prefix per 3300-second UTC group and actual buy intents",
    "snapshot": "Latest 512 chronological retained prefixes at the declared cutoff",
    "capacity": "64 MiB, 8192 prefixes, 20000 linked events; stop without eviction",
    "labels": "First dispatched linked modeled buy and closed trade, then observed 45m maturity",
    "authority": "Read-only research; full PostgreSQL journal remains authoritative",
}


def prefix(
    at: float, bars: list[dict[str, Any]], context: dict[str, Any], mode: str
) -> dict[str, Any]:
    return descriptor(bars, at, context, mode)


def linked_events(
    events: list[dict[str, Any]], receipt: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if not receipt:
        return []
    refs = {r["event_index"]: r for r in receipt["events"]}
    result = []
    fields = (
        "symbol",
        "side",
        "version",
        "created_at",
        "opened_at",
        "closed_at",
        "pnl",
        "cost",
        "proceeds",
        "fees",
    )
    for i, event in enumerate(events):
        if event["kind"] not in {"order_intent", "fill", "trade_closed"}:
            continue
        if event["body"].get("symbol") != "BTCUSD" or i not in refs:
            continue
        result.append(
            {
                "reference": refs[i],
                "at": event["at"],
                "kind": event["kind"],
                "account": event["account"],
                "body": {k: event["body"][k] for k in fields if k in event["body"]},
                "original_event_sha256": digest(event),
                "committed_at": receipt["committed_at"],
            }
        )
    return result


class CompactMemory:
    def __init__(self, path: Path, *, storage_bytes: int | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=0.25, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA wal_autocheckpoint=64;
            PRAGMA max_page_count=16384;
            CREATE TABLE IF NOT EXISTS compact_prefixes(
                seq INTEGER PRIMARY KEY, episode TEXT UNIQUE NOT NULL, cutoff REAL NOT NULL,
                available REAL NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS compact_events(
                event_id INTEGER PRIMARY KEY, available REAL NOT NULL,
                body TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS compact_outcomes(
                episode TEXT PRIMARY KEY, available REAL NOT NULL,
                body TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS compact_meta(id INTEGER PRIMARY KEY, state TEXT NOT NULL);
            INSERT OR IGNORE INTO compact_meta VALUES(1,'recording');
            CREATE INDEX IF NOT EXISTS compact_time ON compact_prefixes(cutoff,available);
            CREATE INDEX IF NOT EXISTS compact_event_time ON compact_events(
                json_extract(body,'$.at'));
        """)
        for table in ("compact_prefixes", "compact_events", "compact_outcomes"):
            self.db.executescript(f"""
                CREATE TRIGGER IF NOT EXISTS {table}_update BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT,'Memory evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS {table}_delete BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT,'Memory history is retained'); END;
            """)
        self.storage_bytes = storage_bytes
        self.state_table = "compact_meta"
        if storage_bytes is not None:
            if not 256 * 1024 <= storage_bytes <= 100_000_000_000:
                raise ValueError("Invalid versioned retained research capacity")
            self.db.executescript(
                "CREATE TABLE IF NOT EXISTS compact_v2_plan("
                "id INTEGER PRIMARY KEY,bytes INTEGER NOT NULL);"
                " CREATE TABLE IF NOT EXISTS compact_v2_state("
                "id INTEGER PRIMARY KEY,state TEXT NOT NULL);"
                " INSERT OR IGNORE INTO compact_v2_state VALUES(1,'recording');"
            )
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO compact_v2_plan VALUES(1,?)", (storage_bytes,)
                )
            if self.db.execute("SELECT bytes FROM compact_v2_plan").fetchone()[0] != storage_bytes:
                raise ValueError("Versioned compact capacity differs from its saved plan")
            self.db.execute(f"PRAGMA max_page_count={storage_bytes // 4096}")
            self.state_table = "compact_v2_state"

    def append(self, packet: dict[str, Any], *, disk_available: bool = True) -> None:
        with self.db:
            state = self.db.execute(f"SELECT state FROM {self.state_table}").fetchone()[0]
            if state == "capacity":
                return
            if not disk_available:
                self.db.execute(f"UPDATE {self.state_table} SET state='disk_pressure'")
                return
            size = sum(
                p.stat().st_size for p in (self.path, Path(str(self.path) + "-wal")) if p.exists()
            )
            if self.storage_bytes is None and (
                size > 60 * 1024**2
                or self.db.execute("SELECT count(*) FROM compact_prefixes").fetchone()[0] >= 8192
                or self.db.execute("SELECT count(*) FROM compact_events").fetchone()[0]
                + len(packet["events"])
                > 20000
            ):
                self.db.execute(f"UPDATE {self.state_table} SET state='capacity'")
                return
            if self.storage_bytes is not None and size + 262144 > self.storage_bytes:
                self.db.execute(f"UPDATE {self.state_table} SET state='capacity'")
                return
            self.db.execute(
                f"UPDATE {self.state_table} SET state='recording' WHERE state!='recording'"
            )
            available = max(
                packet["collected_at"],
                time.time(),
                max(
                    (e.get("committed_at", packet["collected_at"]) for e in packet["events"]),
                    default=packet["collected_at"],
                ),
            )
            for event in packet["events"]:
                body, sha = canonical(event), digest(event)
                event_id = event["reference"]["event_id"]
                old = self.db.execute(
                    "SELECT sha256 FROM compact_events WHERE event_id=?", (event_id,)
                ).fetchone()
                if old and old[0] != sha:
                    raise ValueError("Journal reference changed")
                if old is None:
                    self.db.execute(
                        "INSERT INTO compact_events VALUES(?,?,?,?)",
                        (event_id, available, body, sha),
                    )
            d = packet.get("prefix")
            if d and d.get("status") == "available":
                group = int(d["cutoff"] // 3300)
                existing = self.db.execute(
                    "SELECT 1 FROM compact_prefixes WHERE cutoff>=? AND cutoff<? LIMIT 1",
                    (group * 3300, (group + 1) * 3300),
                ).fetchone()
                buy = any(
                    e["kind"] == "order_intent"
                    and e["body"].get("side") == "buy"
                    and e["body"].get("version") == "breakout-v1"
                    for e in packet["events"]
                )
                if not existing or buy:
                    episode = digest(d)
                    self.db.execute(
                        "INSERT OR IGNORE INTO compact_prefixes VALUES(NULL,?,?,?,?,?)",
                        (episode, d["cutoff"], available, canonical(d), episode),
                    )
            if packet["fresh"]:
                self._mature(packet["at"], available)

    def _mature(self, at: float, available: float) -> None:
        # A declared continuation owns subsequent first-seen labels.
        if (self.path.parent / "mature-outcomes-v2.sqlite").exists():
            return
        due = self.db.execute(
            "SELECT p.* FROM compact_prefixes p LEFT JOIN compact_outcomes o "
            "ON o.episode=p.episode WHERE o.episode IS NULL AND p.cutoff+2700<=? "
            "ORDER BY p.cutoff LIMIT 16",
            (min(at, available),),
        ).fetchall()
        for row in due:
            if digest(json.loads(row["body"])) != row["sha256"]:
                raise ValueError("Prefix changed")
            target = journal_target(self.db, row["cutoff"], at, available)
            self.db.execute(
                "INSERT INTO compact_outcomes VALUES(?,?,?,?)",
                (row["episode"], available, canonical(target), digest(target)),
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            "contract": CONTRACT
            if self.storage_bytes is None
            else {
                **CONTRACT,
                "capacity": (
                    "Versioned shared research-tier physical quota; no lifetime prefix/event cap"
                ),
                "storage_version": "research-tiers-v2",
            },
            "state": self.db.execute(f"SELECT state FROM {self.state_table}").fetchone()[0],
            "prefixes": self.db.execute("SELECT count(*) FROM compact_prefixes").fetchone()[0],
            "financial_authority": False,
        }

    def close(self) -> None:
        self.db.close()


def journal_target(
    db: sqlite3.Connection, cutoff: float, at: float, available: float
) -> dict[str, Any]:
    target: dict[str, Any] = {
        "status": "unavailable",
        "version": "executed-trade-net-v1",
        "collection_version": CONTRACT["version"],
        "reason": "No linked modeled closed trade by original horizon",
        "available_at": available,
        "net_bps": None,
    }
    rows = db.execute(
        "SELECT * FROM compact_events WHERE available<=? "
        "AND json_extract(body,'$.at')>=? AND json_extract(body,'$.at')<=? "
        "ORDER BY event_id LIMIT 4097",
        (available, cutoff, cutoff + 2700),
    ).fetchall()
    if len(rows) > 4096:
        return dict(target, reason="Linked journal dependencies exceed the bounded outcome pass")
    chosen, opened, entry = None, None, None
    for row in rows:
        e = json.loads(row["body"])
        if digest(e) != row["sha256"]:
            raise ValueError("Linked event changed")
        b = e["body"]
        if (
            e["kind"] == "order_intent"
            and b.get("side") == "buy"
            and b.get("version") == "breakout-v1"
            and b.get("created_at") == cutoff
            and chosen is None
        ):
            chosen = e["account"]
        if (
            chosen == e["account"]
            and e["kind"] == "fill"
            and b.get("side") == "buy"
            and b.get("created_at") == cutoff
        ):
            opened, entry = e["at"], e
        if (
            chosen == e["account"]
            and e["kind"] == "trade_closed"
            and opened is not None
            and b["opened_at"] == opened
            and b["closed_at"] <= min(at, cutoff + 2700)
        ):
            cost, proceeds, pnl = (Decimal(b[k]) for k in ("cost", "proceeds", "pnl"))
            if not all(x.is_finite() for x in (cost, proceeds, pnl)) or cost <= 0:
                return dict(target, reason="Invalid executable target")
            if proceeds - cost != pnl:
                return dict(target, reason="Net journal target does not reconcile")
            return dict(
                target,
                status="available",
                reason="Linked original journal trade",
                net_bps=float(pnl / cost * 10000),
                entry=entry,
                exit=e,
                fees_embedded_once=True,
                horizon_seconds=2700,
                maturity_observed_at=at,
                coverage="Modeled paper fills only",
            )
    return target


def compact_snapshot(path: Path, as_of: float) -> dict[str, Any]:
    from trading.outcome_continuation import continued_outcome

    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM compact_prefixes WHERE cutoff<=? AND available<=? "
            "ORDER BY cutoff DESC,seq DESC LIMIT 513",
            (as_of, as_of),
        ).fetchall()
        result = []
        for row in reversed(rows[:512]):
            d = json.loads(row["body"])
            if digest(d) != row["sha256"]:
                raise ValueError("Compact prefix changed")
            out = db.execute(
                "SELECT * FROM compact_outcomes WHERE episode=? AND available<=?",
                (row["episode"], as_of),
            ).fetchone()
            label = (
                json.loads(out["body"])
                if out
                else (
                    continued_outcome(path.parent, "compact", row["episode"], row["sha256"], as_of)
                    or {"status": "pending"}
                )
            )
            if out and digest(label) != out["sha256"]:
                raise ValueError("Compact outcome changed")
            result.append(
                {
                    "episode": row["episode"],
                    "record_id": row["seq"],
                    "evidence_reference": {
                        "archive": "compact",
                        "episode": row["episode"],
                        "record_id": row["seq"],
                        "sha256": row["sha256"],
                    },
                    "available_at": row["available"],
                    "descriptor": d,
                    "executable_label": label,
                }
            )
        return {
            "rows": result,
            "contract": CONTRACT,
            "records": [],
            "manifest": {
                "rows": len(result),
                "source_decisions": 0,
                "execution_status": "Compact journal-linked targets; continuous replay unavailable",
                "selection": CONTRACT["snapshot"],
                "older_rows_omitted": len(rows) > 512,
            },
        }


def compact_evidence(path: Path, episode: str, expected_sha256: str) -> dict[str, Any]:
    from trading.outcome_continuation import continued_outcome

    if not path.is_file():
        raise LookupError("Compact evidence archive is unavailable")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        row = db.execute("SELECT * FROM compact_prefixes WHERE episode=?", (episode,)).fetchone()
        if row is None:
            raise LookupError("Requested compact episode is not retained")
        d = json.loads(row["body"])
        if (
            row["sha256"] != expected_sha256
            or digest(d) != expected_sha256
            or row["episode"] != episode
        ):
            raise ValueError("Requested compact episode fingerprint differs")
        out = db.execute("SELECT * FROM compact_outcomes WHERE episode=?", (episode,)).fetchone()
        outcome = None
        if out:
            outcome = json.loads(out["body"])
            if digest(outcome) != out["sha256"]:
                raise ValueError("Requested compact outcome fingerprint differs")
        else:
            outcome = continued_outcome(
                path.parent, "compact", episode, expected_sha256, time.time()
            )
        return {
            "archive": "compact",
            "episode": episode,
            "record_id": row["seq"],
            "sha256": expected_sha256,
            "available_at": row["available"],
            "descriptor": d,
            "outcome": outcome,
            "outcome_sha256": digest(outcome) if outcome else None,
            "outcome_available_at": outcome["available_at"] if outcome else None,
            "financial_authority": False,
        }
