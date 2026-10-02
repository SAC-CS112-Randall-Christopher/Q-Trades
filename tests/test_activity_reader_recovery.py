"""Authenticated activity polling and actual shared-writer/candle concurrency."""

import asyncio
import copy
import socket
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

from trading.api import create_app
from trading.config import Settings
from trading.paper_runtime import PaperRuntime
from trading.research_activity import ResearchActivity
from trading.tiered_runtime import TieredPaperRuntime


@pytest.mark.parametrize("password", ["synthetic-only", "synthetic ' quote \\ space"])
def test_activity_api_preserves_private_authentication_options_and_evidence_dates(
    password, monkeypatch, tmp_path
):
    import trading.research_activity as activity_module

    queries = []

    class Activity:
        def __init__(self, directory):
            pass

        def snapshot(self, dsn, runtime, lab):
            parameters = conninfo_to_dict(dsn)
            assert parameters["password"] == password
            assert parameters["options"] == "-c search_path=activity_case"
            assert parameters["connect_timeout"] == "3"
            queries.append(parameters)
            return {"queried_at": START + 100, "signal": {"at": START}, "warnings": []}

    monkeypatch.setattr(activity_module, "ResearchActivity", Activity)
    info = SimpleNamespace(
        dsn="host=127.0.0.1 dbname=synthetic user=fixture options='-c search_path=activity_case'",
        password=password,
    )
    runtime = SimpleNamespace(store=SimpleNamespace(connection=SimpleNamespace(info=info)))
    with TestClient(create_app(Settings(), tmp_path / "monitor", background=False)) as client:
        client.app.state.paper = runtime
        response = client.get("/api/research/activity")
    assert response.status_code == 200 and len(queries) == 1
    assert response.json()["signal"]["at"] < response.json()["queried_at"]
    assert password not in response.text


def test_activity_endpoint_recovers_after_real_connection_outage_without_restart(
    pg_store, monkeypatch, tmp_path
):
    import trading.research_activity as activity_module

    store, _ = pg_store
    store.transact(START, lambda engine: engine.emit("decision", "primary", {}))
    runtime = PaperRuntime(store, None)
    activity = ResearchActivity(tmp_path)
    monkeypatch.setattr(activity_module, "ResearchActivity", lambda directory: activity)
    polling_clock = [1000.0]
    monkeypatch.setattr(
        activity_module,
        "time",
        SimpleNamespace(monotonic=lambda: polling_clock[0], time=time.time),
    )
    before = store.read(), store.export(0, 1000)
    with (
        socket.socket() as unavailable,
        TestClient(create_app(Settings(), tmp_path / "monitor", background=False)) as client,
    ):
        unavailable.bind(("127.0.0.1", 0))
        # Owned but non-listening port; use the actual driver to observe refusal.
        info = SimpleNamespace(
            dsn=make_conninfo(store.connection.info.dsn, port=unavailable.getsockname()[1]),
            password=store.connection.info.password,
        )
        runtime.store = SimpleNamespace(connection=SimpleNamespace(info=info))
        client.app.state.paper = runtime
        failed = client.get("/api/research/activity").json()
        assert "Durable financial activity query unavailable" in failed["warnings"]
        assert failed["signal"] is None
        runtime.store = store
        polling_clock[0] += 1
        assert client.get("/api/research/activity").json() == failed
        polling_clock[0] += 10  # Expire the normal polling cache; no service restart.
        restored = client.get("/api/research/activity").json()
        assert "Durable financial activity query unavailable" not in restored["warnings"]
        assert restored["signal"]["at"] == START
        assert restored["queried_at"] != START
        assert restored["completed_learning"] is None
    assert before == (store.read(), store.export(0, 1000))
    assert store.reconcile()["balanced"]


def test_candle_commit_and_financial_commit_do_not_share_nested_transactions(pg_store, monkeypatch):
    store, _ = pg_store
    accounts_before = copy.deepcopy(store.read()["accounts"])
    writer_entered, release_writer, candle_entered, release_candle = [Event() for _ in range(4)]
    execute = store.connection.execute

    def observed_execute(query, *args, **kwargs):
        cursor = execute(query, *args, **kwargs)
        if isinstance(query, str) and query.startswith("INSERT INTO paper_bars"):
            candle_entered.set()
            assert release_candle.wait(3), "Candle observation did not complete"
        return cursor

    monkeypatch.setattr(store.connection, "execute", observed_execute)

    def financial_work(engine):
        engine.emit("concurrency_observation", "primary", {"source": "synthetic"})
        writer_entered.set()
        assert release_writer.wait(3), "Writer observation did not complete"

    raw = [[60000, "100", "101", "99", "100", "10", 119999]]
    with ThreadPoolExecutor(max_workers=2) as workers:
        writer = workers.submit(store.transact, START + 1, financial_work)
        assert writer_entered.wait(2)
        candle = workers.submit(store.bars, "BTCUSD", raw, START + 1, False)
        # The SQL pause makes an overlapping native driver transaction observable.
        # After correction, the candle reaches SQL only after the writer commits.
        candle_entered.wait(0.2)
        release_writer.set()
        try:
            writer.result(timeout=2)
        finally:
            release_candle.set()
        assert candle.result(timeout=2) == 1
    assert store.reconcile()["balanced"]
    records = store.export(0, 1000)["records"]
    assert sum(r["kind"] == "concurrency_observation" for r in records) == 1
    row = store.connection.execute("SELECT count(*) AS n FROM paper_bars").fetchone()
    assert row["n"] == 1
    assert store.connection.info.transaction_status.name == "IDLE"
    assert store.read()["accounts"] == accounts_before


def test_transaction_diagnostics_separate_work_serialization_and_commit(pg_store):
    store, _ = pg_store
    store.transact(START + 1, lambda engine: engine.emit("measurement_fixture", "primary", {}))
    diagnostics = store.last_transaction_diagnostics
    assert diagnostics is not None
    assert set(diagnostics) == {
        "writer_lock_wait",
        "read_decode",
        "projection_verification",
        "financial_calculation",
        "invariant_check",
        "journal_append",
        "projection_encode",
        "projection_update",
        "database_commit",
    }
    assert all(value >= 0 for value in diagnostics.values())
    assert store.last_commit_receipt is not None
    assert store.last_commit_receipt["revision"] == store.read()["revision"]

    def fail(engine):
        raise ValueError("Synthetic calculation failure")

    with pytest.raises(ValueError, match="Synthetic calculation failure"):
        store.transact(START + 2, fail)
    assert store.last_commit_receipt is None and store.last_transaction_diagnostics is None
    assert store.reconcile()["balanced"]


@pytest.mark.parametrize(
    ("coarse_ms", "precise_ms", "prior_slow", "constrained"),
    [(109, 99, 3, False), (94, 101, 3, True), (1000, 999, 0, False), (999, 1001, 0, True)],
)
def test_normal_financial_loop_uses_precise_complete_work_for_existing_guard(
    pg_store, tmp_path, monkeypatch, coarse_ms, precise_ms, prior_slow, constrained
):
    import trading.tiered_runtime as tiered_module

    store, _ = pg_store
    runtime = TieredPaperRuntime(store, None, tmp_path / "raw.sqlite")
    runtime._loop_ms = deque([20] * (19 - prior_slow) + [101] * prior_slow, maxlen=1000)
    runtime._last_audit = runtime._last_receipts = START
    clocks = {"coarse": 1000.0, "precise": 2000.0}
    monkeypatch.setattr(
        tiered_module,
        "time",
        SimpleNamespace(
            time=lambda: START,
            monotonic=lambda: clocks["coarse"],
            perf_counter=lambda: clocks["precise"],
            thread_time=lambda: 0,
        ),
    )

    async def noop(*args):
        pass

    async def background(*args):
        await asyncio.Event().wait()

    # Exercise the normal loop and real financial transaction; isolate network and
    # disk transport. Put the declared elapsed work in post-commit capture, so it
    # must still count toward admission even though it is outside the writer lock.
    monkeypatch.setattr(runtime.stream, "configure", noop)
    monkeypatch.setattr(runtime.stream, "close", noop)
    for name in ("_references", "_fallback_loop", "_capture_loop", "_futures_loop"):
        monkeypatch.setattr(runtime, name, background)
    monkeypatch.setattr(runtime.evidence, "run", background)
    monkeypatch.setattr(runtime.evidence, "summary", lambda *args: None)
    monkeypatch.setattr(runtime.evidence, "selected", lambda *args: False)
    monkeypatch.setattr(runtime, "current_frames", lambda: ({}, {}))

    def capture(packet):
        clocks["coarse"] += coarse_ms / 1000
        clocks["precise"] += precise_ms / 1000

    monkeypatch.setattr(runtime.evidence, "compact", capture)
    observed = runtime.observe_engine_work

    def one_work_item(*args):
        observed(*args)
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime, "observe_engine_work", one_work_item)

    async def run_one():
        runtime.stream.changed.set()
        with pytest.raises(asyncio.CancelledError):
            await runtime.run()

    asyncio.run(run_one())
    assert (runtime._constrained_until > clocks["coarse"]) is constrained
    assert runtime._loop_ms[-1] == pytest.approx(precise_ms)
    latest = runtime._work_diagnostics.samples[-1]
    assert latest["coarse_elapsed_ms"] == coarse_ms
    assert latest["stages_ms"]["compact_capture"] == precise_ms
    assert store.reconcile()["balanced"]
