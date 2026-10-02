"""Actual supervisor recovery on owned PostgreSQL; software answers only."""

import asyncio
import socket
from contextlib import contextmanager

import pytest
from psycopg.conninfo import make_conninfo
from test_autonomous_lab import admit, close_window
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_lessons import DataWaitStub
from test_research_storage import plan_at
from test_role_history import NoChange
from test_role_worker import make_lab

from trading.evidence_runtime import EvidenceRecorder
from trading.paper_store import PaperStore
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker


async def until(predicate, seconds=6):
    end = asyncio.get_running_loop().time() + seconds
    while not predicate():
        if asyncio.get_running_loop().time() >= end:
            raise AssertionError("Normal supervisor did not reach the bounded expected state")
        await asyncio.sleep(0.02)


def test_normal_supervisor_recovers_refused_dependency_and_preserves_independent_progress(
    pg_store, tmp_path, monkeypatch
):
    import trading.role_worker as module

    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    recorder.enqueue({"kind": "wire", "at": START, "source": "synthetic-supervisor-fixture"})
    asyncio.run(recorder.flush())
    comparison = admit(lab, START)
    model = DataWaitStub()
    model.dependency = "mature_outcome"
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    waiting = worker.enqueue(Question(question="Wait for the original offered mature comparison."))
    assert asyncio.run(worker.step())
    dependency = worker.get(waiting["id"])["result"]["wait_requirement"]
    independent = worker.enqueue(
        Question(question="Finish independent software research during outage.")
    )
    worker.transport = NoChange()
    original_reader = module.reader
    checks = []
    outage = [True]
    refusing = socket.socket()
    refusing.bind(("127.0.0.1", 0))  # Owned, bound but never listening.
    port = refusing.getsockname()[1]

    @contextmanager
    def dependency_reader(paper):
        checks.append(clock[0])
        if outage[0]:
            info = paper.store.connection.info
            reader = PaperStore(
                make_conninfo(info.dsn, password=info.password, port=port, connect_timeout=1)
            )
            try:
                yield reader
            finally:
                reader.close()
        else:
            with original_reader(paper) as view:
                yield view

    monkeypatch.setattr(module, "reader", dependency_reader)

    async def check():
        supervisor = asyncio.create_task(worker.run())
        try:
            await until(lambda: bool(checks))
            await asyncio.sleep(0.1)
            assert not supervisor.done(), "Dependency outage terminated the real supervisor"
            await until(lambda: worker.get(independent["id"])["status"] == "done")
            retained = worker.get(waiting["id"])
            assert retained["stage"] == "data_wait" and retained["status"] == "waiting"
            assert retained["result"]["wait_requirement"] == dependency
            assert retained["retry_at"] > clock[0]
            assert "database" in retained["reason"].lower()
            checked = len(checks)
            await asyncio.sleep(1.05)
            assert len(checks) == checked  # Real loop runs but respects the persisted backoff.
            outage[0] = False
            score = close_window(lab, comparison, "inconclusive")
            clock[0] = max(score["available_at"] + 1, retained["retry_at"] + 1)
            await until(lambda: worker.get(waiting["id"])["status"] == "done")
            next_rows = lab.registry.db.execute(
                "SELECT id FROM role_tasks WHERE json_extract(context,'$.predecessor_task')=?",
                (waiting["id"],),
            ).fetchall()
            assert len(next_rows) == 1
            successor = worker.get(next_rows[0][0])
            assert successor["context"]["dependency_evidence"]["body"] == score
            assert len(model.calls) == 1
            await asyncio.sleep(1.05)
            assert (
                len(
                    lab.registry.db.execute(
                        "SELECT id FROM role_tasks "
                        "WHERE json_extract(context,'$.predecessor_task')=?",
                        (waiting["id"],),
                    ).fetchall()
                )
                == 1
            )
            assert not supervisor.done() and store.reconcile()["balanced"]
        finally:
            supervisor.cancel()
            with pytest.raises(asyncio.CancelledError):
                await supervisor

    try:
        asyncio.run(check())
    finally:
        refusing.close()
        lab.registry.close()


def test_normal_supervisor_recovers_successor_storage_and_keeps_other_work_moving(
    pg_store, tmp_path, monkeypatch
):
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    lab = make_lab(pg_store[0], tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    recorder.enqueue({"kind": "wire", "at": START, "source": "synthetic-supervisor-fixture"})
    asyncio.run(recorder.flush())
    finished_worker = RoleWorker(lab.registry, lab, NoChange())
    finished_worker.enabled = True
    terminal = finished_worker.enqueue(
        Question(question="Make one disposable terminal archive record.")
    )
    assert asyncio.run(finished_worker.step())
    model = DataWaitStub()
    model.dependency = "mature_outcome"
    comparison = admit(lab, START)
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    waiting = worker.enqueue(
        Question(question="Keep the original wait if successor storage is absent.")
    )
    assert asyncio.run(worker.step())
    independent = worker.enqueue(
        Question(question="Complete this independent task through storage outage.")
    )
    worker.transport = NoChange()
    # Ensure a terminal hot payload exists when continuation performs real rollover.
    finished_worker.history.restore(terminal["id"])
    frozen = worker.get(waiting["id"])["result"]
    score = close_window(lab, comparison, "inconclusive")
    clock[0] = score["available_at"] + 1
    plan_file = tmp_path / "research-storage.json"
    unavailable = tmp_path / "owned-plan-temporarily-unavailable.json"
    assert plan_file.parent.resolve() == tmp_path.resolve()
    plan_file.rename(unavailable)  # Only this fixture's configuration; no operating G: edits.

    async def check():
        supervisor = asyncio.create_task(worker.run())
        try:
            await until(lambda: worker.get(independent["id"])["status"] == "done")
            blocked = worker.get(waiting["id"])
            assert blocked["stage"] == "data_wait" and blocked["result"] == frozen
            assert blocked["retry_at"] > clock[0] and "storage" in blocked["reason"]
            assert not supervisor.done()
            unavailable.rename(plan_file)
            clock[0] = blocked["retry_at"] + 1
            await until(lambda: worker.get(waiting["id"])["status"] == "done")
            successors = lab.registry.db.execute(
                "SELECT id FROM role_tasks WHERE json_extract(context,'$.predecessor_task')=?",
                (waiting["id"],),
            ).fetchall()
            assert len(successors) == 1 and len(model.calls) == 1
            assert pg_store[0].reconcile()["balanced"]
        finally:
            supervisor.cancel()
            with pytest.raises(asyncio.CancelledError):
                await supervisor

    try:
        asyncio.run(check())
    finally:
        if unavailable.exists():
            unavailable.rename(plan_file)
        lab.registry.close()


def test_supervisor_persists_selection_backoff_and_exposes_programming_fault(
    pg_store, tmp_path, monkeypatch
):
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(pg_store[0], tmp_path)
    worker = RoleWorker(lab.registry, lab, NoChange())
    worker.enabled = True
    independent = worker.enqueue(
        Question(question="Independent progress during an interrupted selector.")
    )
    calls = []

    def unavailable():
        calls.append(clock[0])
        raise OSError("Owned selection write unavailable")

    monkeypatch.setattr(worker, "select_followups", unavailable)

    async def check():
        supervisor = asyncio.create_task(worker.run())
        try:
            await until(lambda: worker.get(independent["id"])["status"] == "done")
            state = lab.registry.db.execute(
                "SELECT * FROM role_supervision WHERE phase='followups'"
            ).fetchone()
            assert state["status"] == "waiting" and state["retry_at"] == START + 30
            assert len(calls) == 1 and not supervisor.done()
        finally:
            supervisor.cancel()
            with pytest.raises(asyncio.CancelledError):
                await supervisor
        replacement = RoleWorker(lab.registry, lab, NoChange())
        monkeypatch.setattr(replacement, "select_followups", unavailable)
        await replacement._maintain("followups", replacement.select_followups)
        assert len(calls) == 1  # Durable phase cooldown survives worker reconstruction.
        clock[0] += 31
        await replacement._maintain("followups", lambda: {"selected": 0, "waiting": 0})
        assert (
            lab.registry.db.execute(
                "SELECT status FROM role_supervision WHERE phase='followups'"
            ).fetchone()[0]
            == "recovered"
        )

        def invalid():
            raise KeyError("Malformed dependency implementation")

        with pytest.raises(KeyError):
            await replacement._maintain("dependencies", invalid)
        assert replacement.page()["supervision"][0]["status"] == "failed"
        assert (
            lab.registry.db.execute(
                "SELECT status FROM role_supervision WHERE phase='dependencies'"
            ).fetchone()[0]
            == "failed"
        )
        assert pg_store[0].reconcile()["balanced"]

    try:
        asyncio.run(check())
    finally:
        lab.registry.close()
