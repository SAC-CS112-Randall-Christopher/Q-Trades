"""Diagnostic HTTP workers retain the sole writer's full transaction boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

from trading.paper_diagnostics import create_diagnostic
from trading.paper_runtime import PaperRuntime


def test_commit_and_cache_publication_cannot_be_overtaken(pg_store, monkeypatch):
    store, _ = pg_store
    runtime = PaperRuntime(store, None)
    runtime.running = True
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    committed, release, writer_entered, reader_entered = (Event() for _ in range(4))
    original = store.transact

    def delay_publication(now, work):
        result = original(now, work)
        if not committed.is_set():
            committed.set()
            assert release.wait(5)
        return result

    def write_later():
        writer_entered.set()
        runtime.set_paused(True)

    def read_later():
        reader_entered.set()
        return store.export(0, 1000)

    monkeypatch.setattr(store, "transact", delay_publication)
    with ThreadPoolExecutor(max_workers=3) as pool:
        create = pool.submit(runtime.diagnostic_create, "thread-create-0001")
        assert committed.wait(5)
        write = pool.submit(write_later)
        read = pool.submit(read_later)
        try:
            assert writer_entered.wait(5) and reader_entered.wait(5)
            assert not write.done() and not read.done()
        finally:
            release.set()
        assert create.result(timeout=5)["status"] == "created"
        write.result(timeout=5)
        records = read.result(timeout=5)["records"]
    assert runtime.state["paused"] is True
    assert runtime.state["accounts"] == store.read()["accounts"]
    assert sum(e["kind"] == "performance_diagnostic_funded" for e in records) == 1
    assert store.reconcile()["balanced"]


def test_reader_does_not_observe_rolled_back_diagnostic_transaction(pg_store):
    store, _ = pg_store
    inside, release, reader_entered = Event(), Event(), Event()
    prefix = store.export(0, 1000)

    def fail(engine):
        create_diagnostic(engine, "thread-rollback-0001")
        # Insert inside the real owned transaction, then force rollback.
        store._append(engine, 1)
        inside.set()
        assert release.wait(5)
        raise ValueError("Synthetic transaction failure")

    def read():
        reader_entered.set()
        return store.export(0, 1000)

    with ThreadPoolExecutor(max_workers=2) as pool:
        write = pool.submit(store.transact, START, fail)
        assert inside.wait(5)
        view = pool.submit(read)
        try:
            assert reader_entered.wait(5)
            assert not view.done()
        finally:
            release.set()
        with pytest.raises(ValueError, match="Synthetic transaction failure"):
            write.result(timeout=5)
        assert view.result(timeout=5) == prefix
    assert store.reconcile()["balanced"]
