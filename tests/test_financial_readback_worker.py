"""Owned-child faults, actual libpq cancellation and bounded Windows/POSIX shutdown."""

import asyncio
import copy
import time
import uuid
from contextlib import suppress
from threading import Event

import psycopg
import pytest
from financial_monitoring_fixture import FinancialMonitoringFixture
from psycopg.conninfo import make_conninfo
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

import trading.financial_readback_worker as worker_module
from trading.financial_readback import FinancialReadback
from trading.financial_readback_worker import ReadbackWorker, readback_child
from trading.paper_store import PaperStore
from trading.tiered_runtime import TieredPaperRuntime


@pytest.mark.parametrize("ancillary", ["recent", "storage_usage"])
def test_retry_audit_keeps_known_optional_failure_unavailable_until_real_recovery(
    pg_store, tmp_path, ancillary
):
    """R63-1: a new real audit cannot clear a prior optional-query failure."""
    from trading.research_notices import operational_conditions

    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.disk_free = 10 * 1024**3
    runtime.running = True
    runtime.state["last_tick"] = time.time()
    fixture = FinancialMonitoringFixture(runtime)

    async def scenario():
        await fixture.start()
        try:
            await fixture.wait_sample()
            assert runtime.journal_status()["status"] == "balanced"
            retained_history = copy.deepcopy(runtime.recent)
            assert retained_history, "Retention proof requires real persisted history"
            retained_storage = dict(runtime.database_usage)
            first_completed = fixture.completed_at
            fixture.fail(ancillary)
            if ancillary == "storage_usage":
                fixture.make_audit_due()  # Synthetic schedule; next actual query owns the result.
            await fixture.wait_sample(first_completed)
            assert runtime.journal_status()["status"] == "unavailable"
            previous_audit = fixture.audit_at
            failed_completed = fixture.completed_at
            store.transact(START + 1, lambda engine: None)
            before = store.read(), store.export(0, 1000)
            fixture.hold(ancillary)
            await fixture.wait_held(ancillary)
            await fixture.wait_audit(previous_audit)

            # The completed audit is new; the failing refresh has not completed.
            assert runtime.receipts["balanced"] is True
            assert runtime.receipts["revision"] == before[0]["revision"]
            assert runtime.receipts["checked_at"] > previous_audit
            assert fixture.completed_at == failed_completed
            assert runtime.recent == retained_history
            assert runtime.database_usage == retained_storage
            journal = runtime.journal_status()
            snapshot = runtime.snapshot()
            notice = next(
                row for row in operational_conditions(runtime, time.time())
                if row["key"] == "financial_monitoring"
            )
            assert journal["status"] == "unavailable", (
                "R63-1: a retry audit falsely reopened monitoring while the known "
                f"{ancillary} failure is still held; actual owner state: {fixture.snapshot()}"
            )
            assert journal["available"] is False and journal["balanced"] is True
            assert all(
                snapshot["journal"][key] == journal[key]
                for key in ("status", "available", "balanced", "checked_at", "revision", "error")
            )
            assert snapshot["performance"]["financial_readback"]["available"] is False
            assert "financial_readback_unavailable" in (
                snapshot["performance"]["resource_guard"]["blocking_conditions"]
            )
            assert runtime.readback_unavailable() and runtime.constrained()
            assert notice["condition"] == "unknown"
            assert notice["facts"]["status"] == "unavailable"
            assert runtime._financial_failure is None and runtime.error is None

            fixture.release(ancillary)  # The retry fails again after its actual audit.
            await fixture.wait_sample(failed_completed)
            assert runtime.journal_status()["status"] == "unavailable"
            repeated_completed = fixture.completed_at
            fixture.recover(ancillary)
            await fixture.wait_sample(repeated_completed)
            assert runtime.journal_status()["status"] == "balanced"
            assert not runtime.readback_unavailable() and not runtime.constrained()
            assert runtime._financial_failure is None and runtime.error is None
            assert (store.read(), store.export(0, 1000)) == before
        finally:
            await fixture.stop()
            assert fixture.reader._process is None

    asyncio.run(scenario())


@pytest.mark.parametrize("recovered", ["recent", "storage_usage"])
def test_recovery_of_one_optional_query_keeps_the_other_failure_outstanding(
    pg_store, tmp_path, recovered
):
    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.disk_free = 10 * 1024**3
    fixture = FinancialMonitoringFixture(runtime)
    remaining = "storage_usage" if recovered == "recent" else "recent"

    async def scenario():
        await fixture.start()
        try:
            await fixture.wait_sample()
            completed = fixture.completed_at
            fixture.fail("recent", "storage_usage")
            fixture.make_audit_due()
            await fixture.wait_sample(completed)
            assert set(runtime._readback_sample["refresh_errors"]) == {
                "recent", "storage_usage"
            }
            completed = fixture.completed_at
            fixture.recover(recovered)
            await fixture.wait_sample(completed)
            assert set(runtime._readback_sample["refresh_errors"]) == {remaining}
            assert runtime.journal_status()["status"] == "unavailable"
            previous_audit = fixture.audit_at
            completed = fixture.completed_at
            fixture.hold(remaining)
            await fixture.wait_held(remaining)
            await fixture.wait_audit(previous_audit)
            assert runtime.journal_status()["status"] == "unavailable"
            assert runtime.constrained() and runtime._financial_failure is None
            fixture.recover(remaining)
            fixture.release(remaining)
            await fixture.wait_sample(completed)
            assert runtime._readback_sample["refresh_errors"] == {}
            assert runtime.journal_status()["status"] == "balanced"
            assert not runtime.constrained()
        finally:
            await fixture.stop()

    asyncio.run(scenario())


def test_healthy_optional_refresh_in_flight_keeps_current_monitoring_available(pg_store, tmp_path):
    store, _ = pg_store
    before = store.read(), store.export(0, 1000)
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.disk_free = 10 * 1024**3
    fixture = FinancialMonitoringFixture(runtime)

    async def scenario():
        await fixture.start()
        try:
            await fixture.wait_sample()
            audit = dict(runtime.receipts)
            completed = fixture.completed_at
            fixture.hold("recent")
            await fixture.wait_held("recent")
            assert fixture.completed_at == completed
            assert runtime.receipts == audit
            assert runtime.journal_status()["status"] == "balanced"
            assert runtime.journal_status()["available"] is True
            assert not runtime.readback_unavailable() and not runtime.constrained()
            fixture.release("recent")
            await fixture.wait_sample(completed)
            assert runtime.journal_status()["status"] == "balanced"
            assert (store.read(), store.export(0, 1000)) == before
        finally:
            await fixture.stop()

    asyncio.run(scenario())


def test_optional_retry_timeout_retains_new_audit_and_recovers_without_restart(pg_store, tmp_path):
    """Use the actual 15-second operation policy after a completed retry audit."""
    store, _ = pg_store
    before = store.read(), store.export(0, 1000)
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.disk_free = 10 * 1024**3
    fixture = FinancialMonitoringFixture(runtime)

    async def scenario():
        await fixture.start()
        try:
            await fixture.wait_sample()
            completed = fixture.completed_at
            fixture.fail("recent")
            await fixture.wait_sample(completed)
            completed, previous_audit = fixture.completed_at, fixture.audit_at
            fixture.hold("recent")
            await fixture.wait_held("recent")
            await fixture.wait_audit(previous_audit)
            audit = dict(runtime.receipts)
            assert runtime.journal_status()["status"] == "unavailable"
            assert runtime.constrained()
            async with asyncio.timeout(
                worker_module.SAMPLE_SECONDS + worker_module.DRAIN_SECONDS
                + worker_module.TERMINATE_SECONDS + 3
            ):
                while (
                    runtime._readback_error != "Financial readback operation deadline exceeded"
                    or runtime._readback_shutdown is None
                ):
                    await asyncio.sleep(0.01)
            assert runtime._readback_shutdown["status"] == "terminated_owned_reader"
            assert fixture.reader._process is None
            assert runtime.receipts == audit
            assert fixture.completed_at == completed
            assert runtime.journal_status()["status"] == "unavailable"
            assert runtime._financial_failure is None and runtime.error is None
            fixture.recover("recent")
            fixture.release("recent")
            await fixture.wait_sample(completed)
            assert runtime.journal_status()["status"] == "balanced"
            assert not runtime.constrained()
            assert fixture.reader._process is not None and fixture.reader._process.is_alive()
            assert (store.read(), store.export(0, 1000)) == before
        finally:
            await fixture.stop()
            assert fixture.reader._process is None

    asyncio.run(scenario())


def test_reader_restart_retains_optional_failure_until_its_real_query_recovers(pg_store, tmp_path):
    store, _ = pg_store
    before = store.read(), store.export(0, 1000)
    runtime = TieredPaperRuntime(store, None, tmp_path / "capture.sqlite")
    runtime.disk_free = 10 * 1024**3
    first = FinancialMonitoringFixture(runtime)

    async def scenario():
        await first.start()
        try:
            await first.wait_sample()
            completed = first.completed_at
            first.fail("recent")
            await first.wait_sample(completed)
            retained_history = copy.deepcopy(runtime.recent)
            previous_audit = first.audit_at
            completed = first.completed_at
        finally:
            await first.stop()
        assert first.reader._process is None
        assert runtime.journal_status()["status"] == "unavailable"
        second = FinancialMonitoringFixture(runtime)
        second.hold("recent")
        await second.start()
        try:
            await second.wait_held("recent")
            await second.wait_audit(previous_audit)
            assert second.completed_at == completed
            assert runtime.recent == retained_history
            assert runtime.journal_status()["status"] == "unavailable"
            assert runtime.constrained() and runtime._financial_failure is None
            second.release("recent")
            await second.wait_sample(completed)
            assert runtime.journal_status()["status"] == "balanced"
            assert not runtime.constrained()
            assert (store.read(), store.export(0, 1000)) == before
        finally:
            await second.stop()
            assert second.reader._process is None

    asyncio.run(scenario())


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
