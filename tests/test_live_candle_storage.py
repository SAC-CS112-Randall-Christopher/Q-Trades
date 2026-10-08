"""Matched disposable writer/read coexistence and existing-owner reuse."""

import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from test_candle_history import study
from test_research_storage import plan_at

from trading.candle_history import reopen_history, retain_history
from trading.evidence_runtime import EvidenceRecorder
from trading.research_storage import ResearchStorage, save_plan
from trading.tool_journal import ToolJournal


def test_reopen_is_read_only_while_existing_segment_writer_holds_lock(tmp_path):
    plan = plan_at(tmp_path)
    journal = ToolJournal(tmp_path / "tools.sqlite", plan)
    analysis, raw = study()
    identifier = journal.start(
        "candle_patterns", "BTCUSD", query={"timeframe": "5m", "window": "recent"}
    )
    journal.finish(
        identifier, retain_history(plan, journal.namespace, identifier, analysis, raw), None
    )
    receipt = journal.get(identifier)
    original = copy.deepcopy(receipt)
    live = ResearchStorage(plan)
    try:
        segments = [tuple(row) for row in live.db.execute("SELECT * FROM storage_segments")]
        with live._exclusive():
            # Matched original behavior: recovery initialization cannot acquire
            # another capture lock while this live writer owns it.
            with pytest.raises(OSError, match="another storage writer"):
                ResearchStorage(plan)
            # Same saved inputs; the repaired GET does not acquire a write lock.
            reopen_history(plan, journal.namespace, receipt)
        assert receipt["candle_analysis"] == analysis
        assert {
            key: value for key, value in receipt.items() if key != "candle_analysis"
        } == original
        assert [tuple(row) for row in live.db.execute("SELECT * FROM storage_segments")] == segments
    finally:
        live.close()
        journal.close()


def test_tools_borrow_initialized_recorder_without_recovery_or_closing_it(tmp_path, monkeypatch):
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    recorder = EvidenceRecorder(tmp_path / "evidence.sqlite")
    journal = ToolJournal(tmp_path / "tools.sqlite", plan)
    asyncio.run(recorder.flush())
    assert recorder._storage is not None
    owner = recorder._storage
    journal.storage_owner = recorder.research_store
    analysis, raw = study()
    # No optional tool operation may initialize/reconcile another writer.
    monkeypatch.setattr(
        ResearchStorage, "_initialize", lambda self: pytest.fail("Repeated recovery")
    )
    identifier = journal.start(
        "candle_patterns",
        "BTCUSD",
        request_id="owned-candles-123",
        query={"timeframe": "5m", "window": "recent"},
    )
    result = retain_history(
        plan,
        journal.namespace,
        identifier,
        analysis,
        raw,
        storage_owner=recorder.research_store,
    )
    journal.finish(identifier, result, None)
    assert journal.find_request("owned-candles-123")["status"] == "completed"
    assert journal.recent()["total"] == 1
    saved = journal.get(identifier)
    reopen_history(plan, journal.namespace, saved)
    assert saved["candle_analysis"] == analysis
    asyncio.run(recorder.flush())
    assert recorder.status["state"] == "recording"
    assert recorder._storage is owner
    journal.close()
    recorder.close()


def test_borrow_serializes_against_capture_and_rejects_identity_or_closed_owner(tmp_path):
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    recorder = EvidenceRecorder(tmp_path / "evidence.sqlite")
    asyncio.run(recorder.flush())
    entered, completed = Event(), Event()

    def capture():
        entered.set()
        recorder._write_batch([], [], True)
        completed.set()

    with ThreadPoolExecutor(max_workers=1) as workers:
        with recorder.research_store(plan) as owner:
            future = workers.submit(capture)
            assert entered.wait(2)
            assert not completed.wait(0.05)
            assert owner is recorder._storage
        future.result(timeout=5)
    assert completed.is_set()
    with pytest.raises(ValueError, match="identity differs"):
        with recorder.research_store(plan.model_copy(update={"temporary_bytes": 1})):
            pytest.fail("Wrong plan admitted")
    recorder.close()
    with pytest.raises(OSError, match="not ready"):
        with recorder.research_store(plan):
            pytest.fail("Closed writer admitted")


def test_unready_recorder_does_not_start_an_optional_writer(tmp_path):
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    recorder = EvidenceRecorder(tmp_path / "evidence.sqlite")
    with pytest.raises(OSError, match="no alternate writer"):
        with recorder.research_store(plan):
            pytest.fail("Unready writer admitted")
    assert not Path(plan.root).exists()


def test_shutdown_waits_for_borrow_without_blocking_independent_async_work(tmp_path):
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    recorder = EvidenceRecorder(tmp_path / "evidence.sqlite")
    entered, release = Event(), Event()

    def borrow():
        with recorder.research_store(plan):
            entered.set()
            assert release.wait(3), "Shutdown blocked the event loop"

    async def run():
        service = asyncio.create_task(recorder.run(lambda: True))
        for _ in range(100):
            if recorder._storage is not None:
                break
            await asyncio.sleep(0.01)
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(borrow)
            assert await asyncio.to_thread(entered.wait, 2)
            service.cancel()
            # Independent financial cleanup remains able to run while the
            # existing off-thread close is waiting on an optional borrower.
            await asyncio.sleep(0.1)
            assert not service.done()
            assert not recorder._closed
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(service, 2)
            future.result(timeout=2)
        assert recorder._closed

    try:
        asyncio.run(run())
    finally:
        release.set()
