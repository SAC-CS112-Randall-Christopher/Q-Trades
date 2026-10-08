"""Versioned owned research tiers. No financial authority and no local spill fallback."""

import ctypes
import gzip
import hashlib
import json
import math
import os
import shutil
import sqlite3
import stat
import time
from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading.ownership import CollectorLock
from trading.research_evidence import MAX_PACKET, canonical, digest

GB = 1_000_000_000
DEFAULT_ROOT = r"G:\Projects\Q-Trades-Data"


def volume(path: Path) -> dict[str, Any]:
    """Read actual mapping identity; refuse active WAL on a network filesystem."""
    if not path.is_absolute():
        raise ValueError("Research root must be absolute")
    anchor = Path(path.anchor)
    if not anchor.exists():
        raise OSError("Configured research volume is absent")
    if os.name == "nt":
        kernel = ctypes.windll.kernel32
        serial, maximum, flags = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
        filesystem = ctypes.create_unicode_buffer(64)
        label = ctypes.create_unicode_buffer(256)
        if not kernel.GetVolumeInformationW(
            str(anchor),
            label,
            256,
            ctypes.byref(serial),
            ctypes.byref(maximum),
            ctypes.byref(flags),
            filesystem,
            64,
        ):
            raise OSError("Configured research volume identity is unavailable")
        kind = kernel.GetDriveTypeW(str(anchor))
        if kind not in (2, 3) or filesystem.value != "NTFS":
            raise ValueError("Active research WAL requires a verified local NTFS disk")
        identity = f"ntfs:{path.anchor.casefold()}:{serial.value:08x}"
    else:
        identity = f"local-test:{anchor.stat().st_dev}"
    usage = shutil.disk_usage(anchor)
    return {"identity": identity, "free_bytes": usage.free, "total_bytes": usage.total}


class StoragePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["research-tiers-v2"] = "research-tiers-v2"
    root: str = DEFAULT_ROOT
    volume_identity: str = Field(min_length=8, max_length=150)
    temporary_bytes: int = Field(default=100 * GB, ge=256 * 1024, le=400 * GB)
    research_bytes: int = Field(default=100 * GB, ge=256 * 1024, le=100 * GB)
    free_reserve_bytes: int = Field(default=5 * 1024**3, ge=0, le=100 * GB)
    scratch_bytes: int = Field(default=128 * 1024**2, ge=128 * 1024, le=512 * 1024**2)
    segment_bytes: int = Field(default=16 * 1024**2, ge=16 * 1024, le=32 * 1024**2)
    housekeeping_seconds: Literal[7200] = 7200
    temporary_retention_seconds: int = Field(default=7 * 86400, ge=7200, le=30 * 86400)

    @model_validator(mode="after")
    def owned(self) -> Self:
        p = Path(self.root)
        if not p.is_absolute() or not p.name.startswith("Q-Trades-Data"):
            raise ValueError("Use an absolute dedicated Q-Trades-Data subtree")
        if self.segment_bytes * 2 > self.scratch_bytes:
            raise ValueError("Scratch must accommodate a complete segment and verified transfer")
        if self.scratch_bytes > self.temporary_bytes or self.scratch_bytes > self.research_bytes:
            raise ValueError("Each tier must accommodate its declared scratch reserve")
        return self


def load_plan(directory: Path) -> StoragePlan | None:
    path = directory / "research-storage.json"
    return StoragePlan.model_validate_json(path.read_text()) if path.exists() else None


def compact_path(directory: Path) -> Path:
    plan = load_plan(directory)
    return (
        Path(plan.root) / "research" / "memory-episodes.sqlite"
        if plan
        else directory / "memory-episodes.sqlite"
    )


def save_plan(directory: Path, plan: StoragePlan) -> None:
    if volume(Path(plan.root))["identity"] != plan.volume_identity:
        raise ValueError("Research mapping differs from the declared volume identity")
    path = directory / "research-storage.json"
    if path.exists():
        if load_plan(directory) != plan:
            raise ValueError("Existing storage policy is frozen; declare a reviewed successor")
        return
    directory.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        out.write(plan.model_dump_json(indent=2))
        out.flush()
        os.fsync(out.fileno())


def _bytes(directory: Path) -> int:
    # Only owned files, including index/WAL/SHM, transfer scratch and unexpected files.
    recounted = False
    while True:
        total = 0
        for path in directory.iterdir():
            try:
                observed = path.stat()
            except FileNotFoundError as exc:
                if not path.name.endswith((".sqlite-wal", ".sqlite-shm")):
                    raise
                if recounted:
                    raise OSError(
                        "SQLite files changed during storage recount; admission refused"
                    ) from exc
                # Last-connection close/checkpoint can remove a sidecar and grow a
                # main database already counted. Recount everything once, never
                # admit using the partial tally or retry continued churn.
                recounted = True
                break
            if stat.S_ISREG(observed.st_mode):
                total += observed.st_size
        else:
            return total


class ResearchStorage:
    def __init__(self, plan: StoragePlan):
        self.plan = plan
        self.root = Path(plan.root)
        self._write_lock = RLock()
        self._write_depth = 0
        self.recovery = {"segments_checked": 0, "rollbacks": 0}
        try:
            with self._exclusive():
                self._initialize()
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            raise

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """All application segment writers share this short, crash-released lock."""
        with self._write_lock:
            if self._write_depth:
                yield
                return
            self._check_volume()
            for path in (self.root, *self.root.parents):
                self._not_redirected(path)
            if (
                self.root.exists()
                and not (self.root / "owned.json").exists()
                and (
                    hasattr(self, "db")
                    or any(p.name != ".capture-owner.lock" for p in self.root.iterdir())
                )
            ):
                raise ValueError("Existing target is not a declared Q-Trades storage root")
            self.root.mkdir(parents=True, exist_ok=True)
            lock_path = self.root / ".capture-owner.lock"
            self._not_redirected(lock_path)
            owner = CollectorLock(lock_path)
            try:
                owner.acquire()
            except RuntimeError as exc:
                raise OSError(
                    "Capture recovery busy: another storage writer owns this root"
                ) from exc
            try:
                marker = self.root / "owned.json"
                self._not_redirected(marker)
                if marker.exists() and json.loads(marker.read_text()) != {
                    "plan_sha256": digest(self.plan.model_dump()),
                    "version": self.plan.version,
                }:
                    raise ValueError("Owned storage marker differs; no replacement inferred")
                self._write_depth = 1
                yield
            finally:
                self._write_depth = 0
                owner.release()

    @staticmethod
    def _not_redirected(path: Path) -> None:
        if path.is_symlink() or (
            path.exists() and os.name == "nt" and path.stat().st_file_attributes & 0x400
        ):
            raise OSError("Capture recovery foreign: redirected owned path")

    def _initialize(self) -> None:
        plan = self.plan
        self._check_volume()
        # Refuse redirected subtree components and an unowned preexisting directory.
        for p in (self.root, *self.root.parents):
            redirected = (
                p.is_symlink() or (os.name == "nt" and bool(p.stat().st_file_attributes & 0x400))
                if p.exists()
                else False
            )
            if redirected:
                raise ValueError("Research root cannot traverse a redirected/reparse directory")
        if (
            self.root.exists()
            and any(p.name != ".capture-owner.lock" for p in self.root.iterdir())
            and not (self.root / "owned.json").exists()
        ):
            raise ValueError("Existing target is not a declared Q-Trades storage root")
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / "owned.json"
        frozen = {"plan_sha256": digest(plan.model_dump()), "version": plan.version}
        if marker.exists():
            if json.loads(marker.read_text()) != frozen:
                raise ValueError("Owned storage marker differs; no replacement inferred")
        else:
            with marker.open("x", encoding="utf-8") as out:
                out.write(canonical(frozen))
                out.flush()
                os.fsync(out.fileno())
        self.temporary, self.research = self.root / "temporary", self.root / "research"
        self.temporary.mkdir(exist_ok=True)
        self.research.mkdir(exist_ok=True)
        for suffix in ("", "-wal", "-shm", "-journal"):
            self._not_redirected(self.research / ("storage-index.sqlite" + suffix))
        self.db = sqlite3.connect(
            self.research / "storage-index.sqlite", timeout=0.1, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA wal_autocheckpoint=64;
            CREATE TABLE IF NOT EXISTS storage_state(id INTEGER PRIMARY KEY,
                next_due REAL NOT NULL,
                last_success REAL, reason TEXT, read_bytes INTEGER NOT NULL DEFAULT 0,
                written_bytes INTEGER NOT NULL DEFAULT 0,
                reclaimed_bytes INTEGER NOT NULL DEFAULT 0,
                rows INTEGER NOT NULL DEFAULT 0, last_capture REAL, started REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS storage_segments(id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                rows INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0,
                first_at REAL, last_at REAL, sealed_at REAL, retained_sha TEXT,
                retained_bytes INTEGER,
                expires REAL, pin_until REAL NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS storage_segment_work ON storage_segments(state,id);
            CREATE TABLE IF NOT EXISTS storage_records(sha TEXT PRIMARY KEY,
                segment INTEGER NOT NULL,
                record INTEGER NOT NULL,at REAL NOT NULL,kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS storage_pins(reference TEXT PRIMARY KEY,
                segment INTEGER NOT NULL,
                until_at REAL NOT NULL, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS storage_legacy(path TEXT PRIMARY KEY, rows INTEGER NOT NULL,
                plan TEXT NOT NULL, verified_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS storage_rollups(bucket INTEGER NOT NULL,
                seconds INTEGER NOT NULL,
                symbol TEXT NOT NULL, samples INTEGER NOT NULL,
                minimum REAL NOT NULL, maximum REAL NOT NULL,
                last REAL NOT NULL, available REAL NOT NULL, gaps INTEGER NOT NULL,
                PRIMARY KEY(bucket,seconds,symbol));
        """)
        if "reclaimed_at" not in {
            r[1] for r in self.db.execute("PRAGMA table_info(storage_segments)")
        }:
            with self.db:
                self.db.execute("ALTER TABLE storage_segments ADD COLUMN reclaimed_at REAL")
        with self.db:
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(storage_records)")}
            for name, kind in (("available", "REAL"), ("bytes", "INTEGER")):
                if name not in columns:
                    self.db.execute(f"ALTER TABLE storage_records ADD COLUMN {name} {kind}")
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS storage_record_time "
                "ON storage_records(kind,at,segment,record)"
            )
        self.db.execute("PRAGMA max_page_count=" + str(plan.research_bytes // 4096))
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO storage_state(id,next_due,started) VALUES(1,?,?)",
                (time.time() + 7200, time.time()),
            )
        # A segment commit may precede a lost index acknowledgment. Reconcile only
        # active/orphan segments, never reinterpret their original availability.
        for row in self.db.execute("SELECT id FROM storage_segments WHERE state='active'"):
            if not self._path(row[0]).is_file():
                raise OSError("Capture recovery missing: an active segment is absent")
        for path in self.temporary.glob("segment-*.sqlite"):
            suffix = path.stem.removeprefix("segment-")
            if not suffix.isdecimal() or len(suffix) != 12 or int(suffix) <= 0:
                raise ValueError("Capture recovery foreign: unexpected segment name")
            number = int(suffix)
            if path != self._path(number):
                raise ValueError("Capture recovery foreign: noncanonical segment name")
            saved = self.db.execute(
                "SELECT state FROM storage_segments WHERE id=?", (number,)
            ).fetchone()
            if saved is not None and saved[0] != "active":
                continue
            if self.recovery["segments_checked"] >= 8:
                raise OSError("Capture recovery pending: eight segments reconciled; retry startup")
            with self._recovery_source(path, number, indexed=saved is not None) as source:
                with self.db:
                    self.db.execute(
                        (
                            "INSERT OR IGNORE INTO storage_segments(id,state,sealed_at,ex"
                            "pires) VALUES(?,'sealed',?,?)"
                        ),
                        (number, time.time(), time.time() + plan.temporary_retention_seconds),
                    )
                    count = size = 0
                    first = last = None
                    for record, sha, body in source.execute(
                        "SELECT id,sha,body FROM records ORDER BY id"
                    ):
                        if not isinstance(body, str) or len(body.encode()) > MAX_PACKET:
                            raise ValueError("Capture recovery corrupt: record exceeds its bound")
                        value = json.loads(body)
                        if digest(value) != sha:
                            raise ValueError("Interrupted capture checksum differs")
                        if not isinstance(value, dict) or (
                            type(value.get("at")) not in (int, float)
                            or not math.isfinite(value["at"])
                            or not isinstance(value.get("kind"), str)
                        ):
                            raise ValueError("Capture recovery corrupt: record metadata differs")
                        self.db.execute(
                            "INSERT OR IGNORE INTO storage_records"
                            "(sha,segment,record,at,kind,available,bytes) VALUES(?,?,?,?,?,?,?)",
                            (
                                sha,
                                number,
                                record,
                                value["at"],
                                value["kind"],
                                (
                                    source.execute(
                                        "SELECT available FROM record_availability WHERE id=?",
                                        (record,),
                                    ).fetchone()
                                    or (None,)
                                )[0]
                                if source.execute(
                                    "SELECT 1 FROM sqlite_master WHERE name='record_availability'"
                                ).fetchone()
                                else None,
                                len(body.encode()),
                            ),
                        )
                        self._pin_packet(
                            value, f"capture-v2:{number}:{record}:{sha}", number, time.time()
                        )
                        count += 1
                        size += len(body.encode())
                        first = value["at"] if first is None else first
                        last = value["at"]
                    self.db.execute(
                        (
                            "UPDATE storage_segments SET rows=?,bytes=?,first_at=?,last_a"
                            "t=? WHERE id=?"
                        ),
                        (count, size, first, last, number),
                    )
                self.recovery["segments_checked"] += 1
        with self.db:
            self.db.execute(
                "UPDATE storage_state SET rows=(SELECT count(*) FROM storage_"
                "records),last_capture=(SELECT max(at) FROM storage_records) "
                "WHERE id=1"
            )

    def _segment_marker(self, number: int) -> Path:
        return self._path(number).with_suffix(".owner.json")

    def _segment_identity(self, number: int) -> dict[str, Any]:
        return {
            "format": "capture-segment-owner-v1",
            "segment": number,
            "root_sha256": digest(
                str(self.root.resolve()).casefold() if os.name == "nt" else str(self.root.resolve())
            ),
            "storage_version": self.plan.version,
            "volume_identity": self.plan.volume_identity,
        }

    def _declare_segment(self, number: int) -> None:
        marker = self._segment_marker(number)
        self._not_redirected(marker)
        expected = self._segment_identity(number)
        if marker.exists():
            if json.loads(marker.read_text()) != expected:
                raise ValueError("Capture recovery foreign: segment ownership differs")
            return
        # This durable intent precedes creation/writes, including a lost index commit.
        with marker.open("x", encoding="utf-8") as out:
            out.write(canonical(expected))
            out.flush()
            os.fsync(out.fileno())

    @contextmanager
    def _recovery_source(
        self, path: Path, number: int, *, indexed: bool
    ) -> Iterator[sqlite3.Connection]:
        for candidate in (
            path,
            path.with_name(path.name + "-journal"),
            self._segment_marker(number),
        ):
            self._not_redirected(candidate)
        marker = self._segment_marker(number)
        owned = marker.exists()
        if owned and json.loads(marker.read_text()) != self._segment_identity(number):
            raise ValueError("Capture recovery foreign: segment ownership differs")
        if not (owned or indexed):
            raise ValueError("Capture recovery foreign: orphan has no durable owner intent")
        for suffix in ("-wal", "-shm"):
            if path.with_name(path.name + suffix).exists():
                raise ValueError("Capture recovery foreign: segment has unexpected WAL files")
        if path.stat().st_size > 2 * max(self.plan.segment_bytes, MAX_PACKET) + 131072:
            raise ValueError("Capture recovery corrupt: segment exceeds its bounded size")
        source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1)
        try:
            try:
                source.execute("SELECT id FROM records LIMIT 1").fetchone()
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode != sqlite3.SQLITE_READONLY_ROLLBACK:
                    raise
                self.recovery["rollbacks"] += 1
            source.close()
            # Non-creating and restricted to the verified owner's startup. The
            # reservation also refuses a competing SQLite writer outside our lock.
            # SQLite performs any rollback; no journal/record is manually edited.
            source = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0.1)
            source.execute("BEGIN IMMEDIATE")
            source.execute("PRAGMA query_only=ON")
            if source.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise ValueError("Capture recovery corrupt: segment integrity check failed")
            yield source
        except sqlite3.Error as exc:
            state = (
                "busy"
                if exc.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                else "corrupt"
            )
            raise OSError(f"Capture recovery {state}: segment could not be reconciled") from exc
        finally:
            source.close()

    def _check_volume(self) -> dict[str, Any]:
        for path in (self.root, self.root / "temporary", self.root / "research"):
            if path.exists() and (
                path.is_symlink()
                or (os.name == "nt" and bool(path.stat().st_file_attributes & 0x400))
            ):
                raise OSError("Owned research subtree was redirected; capture paused")
        observed = volume(self.root)
        if observed["identity"] != self.plan.volume_identity:
            raise OSError("Configured research volume identity changed; capture paused")
        return observed

    def admission(self, amount: int, tier: str, *, maturity: bool = False) -> None:
        observed = self._check_volume()
        reserve = self.plan.scratch_bytes
        if maturity:
            # Acquisition leaves this bounded output headroom untouched. Maturity
            # may use it without consuming scratch needed for a complete transfer.
            reserve -= min(16 * 1024**2, reserve - 2 * self.plan.segment_bytes)
        if observed["free_bytes"] < self.plan.free_reserve_bytes + reserve + amount:
            raise OSError("Research volume free-space reserve would be exceeded")
        directory, cap = (
            (self.temporary, self.plan.temporary_bytes)
            if tier == "temporary"
            else (self.research, self.plan.research_bytes)
        )
        # Bound SQLite page/WAL/index overhead as well as exact transfer scratch.
        if _bytes(directory) + amount + reserve > cap:
            raise OSError(f"{tier} tier quota reached; protected evidence preserved")

    def _path(self, number: int) -> Path:
        return self.temporary / f"segment-{number:012d}.sqlite"

    def _pin_packet(self, packet: dict[str, Any], reference: str, number: int, now: float) -> None:
        until = packet.get("protected_until", 0)
        if isinstance(until, (int, float)) and math.isfinite(until) and until > now:
            self.db.execute(
                "INSERT INTO storage_pins VALUES(?,?,?,?) ON CONFLICT(reference) "
                "DO UPDATE SET until_at=max(until_at,excluded.until_at)",
                (reference, number, until, "Declared pending research dependencies"),
            )
            self.db.execute(
                "UPDATE storage_segments SET pin_until=max(pin_until,?) WHERE id=?",
                (until, number),
            )

    def continue_legacy(self, path: Path) -> None:
        with self._exclusive():
            self._continue_legacy(path)

    def _continue_legacy(self, path: Path) -> None:
        if not path.exists():
            return
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            row = source.execute("SELECT rows,plan FROM evidence_meta WHERE id=1").fetchone()
            if source.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise ValueError("Historical archive must be preserved for inspection")
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO storage_legacy VALUES(?,?,?,?)",
                    (str(path.resolve()), row[0], row[1], time.time()),
                )

    def continue_compact(self, path: Path) -> Path:
        with self._exclusive():
            return self._continue_compact(path)

    def _continue_compact(self, path: Path) -> Path:
        destination = self.research / "memory-episodes.sqlite"
        if destination.exists() or not path.exists():
            return destination
        # SQLite's supported backup includes committed WAL. The original and its
        # frozen capacity metadata are never edited or removed.
        self.admission(path.stat().st_size * 2 + 131072, "research")
        staged = destination.with_suffix(".partial")
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(staged)) as target:
                source.backup(target, pages=128)
                if target.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                    raise ValueError("Compact continuation backup failed verification")
                for table in ("compact_prefixes", "compact_events", "compact_outcomes"):
                    for body, sha in target.execute(f"SELECT body,sha256 FROM {table}"):
                        if digest(json.loads(body)) != sha:
                            raise ValueError("Compact continuation checksum differs")
        os.replace(staged, destination)
        return destination

    def append(
        self, packets: list[dict[str, Any]], now: float, *, defer_retention: bool = False
    ) -> list[str]:
        with self._exclusive():
            return self._append(packets, now, defer_retention=defer_retention)

    def _append(
        self, packets: list[dict[str, Any]], now: float, *, defer_retention: bool = False
    ) -> list[str]:
        if len(packets) > 8:
            raise ValueError("Research batch exceeds eight shared observations")
        refs = []
        self._check_volume()
        with ExitStack() as opened, self.db:
            segments: dict[int, sqlite3.Connection] = {}
            self.db.execute("BEGIN IMMEDIATE")
            for packet in packets:
                if type(packet.get("at")) not in (float, int) or not math.isfinite(packet["at"]):
                    raise ValueError("Capture requires a real finite availability time")
                body = canonical(packet)
                sha = digest(packet)
                old = self.db.execute(
                    "SELECT segment,record FROM storage_records WHERE sha=?", (sha,)
                ).fetchone()
                if old is not None:
                    refs.append(f"capture-v2:{old[0]}:{old[1]}:{sha}")
                    continue
                size = len(body.encode())
                if size > MAX_PACKET:
                    raise ValueError("Research packet exceeds bounded serialization")
                self.admission(size * 3 + 65536, "temporary")
                row = self.db.execute(
                    "SELECT * FROM storage_segments WHERE state='active' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row is not None and row["bytes"] + size > self.plan.segment_bytes:
                    self.db.execute(
                        (
                            "UPDATE storage_segments SET state='sealed',sealed_at=?,expir"
                            "es=? WHERE id=?"
                        ),
                        (now, now + self.plan.temporary_retention_seconds, row["id"]),
                    )
                    row = None
                if row is None:
                    number = self.db.execute(
                        "INSERT INTO storage_segments(state) VALUES('active') RETURNING id"
                    ).fetchone()[0]
                else:
                    number = row["id"]
                # A segment uses ordinary rollback journaling: one bounded writer,
                # no copied live WAL. Its commit is verified again before retirement.
                segment = segments.get(number)
                if segment is None:
                    self._not_redirected(self._path(number))
                    self._declare_segment(number)
                    segment = opened.enter_context(
                        closing(sqlite3.connect(self._path(number), timeout=0.1))
                    )
                    segments[number] = segment
                    segment.execute("PRAGMA synchronous=FULL")
                    segment.execute(
                        "CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,sh"
                        "a TEXT UNIQUE NOT NULL,body TEXT NOT NULL)"
                    )
                    segment.execute(
                        "CREATE TABLE IF NOT EXISTS record_availability"
                        "(id INTEGER PRIMARY KEY,available REAL NOT NULL)"
                    )
                record = segment.execute(
                    "INSERT OR IGNORE INTO records(sha,body) VALUES(?,?) RETURNING id",
                    (sha, body),
                ).fetchone()
                if record is None:
                    record = segment.execute(
                        "SELECT id FROM records WHERE sha=?", (sha,)
                    ).fetchone()
                    count, stored_bytes = segment.execute(
                        "SELECT count(*),sum(length(CAST(body AS BLOB))) FROM records"
                    ).fetchone()
                    self.db.execute(
                        "UPDATE storage_segments SET rows=?,bytes=? WHERE id=?",
                        (count, stored_bytes, number),
                    )
                    observed = segment.execute(
                        "SELECT available FROM record_availability WHERE id=?", (record[0],)
                    ).fetchone()
                    available = observed[0] if observed else None
                else:
                    available = max(
                        now,
                        packet["at"],
                        (packet.get("financial_commit") or {}).get("committed_at", packet["at"]),
                    )
                    segment.execute(
                        "INSERT OR IGNORE INTO record_availability VALUES(?,?)",
                        (record[0], available),
                    )
                    self.db.execute(
                        "UPDATE storage_segments SET rows=rows+1,bytes=bytes+?,"
                        "first_at=coalesce(first_at,?),last_at=? WHERE id=?",
                        (size, packet["at"], packet["at"], number),
                    )
                self.db.execute(
                    "UPDATE storage_state SET rows=rows+1,last_capture=? WHERE id=1",
                    (packet["at"],),
                )
                refs.append(f"capture-v2:{number}:{record[0]}:{digest(packet)}")
                self.db.execute(
                    "INSERT INTO storage_records(sha,segment,record,at,kind,available,bytes) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        sha,
                        number,
                        record[0],
                        packet["at"],
                        packet["kind"],
                        available,
                        size,
                    ),
                )
                self._pin_packet(packet, refs[-1], number, now)
                if packet.get("kind") == "summary":
                    for symbol, market in packet.get("markets", {}).items():
                        midpoint = market.get("mid")
                        if midpoint is None:
                            continue
                        for seconds in (60, 300, 3600):
                            bucket = int(packet["at"] // seconds) * seconds
                            self.db.execute(
                                (
                                    "INSERT INTO storage_rollups VALUES(?,?,?,1,?,?,?,?,?) ON CON"
                                    "FLICT(bucket,seconds,symbol) DO UPDATE SET samples=samples+1"
                                    ",minimum=min(minimum,excluded.minimum),maximum=max(maximum,e"
                                    "xcluded.maximum),last=excluded.last,available=max(available,"
                                    "excluded.available),gaps=gaps+excluded.gaps"
                                ),
                                (
                                    bucket,
                                    seconds,
                                    symbol,
                                    float(midpoint),
                                    float(midpoint),
                                    float(midpoint),
                                    now,
                                    int(bool(packet.get("gaps"))),
                                ),
                            )
            # FULL durability once per touched segment in this <=8-record batch,
            # followed by the index commit. Never weaken synchronous=FULL to hide
            # USB latency. A failed index acknowledgment recovers from exact rows.
            for segment in segments.values():
                segment.commit()
        pressure = _bytes(self.temporary) > self.plan.temporary_bytes - 2 * self.plan.scratch_bytes
        # One finite original-window request can defer optional cold transfers.
        # Every packet still passes admission and FULL durability; pressure keeps
        # the existing maintenance authority and can refuse the window.
        if pressure or not defer_retention:
            self.housekeeping(now, capacity_triggered=pressure)
        return refs

    def protect(self, reference: str, until_at: float, reason: str) -> None:
        with self._exclusive():
            self._protect(reference, until_at, reason)

    def _protect(self, reference: str, until_at: float, reason: str) -> None:
        number, _, _ = self.parse_reference(reference)
        self.reopen(reference)  # Never accept an unresolvable dependency.
        with self.db:
            self.db.execute(
                (
                    "INSERT INTO storage_pins VALUES(?,?,?,?) ON CONFLICT(referen"
                    "ce) DO UPDATE SET until_at=max(until_at,excluded.until_at)"
                ),
                (reference, number, until_at, reason[:200]),
            )
            self.db.execute(
                "UPDATE storage_segments SET pin_until=max(pin_until,?) WHERE id=?",
                (until_at, number),
            )

    @staticmethod
    def parse_reference(reference: str) -> tuple[int, int, str]:
        version, number, record, sha = reference.split(":")
        if (
            version != "capture-v2"
            or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
            or int(number) <= 0
            or int(record) <= 0
        ):
            raise ValueError("Invalid exact research reference")
        return int(number), int(record), sha

    def reopen(self, reference: str) -> dict[str, Any]:
        self._check_volume()
        number, record, sha = self.parse_reference(reference)
        path = self._path(number)
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                row = db.execute(
                    "SELECT body FROM records WHERE id=? AND sha=?", (record, sha)
                ).fetchone()
            if row:
                value: dict[str, Any] = json.loads(row[0])
                if digest(value) == sha:
                    return value
                raise ValueError("Temporary evidence checksum differs")
        retained = self.db.execute(
            "SELECT retained_sha FROM storage_segments WHERE id=? AND state='retained'", (number,)
        ).fetchone()
        if retained:
            target = self.research / f"segment-{number:012d}.jsonl.gz"
            if self.file_sha(target) != retained[0]:
                raise ValueError("Retained segment checksum differs")
            with gzip.open(target, "rt", encoding="utf-8") as source:
                for line in source:
                    item = json.loads(line)
                    if item["id"] == record:
                        if item["sha"] != sha or digest(item["payload"]) != sha:
                            raise ValueError("Retained evidence checksum differs")
                        value = item["payload"]
                        return dict(value)
        raise LookupError("Exact research reference unavailable; no substitute inferred")

    @staticmethod
    def file_sha(path: Path) -> str:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()

    def housekeeping(self, now: float, *, capacity_triggered: bool = False) -> dict[str, Any]:
        with self._exclusive():
            return self._housekeeping(now, capacity_triggered=capacity_triggered)

    def _housekeeping(self, now: float, *, capacity_triggered: bool = False) -> dict[str, Any]:
        self._check_volume()
        try:
            # This index transaction is also the cross-process housekeeping lease.
            self.db.execute("BEGIN IMMEDIATE")
            state = self.db.execute("SELECT * FROM storage_state WHERE id=1").fetchone()
            if not capacity_triggered and now < state["next_due"]:
                self.db.rollback()
                return {"state": "not_due"}
            self.db.execute(
                (
                    "UPDATE storage_segments SET state='sealed',sealed_at=?,expir"
                    "es=? WHERE state='active'"
                ),
                (now, now + self.plan.temporary_retention_seconds),
            )
            read = written = reclaimed = 0
            # Bounded continuation: at most two complete segments per attempt.
            for row in self.db.execute(
                "SELECT * FROM storage_segments WHERE state='sealed' ORDER BY id LIMIT 2"
            ).fetchall():
                self.admission(row["bytes"] * 2 + 65536, "research")
                source, number = self._path(row["id"]), row["id"]
                target = self.research / f"segment-{number:012d}.jsonl.gz"
                partial = target.with_suffix(".partial")
                with closing(
                    sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
                ) as db:
                    if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                        raise ValueError("Sealed capture segment is corrupt")
                    has_availability = db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='record_availability'"
                    ).fetchone()
                    records = db.execute(
                        "SELECT r.id,r.sha,r.body,a.available FROM records r "
                        "LEFT JOIN record_availability a ON a.id=r.id ORDER BY r.id"
                        if has_availability
                        else "SELECT id,sha,body,NULL FROM records ORDER BY id"
                    )
                    # Interrupted copies are replaced only from the intact source.
                    with gzip.open(partial, "wt", encoding="utf-8") as out:
                        for item in records:
                            payload = json.loads(item[2])
                            if digest(payload) != item[1]:
                                raise ValueError("Capture checksum differs before transfer")
                            out.write(
                                canonical(
                                    {
                                        "id": item[0],
                                        "sha": item[1],
                                        "payload": payload,
                                        "available": item[3],
                                    }
                                )
                                + "\n"
                            )
                with partial.open("r+b") as staged:
                    os.fsync(staged.fileno())
                count = 0
                with gzip.open(partial, "rt", encoding="utf-8") as verify:
                    for line in verify:
                        item = json.loads(line)
                        if digest(item["payload"]) != item["sha"]:
                            raise ValueError("Retained transfer verification failed")
                        count += 1
                # Source commit could precede a crashed index commit. Count the
                # verified source, not an inferred missing/dropped record.
                sha, size = self.file_sha(partial), partial.stat().st_size
                os.replace(partial, target)
                self.db.execute(
                    (
                        "UPDATE storage_segments SET state='retained',rows=?,retained"
                        "_sha=?,retained_bytes=? WHERE id=?"
                    ),
                    (count, sha, size, number),
                )
                read += source.stat().st_size
                written += size
            remaining = self.db.execute(
                "SELECT count(*) FROM storage_segments WHERE state='sealed'"
            ).fetchone()[0]
            self.db.execute(
                (
                    "UPDATE storage_state SET next_due=?,reason=?,read_bytes=?,wr"
                    "itten_bytes=?,reclaimed_bytes=0 WHERE id=1"
                ),
                (
                    now + (1 if remaining else 7200),
                    "Verified exact retained copies; temporary expiration pending"
                    if written
                    else "No eligible material to transfer or reclaim",
                    read,
                    written,
                ),
            )
            self.db.commit()  # Durable verified destination BEFORE eligible unlink.
            # The index lock serializes protection, unlink and its durable acknowledgment.
            # After a crash between unlink and commit, retry verifies the retained copy
            # and acknowledges the absent source without inferring reclaimed byte counts.
            self.db.execute("BEGIN IMMEDIATE")
            for row in self.db.execute(
                (
                    "SELECT * FROM storage_segments WHERE state='retained' AND ex"
                    "pires<=? AND pin_until<=? AND reclaimed_at IS NULL ORDER BY id LIMIT 2"
                ),
                (now, now),
            ).fetchall():
                target = self.research / f"segment-{row['id']:012d}.jsonl.gz"
                if self.file_sha(target) != row["retained_sha"]:
                    raise ValueError("Destination differs; last source preserved")
                path = self._path(row["id"])
                marker = self._segment_marker(row["id"])
                self._not_redirected(path)
                self._not_redirected(marker)
                if marker.exists() and json.loads(marker.read_text()) != self._segment_identity(
                    row["id"]
                ):
                    raise ValueError("Capture recovery foreign: segment ownership differs")
                if path.exists():
                    size = path.stat().st_size
                    path.unlink()
                    reclaimed += size
                if marker.exists():
                    marker.unlink()
                self.db.execute(
                    "UPDATE storage_segments SET reclaimed_at=? WHERE id=?", (now, row["id"])
                )
            pending_cleanup = self.db.execute(
                "SELECT 1 FROM storage_segments WHERE state='retained' AND expires<=? "
                "AND pin_until<=? AND reclaimed_at IS NULL LIMIT 1",
                (now, now),
            ).fetchone()
            with self.db:
                self.db.execute(
                    "UPDATE storage_state SET last_success=?,reclaimed_bytes=?,reason=?,"
                    "next_due=? WHERE id=1",
                    (
                        now,
                        reclaimed,
                        "Verified transfer and eligible temporary reclamation"
                        if reclaimed
                        else "Verified maintenance; no eligible temporary space reclaimed",
                        now + (1 if remaining or pending_cleanup else 7200),
                    ),
                )
            return {
                "state": "verified",
                "read_bytes": read,
                "written_bytes": written,
                "reclaimed_bytes": reclaimed,
            }
        except Exception as exc:
            self.db.rollback()
            with self.db:
                self.db.execute(
                    "UPDATE storage_state SET next_due=?,reason=? WHERE id=1",
                    (now + 60, str(exc)[:250]),
                )
            raise

    def snapshot(self) -> dict[str, Any]:
        observed = self._check_volume()
        state = dict(self.db.execute("SELECT * FROM storage_state WHERE id=1").fetchone())
        temporary, research = (
            _bytes(self.temporary),
            _bytes(self.research) + (self.root / "owned.json").stat().st_size,
        )
        elapsed = max(1, time.time() - state["started"])
        rate = (
            self.db.execute("SELECT coalesce(sum(bytes),0) FROM storage_segments").fetchone()[0]
            / elapsed
        )
        protected = self.db.execute(
            "SELECT coalesce(sum(bytes),0) FROM storage_segments WHERE pin_until>?", (time.time(),)
        ).fetchone()[0]
        return {
            "version": self.plan.version,
            "recovery": self.recovery,
            "state": "recording",
            "plan": self.plan.model_dump(),
            "temporary_path": str(self.temporary),
            "research_path": str(self.research),
            "temporary_bytes": temporary,
            "research_bytes": research,
            "maturity_headroom_bytes": min(
                16 * 1024**2, self.plan.scratch_bytes - 2 * self.plan.segment_bytes
            ),
            "free_bytes": observed["free_bytes"],
            "protected_bytes": protected,
            "pending_segments": self.db.execute(
                "SELECT count(*) FROM storage_segments WHERE state!='retained'"
            ).fetchone()[0],
            "capture_bytes_per_second": rate,
            "estimated_temporary_runway_seconds": (self.plan.temporary_bytes - temporary) / rate
            if rate
            else None,
            "retained_lifecycle": (
                "Exact lossless segments retained; capacity stops rather than"
                " deleting protected/history inputs"
            ),
            "rollups": (
                "60/300/3600-second sampled midpoint min/max/last; descriptiv"
                "e, not exchange OHLC or executable replay"
            ),
            **state,
        }

    def close(self) -> None:
        self.db.close()


def storage_snapshot(directory: Path) -> dict[str, Any]:
    """UI reads cached worker receipt and current volume, without creating a database."""
    try:
        plan = load_plan(directory)
    except (OSError, ValueError) as exc:
        return {"state": "unavailable", "reason": str(exc)[:250], "fallback": False}
    if plan is None:
        return {
            "state": "not_configured",
            "default_root": DEFAULT_ROOT,
            "temporary_quota_bytes": 100 * GB,
            "research_quota_bytes": 100 * GB,
            "reason": (
                "External v2 continuation requires a declared storage plan at"
                " worker startup; historical v1 archive stays frozen"
            ),
        }
    try:
        observed = volume(Path(plan.root))
        if observed["identity"] != plan.volume_identity:
            raise OSError("Declared volume mapping differs")
        receipt = directory / "research-storage-status.json"
        status = json.loads(receipt.read_text()) if receipt.exists() else {}
        return {
            "plan": plan.model_dump(),
            "state": "awaiting_worker" if not status else status.get("state"),
            **status,
            "free_bytes": observed["free_bytes"],
            "receipt_queried_at": time.time(),
        }
    except (OSError, ValueError) as exc:
        return {
            "plan": plan.model_dump(),
            "state": "unavailable",
            "reason": str(exc),
            "fallback": False,
        }


def reopen_evidence(plan: StoragePlan, reference: str) -> dict[str, Any]:
    reader = object.__new__(ResearchStorage)
    reader.plan, reader.root = plan, Path(plan.root)
    reader.temporary, reader.research = reader.root / "temporary", reader.root / "research"
    with closing(
        sqlite3.connect(
            (reader.research / "storage-index.sqlite").resolve().as_uri() + "?mode=ro", uri=True
        )
    ) as db:
        reader.db = db
        return reader.reopen(reference)
