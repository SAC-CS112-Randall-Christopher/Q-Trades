"""Disposable PostgreSQL evidence for account preservation and startup refusal."""

import copy
import json

import pytest
from fastapi.testclient import TestClient
from test_paper_engine import START, frame, study
from test_paper_store import pg_store as _pg_fixture

from trading import activation_state as s
from trading import api
from trading.config import Settings
from trading.local_updates import UpdateError, write_record
from trading.paper_store import PaperStore

disposable_store = _pg_fixture


def runtime_files(root, dsn):
    (root / "data").mkdir()
    (root / "configs").mkdir()
    (root / "data/paper-database.json").write_text(json.dumps({"dsn": str(dsn)}))
    (root / "configs/paper.toml").write_text("# disposable runtime\n")
    (root / "compose.yaml").write_text("# disposable runtime\n")


def test_capture_is_readonly_and_cannot_hide_a_running_writer(
    disposable_store, tmp_path, monkeypatch
):
    store, dsn = disposable_store
    runtime_files(tmp_path, dsn)
    before = store.read()
    original = s.ledger_checkpoint
    modes = []

    def checked(connection):
        row = connection.connection.execute("SHOW transaction_read_only").fetchone()
        modes.append(row["transaction_read_only"])
        return original(connection)

    monkeypatch.setattr(s, "ledger_checkpoint", checked)
    snapshot = s.capture_accounts(tmp_path)
    assert snapshot["paper"]["accounts"] == sorted(before["accounts"])
    assert set(modes) == {"on"}
    assert store.read() == before
    with pytest.raises(UpdateError, match="writer is still active"):
        s.capture_accounts(tmp_path, require_stopped=True)
    store.close()
    stopped = s.capture_accounts(tmp_path, require_stopped=True)
    assert stopped == snapshot
    # Probe handles and advisory locks must be closed on both success and exception.
    reopened = PaperStore(dsn, owner=True)
    reopened.close()


def plan(root, source, baseline):
    return {
        "id": "f" * 32,
        "phase": "starting",
        "runtime_root": str(root),
        "launch": {"code_root": str(source), "commit": "a" * 40},
        "baseline": baseline,
    }


def test_startup_preserves_pending_orders_balances_and_journal_before_worker_dispatch(
    disposable_store, tmp_path, monkeypatch
):
    store, dsn = disposable_store
    runtime_files(tmp_path, dsn)
    store.transact(START, lambda e: e.tick({"BTCUSD": frame()}, study()))
    before = store.read()
    assert before["accounts"]["primary"]["pending"]
    baseline = s.capture_accounts(tmp_path)
    source = tmp_path / "separate-code"
    source.mkdir()
    record = plan(tmp_path, source, baseline)
    write_record(tmp_path / "data" / s.ACTIVATION_NAME, record)
    identity = {"commit": "a" * 40, "dirty": False, "kind": "prepared_release"}
    monkeypatch.setattr(api, "source_identity", lambda _: identity)
    store.close()
    # Real API lifespan, real exclusive writer, real startup guard; no market workers.
    app = api.create_app(
        Settings(),
        tmp_path / "data/monitor.sqlite3",
        background=False,
        paper_database=tmp_path / "data/paper-database.json",
        source_root=source,
        preserve_existing=True,
    )
    with TestClient(app):
        ack = s.read_record(tmp_path / "data" / s.ACK_NAME)
        assert ack == {
            "operation": record["id"],
            "commit": "a" * 40,
            "checkpoint": s.digest(baseline),
        }
        assert app.state.paper.store.read() == before
        assert app.state.options is None  # No new legacy options account created by update.
    reader = PaperStore(dsn)
    try:
        assert reader.read() == before
    finally:
        reader.close()


@pytest.mark.parametrize(
    "change", ["cash", "pending", "journal", "commit", "dirty", "phase", "runtime"]
)
def test_startup_rejects_changed_evidence_before_any_worker_can_run(
    disposable_store, tmp_path, change
):
    store, dsn = disposable_store
    runtime_files(tmp_path, dsn)
    baseline = s.capture_accounts(tmp_path)
    source = tmp_path / "code"
    source.mkdir()
    operation = plan(tmp_path, source, copy.deepcopy(baseline))
    identity = {"commit": "a" * 40, "dirty": False}
    if change in {"cash", "pending"}:
        operation["baseline"]["paper"]["state_sha256"] = "old-account-state"
    if change == "journal":
        operation["baseline"]["paper"]["journal_sha256"] = "old-history"
    if change == "commit":
        identity["commit"] = "b" * 40
    if change == "dirty":
        identity["dirty"] = True
    if change == "phase":
        operation["phase"] = "stopped"
    if change == "runtime":
        operation["runtime_root"] = str(tmp_path / "wrong-data")
    write_record(tmp_path / "data" / s.ACTIVATION_NAME, operation)
    before = store.read()
    with pytest.raises(UpdateError):
        s.verify_startup(source, tmp_path, identity, store, None)
    assert store.read() == before
    assert not (tmp_path / "data" / s.ACK_NAME).exists()


def test_completed_installation_restart_does_not_compare_against_old_trades(
    disposable_store, tmp_path
):
    store, dsn = disposable_store
    runtime_files(tmp_path, dsn)
    write_record(tmp_path / "data" / s.ACTIVATION_NAME, {"phase": "verified"})
    store.transact(START, lambda e: e.tick({"BTCUSD": frame()}, study()))
    s.verify_startup(tmp_path, tmp_path, {"commit": "a" * 40, "dirty": False}, store, None)
    assert store.read()["accounts"]["primary"]["pending"]
