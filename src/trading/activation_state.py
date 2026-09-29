"""Read-only financial checkpoints and a pre-worker startup guard for local updates."""

import hashlib
import json
from pathlib import Path
from typing import Any

from psycopg import IsolationLevel

from trading.local_updates import UpdateError, read_record, write_record
from trading.options_store import OptionsStore
from trading.paper_store import PaperStore, load_dsn

ACTIVATION_NAME = "local-activation.json"
ACK_NAME = "local-activation-startup.json"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def ledger_checkpoint(store: Any) -> dict[str, Any]:
    """Caller supplies a stable transaction or owns the sole financial writer."""
    state = store.read()
    if state.get("schema") != 1 or not store.reconcile()["balanced"]:
        raise UpdateError("Existing financial history is unsupported or does not reconcile")
    connection = store.connection
    rows = connection.execute(
        "SELECT count(*) AS count, coalesce(max(id),0) AS last FROM paper_events"
    ).fetchone()
    journal = hashlib.sha256()
    count = 0
    # Financial lines are small; do not copy raw market history or secrets to receipts.
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM paper_journal ORDER BY event_id,line_no")
        while chunk := cursor.fetchmany(512):
            for row in chunk:
                journal.update(digest(row).encode())
                count += 1
    return {
        "schema": state["schema"],
        "revision": state["revision"],
        "state_sha256": digest(state),
        "events": rows,
        "journal_rows": count,
        "journal_sha256": journal.hexdigest(),
        "accounts": sorted(state["accounts"]),
    }


def runtime_binding(runtime: Path) -> str:
    names = ("configs/paper.toml", "data/paper-database.json", "compose.yaml")
    # Hashes only. Database credentials never leave the local configuration file.
    values = {name: hashlib.sha256((runtime / name).read_bytes()).hexdigest() for name in names}
    return digest({"root": str(runtime.resolve()), "files": values})


def capture_accounts(runtime: Path, *, require_stopped: bool = False) -> dict[str, Any]:
    """No DDL, financial mutation, initialization, backup restore or model access."""
    dsn = load_dsn(runtime / "data/paper-database.json")
    result: dict[str, Any] = {"runtime_binding": runtime_binding(runtime)}
    stores: list[Any] = []
    try:
        spot = PaperStore(dsn)
        stores.append(spot)
        exists = spot.connection.execute(
            "SELECT to_regclass('options_paper.paper_state') IS NOT NULL AS present"
        ).fetchone()
        options = OptionsStore(dsn, owner=False) if exists and exists["present"] else None
        if options:
            stores.append(options)
        for name, store in (("paper", spot), ("options", options)):
            if store is None:
                result[name] = None
                continue
            connection = store.connection
            if require_stopped:
                row = connection.execute(
                    "SELECT pg_try_advisory_lock(hashtext(current_database() || "
                    "current_schema()), 734921) AS acquired"
                ).fetchone()
                if not row or not row["acquired"]:
                    raise UpdateError("A financial writer is still active; update cannot continue")
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.transaction():
                result[name] = ledger_checkpoint(store)
        return result
    finally:
        for store in reversed(stores):
            store.close()  # Also releases temporary writer-exclusion advisory locks.


def verify_startup(
    source: Path, runtime: Path, identity: dict[str, Any], paper: Any, options: Any
) -> None:
    """Called with writer locks held, before financial workers are scheduled."""
    path = runtime / "data" / ACTIVATION_NAME
    if not path.exists():
        return
    operation = read_record(path)
    phase = operation.get("phase")
    if phase in {"verified", "recovered", "cancelled"}:
        return
    if phase not in {"starting", "recovering_start"}:
        raise UpdateError("An interrupted local update needs recovery before paper startup")
    expected = operation.get("launch")
    if (
        not isinstance(expected, dict)
        or str(source.resolve()) != expected.get("code_root")
        or str(runtime.resolve()) != operation.get("runtime_root")
        or identity.get("commit") != expected.get("commit")
        or identity.get("dirty") is not False
    ):
        raise UpdateError("Startup code does not match the authorized local update")
    current = {
        "runtime_binding": runtime_binding(runtime),
        "paper": ledger_checkpoint(paper),
        "options": ledger_checkpoint(options) if options else None,
    }
    if current != operation.get("baseline"):
        raise UpdateError("Account checkpoint changed before startup; no worker was started")
    write_record(
        runtime / "data" / ACK_NAME,
        {"operation": operation["id"], "commit": identity["commit"], "checkpoint": digest(current)},
    )
