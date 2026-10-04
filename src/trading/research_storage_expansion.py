"""The reviewed 100-to-400 decimal GB successor; no evidence or financial writes."""

import json
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from trading.research_evidence import canonical, digest
from trading.research_storage import GB, StoragePlan, volume


def _owned_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or (
            os.name == "nt" and part.exists() and part.stat().st_file_attributes & 0x400
        ):
            raise ValueError("Storage metadata cannot traverse redirected paths")


def _text(path: Path) -> str:
    _owned_path(path)
    if not path.is_file() or path.stat().st_size > 16 * 1024:
        raise ValueError("Expected bounded storage metadata is unavailable")
    # Keep Windows CRLF exactly: the successor retains original metadata bytes.
    with path.open("r", encoding="utf-8", newline="") as source:
        return source.read()


def _replace(path: Path, text: str) -> None:
    """An interrupted two-file change remains recoverable from its saved original."""
    staged = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    with staged.open("x", encoding="utf-8", newline="") as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    os.replace(staged, path)


def _successor(directory: Path, *, apply: bool) -> dict[str, Any]:
    _owned_path(directory)
    plan_path = directory / "research-storage.json"
    plan_text = _text(plan_path)
    current = StoragePlan.model_validate_json(plan_text)
    root = Path(current.root)
    _owned_path(root)
    observed = volume(root)
    if observed["identity"] != current.volume_identity:
        raise ValueError("Declared research volume identity differs")
    marker_path = root / "owned.json"
    marker_text = _text(marker_path)
    receipt_path = directory / "temporary-storage-100-to-400gb.json"
    if receipt_path.exists():
        receipt = json.loads(_text(receipt_path))
        if set(receipt) != {
            "version",
            "before_plan",
            "before_marker",
            "after_plan",
            "after_marker",
        }:
            raise ValueError("Storage successor receipt has an unsupported contract")
        if receipt["version"] != "temporary-storage-successor-v1":
            raise ValueError("Storage successor receipt version differs")
        before = StoragePlan.model_validate_json(receipt["before_plan"])
        after = StoragePlan.model_validate_json(receipt["after_plan"])
        if before.temporary_bytes != 100 * GB or after != StoragePlan.model_validate(
            {**before.model_dump(), "temporary_bytes": 400 * GB}
        ):
            raise ValueError("Recorded successor differs from the reviewed quota-only change")
        if json.loads(receipt["before_marker"]) != {
            "plan_sha256": digest(before.model_dump()),
            "version": before.version,
        } or json.loads(receipt["after_marker"]) != {
            "plan_sha256": digest(after.model_dump()),
            "version": after.version,
        }:
            raise ValueError("Recorded storage marker identities differ")
        if plan_text not in (receipt["before_plan"], receipt["after_plan"]) or marker_text not in (
            receipt["before_marker"],
            receipt["after_marker"],
        ):
            raise ValueError("Storage metadata changed outside the recorded successor")
    else:
        if current.temporary_bytes != 100 * GB:
            raise ValueError("Expected the existing 100 GB temporary quota")
        before = current
        after = StoragePlan.model_validate({**before.model_dump(), "temporary_bytes": 400 * GB})
        if json.loads(marker_text) != {
            "plan_sha256": digest(before.model_dump()),
            "version": before.version,
        }:
            raise ValueError("Owned storage marker differs; no replacement inferred")
        receipt = {
            "version": "temporary-storage-successor-v1",
            "before_plan": plan_text,
            "before_marker": marker_text,
            "after_plan": after.model_dump_json(indent=2),
            "after_marker": canonical(
                {"plan_sha256": digest(after.model_dump()), "version": after.version}
            ),
        }
    if current.root != before.root or current.volume_identity != before.volume_identity:
        raise ValueError("Storage successor cannot relocate or change volume identity")
    complete = plan_text == receipt["after_plan"] and marker_text == receipt["after_marker"]
    if (
        not complete
        and observed["free_bytes"] < 300 * GB + before.free_reserve_bytes + 2 * before.scratch_bytes
    ):
        raise OSError("Insufficient free space for the extra 300 GB and existing reserves")
    if apply and not complete:
        if not receipt_path.exists():
            if len(canonical(receipt).encode("utf-8")) > 16 * 1024:
                raise ValueError("Original storage metadata exceeds the bounded successor receipt")
            with receipt_path.open("x", encoding="utf-8", newline="") as out:
                out.write(canonical(receipt))
                out.flush()
                os.fsync(out.fileno())
        # The updater holds the stopped supervisor's mutex and this operation
        # holds the financial-writer lock. A crash fails closed: normal startup
        # rejects mismatched metadata; an explicit retry completes this receipt.
        if marker_text != receipt["after_marker"]:
            _replace(marker_path, receipt["after_marker"])
        if plan_text != receipt["after_plan"]:
            _replace(plan_path, receipt["after_plan"])
        if (
            _text(plan_path) != receipt["after_plan"]
            or _text(marker_path) != receipt["after_marker"]
        ):
            raise RuntimeError("Expanded storage metadata was not verified")
    return {
        "mode": "applied" if apply else "preview",
        "already_applied": complete,
        "previous_temporary_bytes": before.temporary_bytes,
        "target_temporary_bytes": after.temporary_bytes,
        "research_bytes": after.research_bytes,
        "additional_bytes": after.temporary_bytes - before.temporary_bytes,
        "free_bytes": observed["free_bytes"],
        "before_plan_sha256": digest(before.model_dump()),
        "after_plan_sha256": digest(after.model_dump()),
        "evidence_files_modified": False,
        "financial_rows_modified": False,
        "activation": "Worker startup reads the expanded frozen plan; no worker started here",
    }


def expand_temporary_storage(
    directory: Path, dsn: str, *, target_gb: int, expected_gb: int, apply: bool = False
) -> dict[str, Any]:
    """Preview by default. The existing updater owns stopping/restarting services."""
    if (target_gb, expected_gb) != (400, 100):
        raise ValueError("Only the reviewed 100-to-400 decimal GB temporary increase is supported")
    if not apply:
        return _successor(directory, apply=False)
    try:
        with (
            psycopg.connect(
                dsn,
                autocommit=True,
                connect_timeout=3,
                row_factory=dict_row,
                application_name="qtrades_temporary_storage_expansion",
            ) as connection,
            connection.transaction(),
        ):
            connection.execute("SET LOCAL statement_timeout='3000'")
            owned = connection.execute(
                "SELECT pg_try_advisory_xact_lock("
                "hashtext(current_database() || current_schema()),734921) AS acquired"
            ).fetchone()
            if not owned or not owned["acquired"]:
                raise RuntimeError("The financial writer is active; storage was not changed")
            initialized = connection.execute("SELECT id FROM paper_state WHERE id=1").fetchone()
            if not initialized:
                raise RuntimeError(
                    "The initialized paper database is unavailable; storage was not changed"
                )
            return _successor(directory, apply=True)
    except psycopg.Error:
        raise RuntimeError("Storage expansion database guard failed") from None
