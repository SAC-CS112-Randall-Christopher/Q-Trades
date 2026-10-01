"""Read-only bounded decision acquisition across immutable v1 and segmented v2 archives."""

import gzip
import json
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

from trading.research_evidence import MAX_PACKET, digest
from trading.research_storage import ResearchStorage, load_plan

MAX_BYTES = 8 * 1024**2
MAX_SCAN_BYTES = 64 * 1024**2


class DependencyBudget(ValueError):
    """Complete dependencies cannot fit; never substitute a first-N sample."""


def decision_records(
    path: Path,
    first: float,
    last: float,
    as_of: float,
    *,
    limit: int = 512,
    complete: bool = True,
    anchor: int | str | None = None,
    bytes_limit: int = MAX_BYTES,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    excluded = 0
    with ExitStack() as stack:
        legacy = None
        if path.exists():
            legacy = stack.enter_context(
                closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True))
            )
            legacy.row_factory = sqlite3.Row
            legacy.execute("PRAGMA query_only=ON")
            legacy.execute("BEGIN")
            excluded += legacy.execute(
                "SELECT count(*) FROM evidence_records WHERE kind='decision' AND at<?", (first,)
            ).fetchone()[0]
            anchor_args: tuple[Any, ...]
            anchor_clause = (
                " AND (at>? OR id>=?)"
                if isinstance(anchor, int)
                else " AND at>?"
                if isinstance(anchor, str)
                else ""
            )
            anchor_args = (
                (first, anchor)
                if isinstance(anchor, int)
                else (first,)
                if isinstance(anchor, str)
                else ()
            )
            candidates.extend(
                {**dict(row), "archive": "full"}
                for row in legacy.execute(
                    "SELECT id,at,sha256,bytes FROM evidence_records WHERE kind='decision' "
                    "AND at>=? AND at<=?" + anchor_clause + " ORDER BY at,id LIMIT ?",
                    (first, min(last, as_of), *anchor_args, limit + 1),
                )
            )
        reader = None
        plan = load_plan(path.parent)
        if plan:
            reader = object.__new__(ResearchStorage)
            reader.plan, reader.root = plan, Path(plan.root)
            reader.temporary, reader.research = reader.root / "temporary", reader.root / "research"
            reader._check_volume()
            if json.loads((reader.root / "owned.json").read_text()) != {
                "version": plan.version,
                "plan_sha256": digest(plan.model_dump()),
            }:
                raise ValueError("Research ownership marker differs")
            db = stack.enter_context(
                closing(
                    sqlite3.connect(
                        (reader.research / "storage-index.sqlite").resolve().as_uri() + "?mode=ro",
                        uri=True,
                    )
                )
            )
            reader.db = db
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            columns = {row[1] for row in db.execute("PRAGMA table_info(storage_records)")}
            availability = "available" if "available" in columns else "NULL AS available"
            size = "bytes" if "bytes" in columns else "NULL AS bytes"
            excluded += db.execute(
                "SELECT count(*) FROM storage_records WHERE kind='decision' AND at<?", (first,)
            ).fetchone()[0]
            if (
                "available" not in columns
                or db.execute(
                    "SELECT 1 FROM storage_records WHERE kind='decision' AND at>=? "
                    "AND at<=? AND available IS NULL LIMIT 1",
                    (first, min(last, as_of)),
                ).fetchone()
            ):
                raise ValueError(
                    "Original capture availability was not recorded; interval is unavailable"
                )
            anchor_clause, anchor_args = "", ()
            if isinstance(anchor, str):
                number, record, _ = reader.parse_reference(anchor)
                anchor_clause = " AND (at>? OR segment>? OR (segment=? AND record>=?))"
                anchor_args = (first, number, number, record)
            for row in db.execute(
                "SELECT sha,segment,record,at,"
                + availability
                + ","
                + size
                + " FROM storage_records WHERE kind='decision' AND at>=? AND at<=? "
                "AND available<=?" + anchor_clause + " ORDER BY at,segment,record LIMIT ?",
                (first, min(last, as_of), as_of, *anchor_args, limit + 1),
            ):
                if row["available"] is None:
                    raise ValueError(
                        "Original capture availability was not recorded; interval is unavailable"
                    )
                if row["available"] <= as_of:
                    candidates.append(
                        {
                            **dict(row),
                            "id": f"capture-v2:{row['segment']}:{row['record']}:{row['sha']}",
                            "sha256": row["sha"],
                            "archive": "capture-v2",
                        }
                    )
        candidates.sort(
            key=lambda row: (
                row["at"],
                row["archive"] != "full",
                row["id"] if row["archive"] == "full" else row["segment"],
                row.get("record", 0),
            )
        )
        selected: list[dict[str, Any]] = []
        seen = set()
        started = anchor is None
        for row in candidates:
            if anchor is not None and row["id"] == anchor:
                started = True
            if not started or row["sha256"] in seen:
                continue
            seen.add(row["sha256"])
            selected.append(row)
        if anchor is not None and (not selected or selected[0]["id"] != anchor):
            raise ValueError("Selected decision is missing; no later record substituted")
        if complete and len(selected) > limit:
            raise DependencyBudget(f"Complete decision interval exceeds {limit} records")
        selected = selected[:limit]
        if sum(row.get("bytes") or 0 for row in selected) > bytes_limit:
            raise DependencyBudget(f"Complete dependencies exceed {bytes_limit} byte budget")
        loaded: dict[str, dict[str, Any]] = {}
        scan = 0
        if reader:
            groups: dict[int, list[dict[str, Any]]] = {}
            for row in selected:
                if row["archive"] == "capture-v2":
                    groups.setdefault(row["segment"], []).append(row)
            for segment, rows in groups.items():
                source_path = reader._path(segment)
                required = {row["record"]: row for row in rows}
                if source_path.exists():
                    with closing(
                        sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
                    ) as source:
                        for number, sha, body in source.execute(
                            "SELECT id,sha,body FROM records WHERE id IN ("
                            + ",".join("?" for _ in rows)
                            + ")",
                            tuple(required),
                        ):
                            observed = source.execute(
                                "SELECT available FROM record_availability WHERE id=?", (number,)
                            ).fetchone()
                            if (
                                sha != required[number]["sha256"]
                                or not observed
                                or observed[0] != required[number]["available"]
                            ):
                                raise ValueError("Original capture metadata differs")
                            loaded[required[number]["id"]] = json.loads(body)
                else:
                    meta = reader.db.execute(
                        "SELECT retained_sha FROM storage_segments WHERE id=? AND state='retained'",
                        (segment,),
                    ).fetchone()
                    target = reader.research / f"segment-{segment:012d}.jsonl.gz"
                    if (
                        not meta
                        or target.stat().st_size > MAX_SCAN_BYTES
                        or reader.file_sha(target) != meta[0]
                    ):
                        raise ValueError("Exact retained dependency missing or changed")
                    with gzip.open(target, "rt", encoding="utf-8") as source:
                        while line := source.readline(MAX_PACKET + 1024):
                            scan += len(line.encode())
                            if scan > MAX_SCAN_BYTES or not line.endswith("\n"):
                                raise DependencyBudget(
                                    "Complete retained dependencies exceed bounded scan"
                                )
                            item = json.loads(line)
                            row = required.get(item["id"])
                            if row:
                                if (
                                    item["sha"] != row["sha256"]
                                    or item.get("available") != row["available"]
                                ):
                                    raise ValueError("Retained dependency metadata differs")
                                loaded[row["id"]] = item["payload"]
        result = []
        total = 0
        for row in selected:
            if row["archive"] == "full":
                assert legacy is not None
                raw = legacy.execute(
                    "SELECT payload FROM evidence_records WHERE id=?", (row["id"],)
                ).fetchone()
                payload = json.loads(raw[0])
            else:
                payload = loaded.get(row["id"])
            if (
                payload is None
                or digest(payload) != row["sha256"]
                or payload.get("at") != row["at"]
            ):
                raise ValueError("Exact decision dependency unavailable or checksum differs")
            available = max(
                row["at"], (payload.get("financial_commit") or {}).get("committed_at", row["at"])
            )
            if available > as_of:
                raise ValueError("Selected financial commit was unavailable at cutoff")
            total += len(json.dumps(payload).encode())
            if total > bytes_limit:
                raise DependencyBudget(f"Complete dependencies exceed {bytes_limit} byte budget")
            result.append(
                {
                    "id": row["id"],
                    "at": row["at"],
                    "sha256": row["sha256"],
                    "archive": row["archive"],
                    "available_at": row.get("available", available),
                    "payload": payload,
                }
            )
        return {
            "records": result,
            "source_bytes": total,
            "excluded_older_records": excluded,
            "archives": ["full"] * bool(legacy) + ["capture-v2"] * bool(reader),
            "retained_scan_bytes": scan,
        }


def replay_records(
    path: Path, reference: int | str, count: int, as_of: float
) -> list[dict[str, Any]]:
    if isinstance(reference, str):
        from trading.research_storage import reopen_evidence

        plan = load_plan(path.parent)
        if plan is None:
            raise ValueError("Selected v2 archive is not configured")
        first = reopen_evidence(plan, reference)["at"]
    else:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT at FROM evidence_records WHERE id=? AND kind='decision'", (reference,)
            ).fetchone()
            if row is None:
                raise ValueError("Selected decision is missing; no later record substituted")
            first = row[0]
    records: list[dict[str, Any]] = decision_records(
        path,
        first,
        as_of,
        as_of,
        limit=count,
        complete=False,
        anchor=reference,
        bytes_limit=16 * 1024**2,
    )["records"]
    return records
