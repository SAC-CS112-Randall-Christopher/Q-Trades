"""Actual-driver metadata transitions, sole-writer exclusion and complete preservation."""

import json
import socket

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

from trading.paper_projection import configure_projection_compression
from trading.paper_store import PaperStore


def saved(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return {
            "projection": connection.execute(
                "SELECT id,revision,body::text AS body,pg_column_compression(body) AS stored "
                "FROM paper_state"
            ).fetchall(),
            "events": connection.execute("SELECT * FROM paper_events ORDER BY id").fetchall(),
            "journal": connection.execute(
                "SELECT * FROM paper_journal ORDER BY event_id,line_no"
            ).fetchall(),
            "compression": connection.execute(
                "SELECT attcompression FROM pg_attribute "
                "WHERE attrelid='paper_state'::regclass AND attname='body'"
            ).fetchone()["attcompression"],
        }


def test_readonly_preview_while_writer_runs_preserves_complete_database(pg_store):
    store, dsn = pg_store
    before = saved(dsn)
    report = configure_projection_compression(dsn, target="lz4", expected="default")
    assert report["mode"] == "preview" and report["previous_compression"] == "default"
    assert report["projection"]["revision"] == store.read()["revision"]
    assert report["financial_rows_rewritten"] is False
    assert saved(dsn) == before


def test_apply_refuses_existing_financial_owner_and_leaves_no_mutation(pg_store):
    _, dsn = pg_store
    before = saved(dsn)
    with pytest.raises(RuntimeError, match="financial writer is active"):
        configure_projection_compression(dsn, target="lz4", expected="default", apply=True)
    assert saved(dsn) == before


def test_opt_in_future_write_exact_projection_journal_and_rollback_setting(pg_store):
    store, dsn = pg_store
    payload = [{"id": i, "nested": {"float": -0.0, "large": 1.23e20}, "text": "λ" * 40}
               for i in range(3000)]
    store.transact(START, lambda engine: engine.state.update(compression_fixture=payload))
    before = saved(dsn)
    assert before["projection"][0]["stored"] == "pglz"
    original = store.read()
    store.close()
    report = configure_projection_compression(dsn, target="lz4", expected="default", apply=True)
    after = saved(dsn)
    assert report["mode"] == "applied" and report["projection"]["revision"] == original["revision"]
    assert after == {**before, "compression": "l"}  # Metadata only; not even a row rewrite.
    with pytest.raises(RuntimeError, match="reviewed expectation"):
        configure_projection_compression(dsn, target="lz4", expected="default", apply=True)
    assert saved(dsn) == after
    reopened = PaperStore(dsn, owner=True)
    try:
        state = reopened.transact(START + 1, lambda engine: None)
        stored = saved(dsn)
        assert stored["projection"][0]["stored"] == "lz4"
        assert state == {key: value for key, value in original.items() if key != "revision"}
        assert json.loads(stored["projection"][0]["body"]) == state
        assert stored["events"] == before["events"] and stored["journal"] == before["journal"]
        assert reopened.reconcile()["balanced"]
    finally:
        reopened.close()
    configure_projection_compression(dsn, target="default", expected="lz4", apply=True)
    assert saved(dsn) == {**stored, "compression": ""}


@pytest.mark.parametrize("bad_version", ["1", 2, None])
def test_invalid_financial_projection_is_refused_without_changing_metadata(pg_store, bad_version):
    store, dsn = pg_store
    store.connection.execute(
        "UPDATE paper_state SET body=jsonb_set(body,'{schema}',%s::jsonb) WHERE id=1",
        (json.dumps(bad_version),),
    )
    before = saved(dsn)
    store.close()
    with pytest.raises(RuntimeError, match="initialized financial projection"):
        configure_projection_compression(dsn, target="lz4", expected="default", apply=True)
    assert saved(dsn) == before


def test_reader_table_lock_timeout_rolls_back_and_releases_writer_lease(pg_store):
    store, dsn = pg_store
    before = saved(dsn)
    store.close()
    with psycopg.connect(dsn) as reader:
        reader.execute("SELECT body FROM paper_state WHERE id=1")
        with pytest.raises(RuntimeError, match="database operation failed"):
            configure_projection_compression(dsn, target="lz4", expected="default", apply=True)
    assert saved(dsn) == before
    reopened = PaperStore(dsn, owner=True)
    reopened.close()  # Failed metadata operation did not leak its advisory lease.
    configure_projection_compression(dsn, target="lz4", expected="default", apply=True)
    assert saved(dsn) == {**before, "compression": "l"}


@pytest.mark.parametrize("target,expected", [("lz4; DROP TABLE paper_state", "default"),
                                             ("lz4", "other")])
def test_nonallowlisted_method_is_rejected_before_connect(target, expected, monkeypatch):
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: pytest.fail("Must not connect"))
    with pytest.raises(ValueError, match="Supported projection compression"):
        configure_projection_compression(
            "not a database", target=target, expected=expected, apply=True
        )


def test_actual_connection_error_does_not_expose_credentials(pg_store):
    _, dsn = pg_store
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        failed = make_conninfo(dsn, port=unavailable.getsockname()[1], password="private-marker")
        with pytest.raises(RuntimeError, match="database operation failed") as error:
            configure_projection_compression(failed, target="lz4", expected="default")
    assert "private-marker" not in str(error.value)


def test_preservation_failure_rolls_back_actual_metadata_transition(pg_store, monkeypatch):
    import trading.paper_projection as module

    store, dsn = pg_store
    before = saved(dsn)
    store.close()
    original = module._projection
    reads = []

    def changed(connection, schema):
        row = original(connection, schema)
        reads.append(row)
        if len(reads) == 2:
            row["projection_sha256"] = "different"
        return row

    monkeypatch.setattr(module, "_projection", changed)
    with pytest.raises(RuntimeError, match="preservation failed"):
        configure_projection_compression(dsn, target="lz4", expected="default", apply=True)
    assert len(reads) == 2 and saved(dsn) == before
