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


def test_background_readback_recovers_real_connection_outage_without_restart(
    pg_store, monkeypatch, tmp_path
):
    import trading.tiered_runtime as runtime_module

    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.disk_free = 10 * 1024**3  # Isolate this reader test from the host's capture reserve.
    view = FinancialReadback(store)
    original_dsn = view._dsn
    monkeypatch.setattr(runtime_module, "FinancialReadback", lambda _: view)

    async def scenario():
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            view._dsn = make_conninfo(original_dsn, port=unavailable.getsockname()[1])
            worker = asyncio.create_task(runtime._financial_readback_loop())
            try:
                async with asyncio.timeout(6):
                    while runtime._readback_error is None:
                        await asyncio.sleep(0.01)
                assert not worker.done() and runtime.constrained()
                assert runtime._readback_audit_mono is None
                view._dsn = original_dsn
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


@pytest.mark.parametrize("cancel_count", [1, 2])
def test_shutdown_drains_owned_query_before_closing_connection(
    pg_store, monkeypatch, tmp_path, cancel_count
):
    import trading.tiered_runtime as runtime_module

    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    view = FinancialReadback(store)
    entered, release, closed = Event(), Event(), Event()
    sample, close = view.sample, view.close

    def blocked_sample(*, audit):
        entered.set()
        assert release.wait(3)
        assert not closed.is_set()
        return sample(audit=audit)

    def verified_close():
        assert release.is_set()
        close()
        closed.set()

    monkeypatch.setattr(view, "sample", blocked_sample)
    monkeypatch.setattr(view, "close", verified_close)
    monkeypatch.setattr(runtime_module, "FinancialReadback", lambda _: view)

    async def scenario():
        worker = asyncio.create_task(runtime._financial_readback_loop())
        assert await asyncio.to_thread(entered.wait, 2)
        worker.cancel()
        await asyncio.sleep(0.02)
        assert not worker.done() and not closed.is_set()
        if cancel_count == 2:
            worker.cancel()
            await asyncio.sleep(0.02)
            assert not worker.done() and not closed.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await worker
        assert closed.is_set()
    asyncio.run(scenario())


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
    assert "financial_readback_unavailable" in snapshot["performance"]["resource_guard"][
        "blocking_conditions"
    ]
    assert snapshot["performance"]["financial_readback"]["available"] is False
