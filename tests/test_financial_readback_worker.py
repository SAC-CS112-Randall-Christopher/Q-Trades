"""Owned-child faults, actual libpq cancellation and bounded Windows/POSIX shutdown."""

import asyncio
import time
import uuid
from contextlib import suppress
from threading import Event

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

import trading.financial_readback_worker as worker_module
from trading.financial_readback import FinancialReadback
from trading.financial_readback_worker import ReadbackWorker, readback_child
from trading.paper_store import PaperStore
from trading.tiered_runtime import TieredPaperRuntime


def blocked_database_child(pipe, dsn):
    reader = FinancialReadback.from_dsn(dsn)
    reader._view = PaperStore(dsn)
    reader._view.connection.execute("SET statement_timeout = 0")  # Disposable session only.
    original = reader._view.reconcile

    def blocked():
        reader._view.connection.execute("SELECT pg_sleep(30)")
        return original()

    reader._view.reconcile = blocked
    FinancialReadback.from_dsn = classmethod(lambda cls, _: reader)
    readback_child(pipe, dsn)


def blocked_client_child(pipe, dsn):
    reader = FinancialReadback.from_dsn(dsn)
    reader._view = PaperStore(dsn)

    def blocked():
        Event().wait()  # No test release: only the owned process termination can finish.

    reader._view.reconcile = blocked
    FinancialReadback.from_dsn = classmethod(lambda cls, _: reader)
    readback_child(pipe, dsn)


def malformed_receipt_child(pipe, dsn):
    pipe.recv()
    pipe.send_bytes(b"A")
    pipe.close()


def incomplete_audit_child(pipe, dsn):
    pipe.recv()
    worker_module._send(pipe, b"A", {"reconciliation": {"balanced": True, "revision": 1}})
    pipe.close()


def incomplete_sample_child(pipe, dsn):
    pipe.recv()
    reader = FinancialReadback.from_dsn(dsn)
    try:
        reader.sample(
            audit=True, publish_audit=lambda value: worker_module._send(pipe, b"A", value)
        )
        worker_module._send(pipe, b"S", {})
    finally:
        reader.close()
        pipe.close()


@pytest.mark.parametrize(
    "child", [malformed_receipt_child, incomplete_audit_child, incomplete_sample_child]
)
def test_incomplete_transport_receipt_remains_unknown_and_nonfatal(
    pg_store, monkeypatch, tmp_path, child
):
    import trading.tiered_runtime as runtime_module

    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    reader = ReadbackWorker(FinancialReadback(store))
    monkeypatch.setattr(worker_module, "readback_child", child)
    monkeypatch.setattr(runtime_module, "ReadbackWorker", lambda _: reader)

    async def scenario():
        task = asyncio.create_task(runtime._financial_readback_loop())
        try:
            async with asyncio.timeout(5):
                while runtime._readback_error is None:
                    await asyncio.sleep(0.01)
            assert not task.done() and runtime.error is None
            assert runtime._financial_failure is None
            if child is incomplete_sample_child:
                assert runtime.receipts["balanced"] is True
                assert runtime._readback_audit_mono is not None
            else:
                assert runtime.receipts == {} and runtime._readback_audit_mono is None
            assert runtime.journal_status()["status"] == "unavailable"
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert reader._process is None

    asyncio.run(scenario())


async def wait_for_backend(store, name, *, active=False):
    async with asyncio.timeout(8):
        while True:
            rows = store.connection.execute(
                "SELECT pid,state,query FROM pg_stat_activity WHERE application_name=%s", (name,)
            ).fetchall()
            if rows and (
                not active or (rows[0]["state"] == "active" and "pg_sleep" in rows[0]["query"])
            ):
                return rows[0]
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("cancel_count", [1, 2])
def test_actual_driver_cancels_owned_query_and_drains_without_touching_writer(
    pg_store, monkeypatch, tmp_path, cancel_count
):
    import trading.tiered_runtime as runtime_module

    if not psycopg.capabilities.has_cancel_safe():
        pytest.skip("Bounded cancel_safe requires libpq 17+; fallback is covered separately")
    store, _ = pg_store
    before = store.read(), store.export(0, 1000)
    name = "readback_cancel_" + uuid.uuid4().hex
    view = FinancialReadback(store)
    view._dsn = make_conninfo(view._dsn, application_name=name)
    reader = ReadbackWorker(view)
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    monkeypatch.setattr(worker_module, "readback_child", blocked_database_child)
    monkeypatch.setattr(runtime_module, "ReadbackWorker", lambda _: reader)

    async def scenario():
        task = asyncio.create_task(runtime._financial_readback_loop())
        try:
            row = await wait_for_backend(store, name, active=True)
            assert row["pid"] != store.connection.info.backend_pid
            assert "pg_sleep" in row["query"]
            started = time.monotonic()
            task.cancel()
            if cancel_count == 2:
                await asyncio.sleep(0.01)
                task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 6)
            assert time.monotonic() - started < 5.5
            assert runtime._readback_shutdown["status"] == "drained"
            assert reader._process is None
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await reader.close()

    asyncio.run(scenario())
    assert (store.read(), store.export(0, 1000)) == before
    store.transact(START + 1, lambda engine: None)
    assert store.reconcile()["balanced"]


@pytest.mark.parametrize("fault", ["shutdown", "operation_deadline"])
def test_stuck_client_is_bounded_without_closing_a_live_thread_or_abandoning_reader(
    pg_store, monkeypatch, fault
):
    store, _ = pg_store
    before = store.read(), store.export(0, 1000)
    name = "readback_stuck_" + uuid.uuid4().hex
    view = FinancialReadback(store)
    view._dsn = make_conninfo(view._dsn, application_name=name)
    reader = ReadbackWorker(view)
    monkeypatch.setattr(worker_module, "readback_child", blocked_client_child)
    if fault == "operation_deadline":
        monkeypatch.setattr(worker_module, "SAMPLE_SECONDS", 2)

    async def scenario():
        audits = []

        async def query():
            try:
                return await reader.sample(audit=True, publish_audit=audits.append)
            finally:
                await reader.close()

        task = asyncio.create_task(query())
        try:
            await wait_for_backend(store, name)
            started = time.monotonic()
            if fault == "shutdown":
                task.cancel()
                await asyncio.sleep(0.02)
                task.cancel()
                expected = asyncio.CancelledError
            else:
                expected = TimeoutError
            with pytest.raises(expected):
                await asyncio.wait_for(task, 8)
            assert time.monotonic() - started < 7.5
            assert reader.last_shutdown["status"] == "terminated_owned_reader"
            assert audits == []  # An unfinished reconciliation never publishes a passing audit.
            assert reader._process is None
            async with asyncio.timeout(3):
                while store.connection.execute(
                    "SELECT 1 FROM pg_stat_activity WHERE application_name=%s", (name,)
                ).fetchone():
                    await asyncio.sleep(0.01)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError, TimeoutError):
                await task
            await reader.close()

    asyncio.run(scenario())
    assert (store.read(), store.export(0, 1000)) == before


def test_completed_audit_is_delivered_even_when_optional_history_exceeds_ipc_budget(pg_store):
    store, _ = pg_store
    store.transact(
        START,
        lambda e: e.emit(
            "synthetic_oversized_history",
            "primary",
            {"text": "x" * worker_module.MAX_RECEIPT_BYTES},
        ),
    )
    before = store.read(), store.export(0, 1000)
    reader = ReadbackWorker(FinancialReadback(store))

    async def scenario():
        audits = []
        try:
            with pytest.raises(OSError, match="monitoring query unavailable"):
                await reader.sample(audit=True, publish_audit=audits.append)
            assert len(audits) == 1 and audits[0]["reconciliation"]["balanced"] is True
            assert audits[0]["reconciliation"]["revision"] == before[0]["revision"]
        finally:
            assert (await reader.close())["status"] == "drained"

    asyncio.run(scenario())
    assert (store.read(), store.export(0, 1000)) == before


def test_restart_of_owned_reader_preserves_financial_history_and_audit_identity(pg_store):
    store, _ = pg_store
    reader = ReadbackWorker(FinancialReadback(store))
    before = store.read(), store.export(0, 1000)

    async def scenario():
        audits = []
        for _ in range(2):
            result = await reader.sample(audit=True, publish_audit=audits.append)
            assert result["reconciliation"]["balanced"]
            assert (await reader.close())["status"] == "drained"
        assert len(audits) == 2
        assert all(a["reconciliation"]["revision"] == before[0]["revision"] for a in audits)

    asyncio.run(scenario())
    assert (store.read(), store.export(0, 1000)) == before
