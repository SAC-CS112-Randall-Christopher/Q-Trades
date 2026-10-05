"""Real snapshot/concurrency, unattended reader recovery and owned-query shutdown."""

import asyncio
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from threading import Event

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from test_paper_engine import START, frame, study
from test_paper_store import pg_store as pg_store

from trading.financial_readback import FinancialReadback
from trading.tiered_runtime import TieredPaperRuntime


def test_readback_authenticates_separately_and_cannot_modify_financial_data(pg_store):
    store, _ = pg_store
    before = store.read(), store.export(0, 1000)
    view = FinancialReadback(store)
    try:
        sample = view.sample(audit=True)
        assert sample["reconciliation"]["balanced"]
        assert sample["storage_usage"]["journal_lines"] > 0
        assert sample["observed_at"] <= sample["completed_at"]
        assert set(sample["stages_ms"]) == {"recent", "reconcile", "storage_usage"}
        assert view._view.connection.info.backend_pid != store.connection.info.backend_pid
        assert not view._view.owner
        assert view._view.connection.execute("SHOW default_transaction_read_only").fetchone() == {
            "default_transaction_read_only": "on"
        }
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            view._view.connection.execute("UPDATE paper_state SET revision=revision+1")
    finally:
        view.close()
    assert (store.read(), store.export(0, 1000)) == before


def test_reconciliation_uses_one_snapshot_while_financial_writer_commits(pg_store, monkeypatch):
    store, _ = pg_store
    view = FinancialReadback(store)
    view.sample(audit=False)
    before = store.read()["revision"]
    original = view._view.read
    read_entered, writer_committed = Event(), Event()

    def overlapping_read():
        state = original()
        read_entered.set()
        assert writer_committed.wait(3)
        return state

    monkeypatch.setattr(view._view, "read", overlapping_read)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(view.sample, audit=True)
            assert read_entered.wait(3)
            store.transact(START, lambda engine: engine.tick({"BTCUSD": frame()}, study()))
            writer_committed.set()
            sample = future.result(timeout=3)
        assert sample["reconciliation"]["revision"] == before
        assert sample["reconciliation"]["balanced"]
        monkeypatch.setattr(view._view, "read", original)
        next_sample = view.sample(audit=True)
        assert next_sample["reconciliation"]["revision"] > before
        assert next_sample["reconciliation"]["balanced"]
    finally:
        writer_committed.set()
        view.close()


@pytest.mark.parametrize("after_good_audit", [False, True])
def test_background_readback_recovers_real_connection_outage_without_restart(
    pg_store, monkeypatch, tmp_path, after_good_audit
):
    import trading.tiered_runtime as runtime_module

    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.disk_free = 10 * 1024**3  # Isolate this reader test from the host's capture reserve.
    view = FinancialReadback(store)
    original_dsn = view._dsn
    from trading.financial_readback_worker import ReadbackWorker

    reader = ReadbackWorker(view)
    monkeypatch.setattr(runtime_module, "ReadbackWorker", lambda _: reader)

    async def scenario():
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            outage_dsn = make_conninfo(original_dsn, port=unavailable.getsockname()[1])
            if not after_good_audit:
                reader._dsn = outage_dsn
            worker = asyncio.create_task(runtime._financial_readback_loop())
            try:
                retained = None
                if after_good_audit:
                    async with asyncio.timeout(6):
                        while runtime._readback_sample is None:
                            await asyncio.sleep(0.01)
                    assert runtime.journal_status()["status"] == "balanced"
                    assert runtime.journal_status()["available"] is True
                    assert runtime._readback_sample["refresh_errors"] == {}
                    retained = dict(runtime.receipts)
                    reader._dsn = outage_dsn
                    await reader.close()  # The owned idle disposable connection only.
                # Include the real 5s poll interval, 3s connect timeout and spawn.
                try:
                    async with asyncio.timeout(10):
                        while runtime.journal_status()["error"] is None:
                            if worker.done():
                                worker.result()
                            await asyncio.sleep(0.01)
                except TimeoutError:
                    pytest.fail(str({
                        "journal": runtime.journal_status(),
                        "sample": runtime._readback_sample,
                        "shutdown": runtime._readback_shutdown,
                        "reader_alive": reader._process is not None
                        and reader._process.is_alive(),
                    }))
                assert not worker.done() and runtime.constrained()
                assert runtime.journal_status()["error"] is not None
                if runtime._readback_error is None:
                    assert runtime._readback_sample["refresh_errors"]
                if retained:
                    assert runtime.receipts == retained
                    assert runtime.journal_status()["status"] == "unavailable"
                else:
                    assert runtime._readback_audit_mono is None
                reader._dsn = original_dsn
                async with asyncio.timeout(8):
                    while runtime.readback_unavailable():
                        await asyncio.sleep(0.01)
                assert not worker.done() and runtime.receipts["balanced"]
                assert runtime._readback_error is None and not runtime.constrained()
                store.transact(START + 1, lambda engine: None)
                assert store.reconcile()["balanced"]
            finally:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["pending", "balanced", "expired", "unavailable", "imbalanced"])
def test_api_snapshot_notice_and_admission_share_current_audit_status(pg_store, tmp_path, mode):
    from fastapi.testclient import TestClient

    from trading.api import create_app
    from trading.config import Settings
    from trading.research_notices import operational_conditions

    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.running = True
    runtime.state["last_tick"] = time.time()
    runtime.disk_free = 10 * 1024**3
    if mode != "pending":
        reader = FinancialReadback(store)
        try:
            runtime._accept_financial_audit(reader.sample(audit=True))
        finally:
            reader.close()
    if mode == "expired":
        runtime._readback_audit_mono = time.monotonic() - 121
        runtime.receipts["available"] = True  # A stale stored flag must not govern publication.
    elif mode == "unavailable":
        runtime._readback_error = "Synthetic monitoring failure"
    elif mode == "imbalanced":
        store.transact(START, lambda e: e.state["accounts"]["primary"].update(cash="90"))
        reader = FinancialReadback(store)
        try:
            with pytest.raises(RuntimeError, match="reconciliation failed"):
                runtime._accept_financial_audit(reader.sample(audit=True))
        finally:
            reader.close()
    original = dict(runtime.receipts)
    app = create_app(Settings(), tmp_path / "api.sqlite", background=False)
    with TestClient(app) as client:
        app.state.paper = runtime
        api = client.get("/api/status").json()["paper"]
        health = client.get("/api/health").json()
    notice = next(
        r
        for r in operational_conditions(runtime, time.time())
        if r["key"] == "financial_monitoring"
    )
    assert api["journal"]["status"] == health["journal_monitoring"]["status"] == mode
    assert notice["facts"]["status"] == mode
    assert notice["condition"] == (
        "clear" if mode == "balanced" else "active" if mode == "imbalanced" else "unknown"
    )
    assert api["journal"]["available"] == api["performance"]["financial_readback"]["available"]
    assert runtime.constrained() == (mode != "balanced")
    assert runtime.receipts == original  # Reads do not rewrite dates or verified history.
    if mode in {"expired", "unavailable"}:
        assert api["journal"]["balanced"] is True
        assert health["journal_balanced"] is None
        assert health["journal_last_balanced"] is True
        assert api["journal"]["checked_at"] == original["checked_at"]


def test_normal_supervisor_stops_for_a_confirmed_reconciliation_failure(
    pg_store, monkeypatch, tmp_path
):
    store, _ = pg_store
    # Disposable corruption probe: never perform this mutation in an operating database.
    store.transact(START, lambda engine: engine.state["accounts"]["primary"].update(cash="90"))
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")

    async def no_op(*args):
        pass

    async def parked(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.stream, "configure", no_op)
    monkeypatch.setattr(runtime.stream, "close", no_op)
    for name in ("_references", "_fallback_loop", "_capture_loop", "_futures_loop"):
        monkeypatch.setattr(runtime, name, parked)
    monkeypatch.setattr(runtime.evidence, "run", parked)
    monkeypatch.setattr(runtime, "current_frames", lambda: ({}, {}))
    asyncio.run(asyncio.wait_for(runtime.run(), timeout=3))
    assert not runtime.running and runtime.error
    assert runtime.receipts["balanced"] is False
    assert runtime.constrained()


def test_readback_age_and_query_error_keep_optional_research_closed(pg_store, tmp_path):
    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.disk_free = 10 * 1024**3
    assert runtime.constrained()
    runtime._readback_audit_mono = time.monotonic()
    runtime.receipts = {"balanced": True}
    assert not runtime.constrained()
    runtime._readback_error = "Durable financial monitoring query unavailable"
    assert runtime.constrained()
    runtime._readback_error = None
    runtime._readback_audit_mono = time.monotonic() - 120
    assert runtime.constrained()
    snapshot = runtime.snapshot()
    assert (
        "financial_readback_unavailable"
        in snapshot["performance"]["resource_guard"]["blocking_conditions"]
    )
    assert snapshot["performance"]["financial_readback"]["available"] is False
    assert snapshot["journal"]["available"] is False
    assert snapshot["journal"]["status"] == "expired"


@pytest.mark.parametrize("ancillary", ["recent", "storage_usage"])
def test_completed_negative_audit_cannot_be_hidden_by_ancillary_failure(
    pg_store, monkeypatch, ancillary
):
    store, _ = pg_store
    view = FinancialReadback(store)
    view.sample(audit=False)
    store.transact(START, lambda e: e.state["accounts"]["primary"].update(cash="90"))

    def unavailable():
        raise psycopg.OperationalError("Synthetic ancillary outage")

    monkeypatch.setattr(view._view, ancillary, unavailable)
    try:
        result = view.sample(audit=True)
        assert result["reconciliation"]["balanced"] is False
        assert result["reconciliation"]["revision"] == store.read()["revision"]
    finally:
        view.close()


@pytest.mark.parametrize("ancillary", ["recent", "storage_usage"])
def test_ancillary_failure_does_not_prevent_completed_audit(pg_store, monkeypatch, ancillary):
    store, _ = pg_store
    view = FinancialReadback(store)
    view.sample(audit=False)

    def unavailable():
        raise psycopg.OperationalError("Synthetic ancillary outage")

    monkeypatch.setattr(view._view, ancillary, unavailable)
    try:
        result = view.sample(audit=True)
        assert result["reconciliation"]["balanced"] is True
        assert ancillary in result["refresh_errors"]
        assert ancillary not in result
    finally:
        view.close()
