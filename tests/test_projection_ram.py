"""Native PostgreSQL cache/authority regressions; no operating data or model calls."""

import hashlib
import json
from contextlib import contextmanager

import psycopg
import pytest
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

from trading.paper_store import PaperStore


def test_ram_read_preserves_postgresql_numeric_representation_and_capture(pg_store):
    store, _ = pg_store
    store.transact(START, lambda e: e.state.update(
        numeric_metadata=[-0.0, 1.23e20, -1e21, 1e-20, 1.0, 0.0]
    ))
    authoritative = store.read()
    authoritative.pop("revision")
    state, receipt = store.transact_with_receipt(
        START + 1, lambda e: None, capture_projection=True
    )
    assert json.dumps(state, sort_keys=True) == json.dumps(authoritative, sort_keys=True)
    assert receipt["projection_sha256"] == hashlib.sha256(
        json.dumps(authoritative, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_committed_ram_copy_is_detached_and_original_capture_digest_survives(pg_store):
    store, _ = pg_store
    state, first = store.transact_with_receipt(START, lambda e: None, capture_projection=True)
    state["accounts"]["primary"]["cash"] = "1"
    state["caller_only"] = True
    second, receipt = store.transact_with_receipt(
        START + 1, lambda e: None, capture_projection=True
    )
    assert second["accounts"]["primary"]["cash"] == "100"
    assert "caller_only" not in second
    assert first["projection_sha256"] == receipt["projection_sha256"]
    assert store.projection_cache_info()["hits"] == 1
    assert store.read()["accounts"] == second["accounts"]
    assert store.reconcile()["balanced"]


def test_failure_discards_cache_and_retains_the_last_committed_financial_state(pg_store):
    store, _ = pg_store
    store.transact(START, lambda e: None)
    before, events = store.read(), store.export(0, 1000)

    def fail(engine):
        engine.state["accounts"]["primary"]["cash"] = "1"
        engine.emit("uncommitted_probe", "primary", {})
        raise RuntimeError("Interrupted financial work")

    with pytest.raises(RuntimeError, match="Interrupted"):
        store.transact(START + 1, fail)
    assert store.projection_cache_info()["cached_bytes"] == 0
    assert store.last_commit_receipt is None
    assert store.read() == before and store.export(0, 1000) == events
    after = store.transact(START + 2, lambda e: None)
    assert after["accounts"] == before["accounts"] and store.reconcile()["balanced"]


@pytest.mark.parametrize("corrupt", [False, True])
def test_same_revision_external_change_is_detected_before_using_ram(pg_store, corrupt):
    store, dsn = pg_store
    store.transact(START, lambda e: None)
    # Deliberate disposable-database integrity probe: normal readers never write.
    with psycopg.connect(dsn, autocommit=True) as probe:
        probe.execute(
            "UPDATE paper_state SET body=jsonb_set(body,%s,%s::jsonb) WHERE id=1",
            (["schema"] if corrupt else ["external_marker"], "99" if corrupt else '"observed"'),
        )
    if corrupt:
        with pytest.raises(RuntimeError, match="Unsupported paper state"):
            store.transact(START + 1, lambda e: None)
        assert store.projection_cache_info()["cached_bytes"] == 0
    else:
        state = store.transact(START + 1, lambda e: None)
        assert state["external_marker"] == "observed"
        assert store.reconcile()["balanced"]
    assert store.projection_cache_info()["hits"] == 0


def test_outer_rollback_cannot_publish_a_savepoint_state_to_ram(pg_store):
    store, _ = pg_store
    store.transact(START, lambda e: e.state.update(marker="committed"))
    with pytest.raises(RuntimeError, match="Outer rollback"):
        with store.connection.transaction():
            store.transact(START + 1, lambda e: e.state.update(marker="rolled back"))
            assert store.projection_cache_info()["cached_bytes"] == 0
            raise RuntimeError("Outer rollback")
    state = store.transact(START + 2, lambda e: None)
    assert state["marker"] == "committed" and store.reconcile()["balanced"]


def test_unknown_commit_acknowledgment_forces_authoritative_reload(pg_store, monkeypatch):
    store, _ = pg_store
    store.transact(START, lambda e: e.state.update(marker="before"))
    original = store.connection.transaction

    @contextmanager
    def lost_acknowledgment(*args, **kwargs):
        with original(*args, **kwargs):
            yield
        raise OSError("Committed but acknowledgment unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(store.connection, "transaction", lost_acknowledgment)
        with pytest.raises(OSError, match="acknowledgment"):
            store.transact(START + 1, lambda e: e.state.update(marker="actually committed"))
    assert store.projection_cache_info()["cached_bytes"] == 0
    assert store.last_commit_receipt is None
    state = store.transact(START + 2, lambda e: None)
    assert state["marker"] == "actually committed" and store.reconcile()["balanced"]


@pytest.mark.parametrize("budget", [0, 1, 8 * 1024**2])
def test_cache_budget_and_restart_preserve_database_and_reader_authority(pg_store, budget):
    store, dsn = pg_store
    store.transact(START, lambda e: e.state.update(marker="before restart"))
    store.close()
    reopened = PaperStore(dsn, owner=True, projection_cache_bytes=budget)
    try:
        assert reopened.projection_cache_info()["cached_bytes"] == 0
        reopened.transact(START + 1, lambda e: None)
        state = reopened.transact(START + 2, lambda e: None)
        info = reopened.projection_cache_info()
        assert state["marker"] == "before restart" and info["cached_bytes"] <= budget
        assert info["hits"] == (1 if budget > 1 else 0)
        assert reopened.reconcile()["balanced"]
        with pytest.raises(RuntimeError, match="Another paper engine"):
            PaperStore(dsn, owner=True)
        reader = PaperStore(dsn)
        try:
            assert not reader.projection_cache_info()["enabled"]
            assert reader.read()["accounts"] == state["accounts"]
            with pytest.raises(RuntimeError, match="exclusive engine writer"):
                reader.transact(START + 3, lambda e: None)
        finally:
            reader.close()
    finally:
        reopened.close()
