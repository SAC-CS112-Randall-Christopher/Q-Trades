"""Generate writer-authentic disposable fixtures; inspect only finalized copies."""

import base64
import hashlib
import json
import os
import random
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from trading.research_evidence import MAX_PACKET, canonical, digest
from trading.research_storage import ResearchStorage, StoragePlan, volume

from .codecs import Clock, Identity, StudyError, identity

SEED = 20261005
EPOCH = 1_800_000_000.0


@contextmanager
def frozen_db(path: Path) -> Iterator[sqlite3.Connection]:
    # This entry point accepts only finalized specimens, never a mutable operating database.
    for suffix in ("-journal", "-wal", "-shm"):
        if path.with_name(path.name + suffix).exists():
            raise StudyError("Finalized specimen has an unresolved SQLite sidecar")
    if path.is_symlink():
        raise StudyError("Redirected specimen refused")
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)
    ) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA cache_size=-1024")
        yield db


def record_rows(db: sqlite3.Connection) -> sqlite3.Cursor:
    has = db.execute("SELECT 1 FROM sqlite_master WHERE name='record_availability'").fetchone()
    return db.execute(
        "SELECT r.id,r.sha,r.body,a.available FROM records r "
        "LEFT JOIN record_availability a ON a.id=r.id ORDER BY r.id"
        if has
        else "SELECT id,sha,body,NULL FROM records ORDER BY id"
    )


def exported(row: Any) -> dict[str, Any]:
    payload = json.loads(row[2])
    if digest(payload) != row[1]:
        raise StudyError("Specimen payload hash differs")
    return {"id": row[0], "sha": row[1], "payload": payload, "available": row[3]}


def sqlite_signature(path: Path) -> dict[str, Any]:
    clock, raw, evidence = Clock(), hashlib.sha256(), hashlib.sha256()
    count = 0
    with frozen_db(path) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise StudyError("SQLite integrity check failed")
        schema = db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall()
        for row in record_rows(db):
            clock.check()
            raw.update((canonical(tuple(row)) + "\n").encode())
            evidence.update((canonical(exported(row)) + "\n").encode())
            count += 1
        availability = hashlib.sha256()
        has = db.execute("SELECT 1 FROM sqlite_master WHERE name='record_availability'").fetchone()
        if has:
            for row in db.execute("SELECT id,available FROM record_availability ORDER BY id"):
                clock.check()
                availability.update((canonical(tuple(row)) + "\n").encode())
        page_count = db.execute("PRAGMA page_count").fetchone()[0]
        free_pages = db.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
    return {
        "records": count,
        "schema_sha256": digest(schema),
        "raw_records_sha256": raw.hexdigest(),
        "evidence_sha256": evidence.hexdigest(),
        "availability_sha256": availability.hexdigest(),
        "page_count": page_count,
        "free_pages": free_pages,
        "page_size": page_size,
    }


def verify_sqlite(path: Path, expected: dict[str, Any]) -> None:
    if sqlite_signature(path) != expected:
        raise StudyError("Complete SQLite record/availability/schema equivalence differs")


def export_jsonl(source: Path, destination: Path) -> Identity:
    # Same canonical object, ordering, text encoding and native text newline as _housekeeping.
    clock = Clock()
    with frozen_db(source) as db, destination.open("x", encoding="utf-8", newline=None) as out:
        for row in record_rows(db):
            clock.check()
            out.write(canonical(exported(row)) + "\n")
        out.flush()
        os.fsync(out.fileno())
    return identity(destination)


def jsonl_signature(path: Path) -> dict[str, Any]:
    clock, evidence, count, previous = Clock(), hashlib.sha256(), 0, 0
    with path.open("rb") as src:
        while line := src.readline(MAX_PACKET + 4096):
            clock.check()
            if not line.endswith(b"\n") or len(line) >= MAX_PACKET + 4096:
                raise StudyError("Incomplete/oversized archive record")
            item = json.loads(line)
            if (
                set(item) != {"id", "sha", "payload", "available"}
                or type(item["id"]) is not int
                or item["id"] <= previous
                or digest(item["payload"]) != item["sha"]
            ):
                raise StudyError("Archive evidence/reference verification failed")
            previous = item["id"]
            evidence.update((canonical(item) + "\n").encode())
            count += 1
    return {"records": count, "evidence_sha256": evidence.hexdigest()}


def verify_jsonl(path: Path, expected: dict[str, Any]) -> None:
    actual = jsonl_signature(path)
    if any(actual[k] != expected[k] for k in actual):
        raise StudyError("Complete exported evidence differs")


def probes(path: Path) -> dict[str, Any]:
    with frozen_db(path) as db:
        count = db.execute("SELECT count(*) FROM records").fetchone()[0]
        if not count:
            return {"references": [], "range": [0, 0]}
        rng = random.Random(SEED)
        offsets = sorted({0, count // 2, count - 1, rng.randrange(count)})
        refs = [
            tuple(
                db.execute(
                    "SELECT id,sha FROM records ORDER BY id LIMIT 1 OFFSET ?", (i,)
                ).fetchone()
            )
            for i in offsets
        ]
        middle_id = refs[offsets.index(count // 2)][0]
        return {"references": refs, "range": [middle_id, middle_id + 3]}


def read_sqlite(path: Path, selection: dict[str, Any]) -> dict[str, Any]:
    wall, cpu = time.perf_counter(), time.process_time()
    # The compressed-path caller has already verified the entire restored specimen.
    h = hashlib.sha256()
    with frozen_db(path) as db:
        for record_id, sha in selection["references"]:
            row = db.execute(
                "SELECT r.id,r.sha,r.body,a.available FROM records r "
                "LEFT JOIN record_availability a ON a.id=r.id WHERE r.id=? AND r.sha=?",
                (record_id, sha),
            ).fetchone()
            if row is None:
                raise StudyError("Exact reference unavailable")
            h.update(canonical(exported(row)).encode())
        for row in db.execute(
            "SELECT r.id,r.sha,r.body,a.available FROM records r "
            "LEFT JOIN record_availability a ON a.id=r.id WHERE r.id BETWEEN ? AND ? ORDER BY r.id",
            tuple(selection["range"]),
        ):
            h.update(canonical(exported(row)).encode())
    return {
        "wall_s": time.perf_counter() - wall,
        "cpu_s": time.process_time() - cpu,
        "selection_sha256": h.hexdigest(),
    }


def read_jsonl(path: Path, selection: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    wall, cpu = time.perf_counter(), time.process_time()
    verify_jsonl(path, expected)  # Stronger than early exit: complete evidence is checked.
    selected, h = {}, hashlib.sha256()
    wanted = {int(i): sha for i, sha in selection["references"]}
    range_start, range_end = selection["range"]
    ranged = []
    with path.open("rb") as src:
        for line in src:
            item = json.loads(line)
            if item["id"] in wanted:
                if item["sha"] != wanted[item["id"]]:
                    raise StudyError("Archive exact reference differs")
                selected[item["id"]] = item
            if range_start <= item["id"] <= range_end:
                ranged.append(item)
    if set(selected) != set(wanted):
        raise StudyError("Archive exact reference unavailable")
    for record_id, _ in selection["references"]:
        h.update(canonical(selected[record_id]).encode())
    for item in ranged:
        h.update(canonical(item).encode())
    return {
        "wall_s": time.perf_counter() - wall,
        "cpu_s": time.process_time() - cpu,
        "selection_sha256": h.hexdigest(),
    }


def make_fixture(parent: Path, name: str, *, rows: int = 24) -> Path:
    if name not in {"repeated", "mixed", "noisy"} or not 1 <= rows <= 24:
        raise StudyError("Fixture shape exceeds initial smoke budget")
    directory = parent / name
    directory.mkdir()
    root = directory / "Q-Trades-Data-synthetic"
    plan = StoragePlan(
        root=str(root),
        volume_identity=volume(root)["identity"],
        temporary_bytes=8 * 1024**2,
        research_bytes=8 * 1024**2,
        scratch_bytes=128 * 1024,
        segment_bytes=64 * 1024,
        free_reserve_bytes=5 * 1024**3,
        temporary_retention_seconds=7200,
    )
    rng = random.Random(SEED)
    with closing(ResearchStorage(plan)) as owner:
        for i in range(rows):
            sample = (
                "repeated evidence / same structure; " * 32
                if name == "repeated"
                else rng.randbytes(512).hex()
                if name == "mixed"
                else base64.b64encode(rng.randbytes(1536)).decode("ascii")
            )
            packet = {
                "kind": "compression-study-synthetic",
                "at": EPOCH + i / 8,
                "ordinal": i,
                "sample": sample,
                "decimal": "0.000000010000000000",
                "unicode": "水 🚰 café e\u0301",
                "timestamp": "2026-10-05T07:00:00.123456-06:00",
                "nullable": None,
                "booleans": [True, False],
                "list": ["1.00", None, i],
                "financial_commit": {"committed_at": EPOCH + i / 8 + 0.03125},
            }
            if i % 2:
                packet["optional"] = None  # Distinguish a null value from an absent field.
            owner.append([packet], EPOCH + 10, defer_retention=True)
        paths = list(Path(owner.temporary).glob("segment-*.sqlite"))
        if len(paths) != 1:
            raise StudyError("Fixture unexpectedly rolled over")
        for ref in owner.db.execute("SELECT segment,record,sha FROM storage_records"):
            reference = f"capture-v2:{ref[0]}:{ref[1]}:{ref[2]}"
            owner.reopen(reference)  # Existing writer/reader proves exact lookup before close.
    source = paths[0]
    sqlite_signature(source)  # Close writer before byte reference is frozen.
    return source


def make_specimens(parent: Path, *, smallest: bool = False) -> list[dict[str, Any]]:
    parent.mkdir()
    specs: list[dict[str, Any]] = []
    for name in ("repeated",) if smallest else ("repeated", "mixed", "noisy"):
        sqlite = make_fixture(parent, name, rows=2 if smallest else 24)
        signature, selection = sqlite_signature(sqlite), probes(sqlite)
        archive = parent / (name + ".jsonl")
        export_jsonl(sqlite, archive)
        verify_jsonl(archive, signature)
        for representation, path in (("sqlite", sqlite), ("jsonl", archive)):
            specs.append(
                {
                    "label": name,
                    "representation": representation,
                    "path": str(path),
                    "input": identity(path).dump(),
                    "signature": signature,
                    "probes": selection,
                    "provenance": "synthetic-existing-storage-writer",
                    "transformation": "none"
                    if representation == "sqlite"
                    else (
                        "retained-owner canonical JSONL export; native newline; "
                        "separate layout comparison"
                    ),
                }
            )
    if not smallest:
        raw = parent / "incompressible.bin"
        raw.write_bytes(random.Random(SEED).randbytes(64 * 1024))
        specs.append(
            {
                "label": "incompressible",
                "representation": "raw",
                "path": str(raw),
                "input": identity(raw).dump(),
                "signature": None,
                "probes": None,
                "provenance": "synthetic-seeded-incompressible-bytes",
                "transformation": "none",
            }
        )
    if sum(s["input"]["length"] for s in specs) > 128 * 1024**2:
        raise StudyError("Combined specimen input exceeds 128 MiB")
    return specs
