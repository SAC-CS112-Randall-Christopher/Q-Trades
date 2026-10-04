"""Freeze and audit one finite original window; read-only source, private output."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from trading.execution_replay import source_hashes
from trading.recorded_window import verify_recorded_window
from trading.research_evidence import canonical, digest
from trading.research_storage import load_plan, reopen_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_directory", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists() or any(
        (p / ".git").exists() for p in (destination, *destination.parents)
    ):
        raise ValueError("Use a new private artifact directory outside every Git checkout")
    if any(p.is_symlink() or p.is_junction() for p in destination.parents if p.exists()):
        raise ValueError("Private output cannot traverse a redirected directory")
    status = json.loads((args.data_directory / "execution-window-status.json").read_text())
    if status["state"] != "captured_pending_reconciliation":
        raise ValueError("A complete elapsed capture is required before this audit")
    request_id = status["request"]["request_id"]
    first, last = status["first_at"], status["last_at"]
    if not 2700 <= last - first <= 2705:
        raise ValueError("The actual finite window has an unsupported horizon")
    plan = load_plan(args.data_directory)
    if plan is None:
        raise ValueError("Use the existing configured research storage; no fallback")
    index = Path(plan.root) / "research" / "storage-index.sqlite"
    with closing(sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            "SELECT segment,record,sha FROM storage_records WHERE kind='decision' "
            "AND at>=? AND at<=? ORDER BY at,segment,record LIMIT 10001",
            (first, last),
        ).fetchall()
    if not rows or len(rows) > 10000:
        raise ValueError("Missing records or finite audit record budget exceeded")
    destination.mkdir(parents=True)
    (destination / "capture-status.json").write_text(canonical(status), encoding="utf-8")
    original = destination / "records.jsonl"

    def records():
        with original.open("x", encoding="utf-8") as frozen:
            for segment, record, sha in rows:
                reference = f"capture-v2:{segment}:{record}:{sha}"
                packet = reopen_evidence(plan, reference)
                if packet.get("execution_window", {}).get("request_id") != request_id:
                    raise ValueError("A selected record lacks the exact capture request")
                value = {"id": reference, "sha256": sha, "payload": packet}
                frozen.write(canonical(value) + "\n")
                yield value

    source = source_hashes()
    try:
        report = verify_recorded_window(records(), source)
    except (OSError, LookupError, ValueError) as exc:
        (destination / "audit.json").write_text(
            canonical(
                {
                    "status": "incomplete",
                    "boundary": str(exc),
                    "full_horizon_verified": False,
                    "financial_authority": False,
                }
            ),
            encoding="utf-8",
        )
        raise
    if report["records_reconciled"] != status["records"]:
        report.update(status="incomplete", full_horizon_verified=False, capture_count_mismatch=True)
    with original.open("rb") as stream:
        identity = hashlib.file_digest(stream, "sha256").hexdigest()
    report.update(
        source_files=source,
        capture_status_sha256=digest(status),
        frozen_records_sha256=identity,
        original_records_bytes=original.stat().st_size,
    )
    (destination / "audit.json").write_text(canonical(report), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "records_reconciled",
                    "observed_seconds",
                    "full_horizon_verified",
                    "fill_events",
                    "no_trade_ticks",
                    "boundary",
                    "market_improvement_established",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
