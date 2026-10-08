"""Exact role archive/history work through the initialized recorder owner."""

import asyncio
import copy
import json
import sqlite3
import time
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest
from test_research_storage import plan_at

from trading.autonomous_spec import LabPolicy, LabProposal, RuleSpec
from trading.evidence_runtime import EvidenceRecorder
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.lab_role_contract import VERSION, contract_hash, validate
from trading.research_storage import ResearchStorage, save_plan
from trading.role_worker import RoleWorker


@pytest.fixture(autouse=True)
def absent_financial_database(monkeypatch):
    monkeypatch.setenv(
        "QTRADES_TEST_DATABASE",
        "postgresql://absent:unused@127.0.0.1:1/role_archive_owner_absent",
    )


@pytest.fixture
def bench(tmp_path):
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    registry = ExperimentRegistry(tmp_path / "research.sqlite")
    policy = LabPolicy(request_id="synthetic-archive-policy").model_dump(mode="json")
    paper = SimpleNamespace(state={"autonomous_lab": {"policy": policy}})
    # The probe starts after evaluation: no financial store, model or venue.
    controller = SimpleNamespace(paper=paper, can_research=lambda: True)
    worker = RoleWorker(registry, controller, storage_owner=recorder.research_store)
    now = time.time()
    proposal = LabProposal(
        request_id="synthetic-archive-proposal",
        policy_id=policy["request_id"],
        kind="independent",
        strategy=RuleSpec(family="range_reversion"),
        reference=RuleSpec(),
        mechanism="Synthetic storage preservation comparison",
        question="Does the exact retained evaluation preserve its original inputs?",
        evidence_bundle_sha256="0" * 64,
    ).model_dump()
    context = {
        "contract": VERSION,
        "execution_mode": "qualified_roles",
        "question": {"question": "Synthetic archive owner question", "horizon": "short"},
        "policy": policy,
        "policy_sha256": fingerprint(policy),
    }
    evaluation = {
        "evaluated_at": now,
        "inputs": [{"synthetic": True, "value": "original adverse input"}],
        "feature": {"eligible": False},
    }
    identity = "role-" + "a" * 32
    with registry.transaction():
        registry.db.execute(
            "INSERT INTO role_tasks(id,created,updated,stage,status,context,proposal,evaluation) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                identity,
                now,
                now,
                "archive_evaluation",
                "queued",
                json.dumps(context),
                json.dumps(proposal),
                json.dumps(evaluation),
            ),
        )
    asyncio.run(recorder.flush())
    assert recorder._storage is not None
    recorder.enqueue({"kind": "wire", "at": now, "sample": "synthetic-owner-input"})
    asyncio.run(recorder.flush())
    owner = recorder._storage
    capture = owner.reopen(recorder.storage_status["latest_reference"])
    item = SimpleNamespace(
        worker=worker,
        registry=registry,
        recorder=recorder,
        owner=owner,
        plan=plan,
        identity=identity,
        evaluation=evaluation,
        context=context,
        proposal=proposal,
        now=now,
        capture=capture,
        capture_reference=recorder.storage_status["latest_reference"],
    )
    try:
        yield item
    finally:
        recorder.close()
        registry.close()


def assert_exact_review(item, attempts=None):
    task = item.worker.get(item.identity)
    assert task["stage"] == "review" and task["status"] == "queued"
    assert task["context"] == item.context and task["proposal"] == item.proposal
    assert task["attempts"] == ([] if attempts is None else attempts)
    saved = item.owner.reopen(task["evaluation"]["detail_reference"])
    assert saved["task"] == item.identity and saved["evaluation"] == item.evaluation
    assert task["evaluation"]["input_count"] == 1
    assert task["evaluation"]["input_sha256"] == fingerprint(item.evaluation["inputs"])
    assert item.owner.reopen(item.capture_reference) == item.capture
    return task


def test_capture_serializes_archive_off_loop_and_preserves_exact_evaluation(bench, monkeypatch):
    entered, release = Event(), Event()
    original = bench.recorder._write_batch_inner

    def held_capture(*args):
        with bench.owner._exclusive():
            entered.set()
            assert release.wait(3), "Fixture capture was not released"
            return original(*args)

    monkeypatch.setattr(bench.recorder, "_write_batch_inner", held_capture)
    monkeypatch.setattr(
        ResearchStorage, "_initialize", lambda self: pytest.fail("Unexpected second recovery owner")
    )

    async def run():
        capture = asyncio.create_task(bench.recorder.flush())
        work = None
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            work = asyncio.create_task(bench.worker.step(bench.now))
            ticks = 0
            for _ in range(5):
                await asyncio.sleep(0.01)
                ticks += 1
            assert ticks == 5 and not work.done()
            row = bench.registry.db.execute(
                "SELECT stage,owner FROM role_tasks WHERE id=?", (bench.identity,)
            ).fetchone()
            assert row["stage"] == "archive_evaluation" and row["owner"] == bench.worker.owner
        finally:
            release.set()
            await asyncio.wait_for(capture, 3)
            if work is not None:
                assert await asyncio.wait_for(work, 3)

    asyncio.run(run())
    assert_exact_review(bench)
    asyncio.run(bench.recorder.flush())
    assert bench.recorder._storage is bench.owner and bench.recorder.status["state"] == "recording"


def test_hot_rollover_and_cold_read_borrow_live_owner_keep_attempts(bench, monkeypatch):
    monkeypatch.setattr("trading.role_history.HOT_TASKS", 2)
    monkeypatch.setattr(
        ResearchStorage, "_initialize", lambda self: pytest.fail("Unexpected second recovery owner")
    )
    terminal = "role-" + "b" * 32
    with bench.registry.transaction():
        bench.registry.db.execute(
            "INSERT INTO role_tasks(id,created,updated,stage,status,context,result) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                terminal,
                bench.now,
                bench.now,
                "complete",
                "done",
                json.dumps(bench.context),
                json.dumps({"action": "no_change", "reason": "Retained synthetic adverse answer"}),
            ),
        )
        bench.registry.db.execute(
            "INSERT INTO role_attempts(task,stage,attempt,started,finished,status,profile,packet,"
            "response,reason,wall_reserved,tokens_reserved) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                terminal,
                "idea",
                1,
                bench.now,
                bench.now + 0.1,
                "answered",
                "{}",
                "{}",
                '{"answer":{"action":"no_change"}}',
                None,
                1.0,
                1,
            ),
        )
    before = bench.worker.get(terminal)
    bench.worker.history.rollover()
    cold = bench.worker.get(terminal)
    assert cold["archive_reference"]
    for key in ("id", "created", "updated", "stage", "status", "context", "result", "attempts"):
        assert cold[key] == before[key]
    assert bench.recorder._storage is bench.owner
    asyncio.run(bench.recorder.flush())
    assert bench.recorder.status["state"] == "recording"
    assert bench.owner.reopen(bench.capture_reference) == bench.capture


@pytest.mark.parametrize("failure", ["closed", "not_ready", "changed_plan"])
def test_unavailable_live_owner_refuses_without_fallback(bench, monkeypatch, failure):
    second = None
    if failure == "closed":
        bench.recorder.close()
    elif failure == "not_ready":
        second = EvidenceRecorder(bench.registry.path.parent / "unready-evidence.sqlite")
        bench.worker = RoleWorker(
            bench.registry, bench.worker.controller, storage_owner=second.research_store
        )
    else:
        changed = bench.plan.model_copy(update={"temporary_bytes": bench.plan.temporary_bytes + 1})
        (bench.registry.path.parent / "research-storage.json").write_text(changed.model_dump_json())
    monkeypatch.setattr(
        ResearchStorage, "_initialize", lambda self: pytest.fail("Unavailable live owner fell back")
    )
    try:
        assert not asyncio.run(bench.worker.step(bench.now))
        task = bench.worker.get(bench.identity)
        assert task["stage"] == "archive_evaluation"
        assert task["status"] in {"waiting", "failed"}
        assert task["evaluation"] == bench.evaluation and task["attempts"] == []
        assert (
            "identity differs" in task["reason"]
            if failure == "changed_plan"
            else "not ready" in task["reason"]
        )
        with pytest.raises((OSError, ValueError), match="identity differs|not ready"):
            with bench.worker.history.storage():
                pytest.fail("Unavailable live history owner admitted")
    finally:
        if second is not None:
            second.close()


def test_registry_rollback_explicit_archive_retry_preserves_original_and_deduplicates(
    bench, monkeypatch
):
    packet = {
        "task": bench.identity,
        "question": bench.context["question"],
        "evidence": {"e0": {"synthetic": True, "source": "Frozen causal fixture"}},
        "capabilities": {"r0": {"strategy": bench.proposal["strategy"]}},
    }
    answer = {
        "action": "propose_experiment",
        "evidence_ids": ["e0"],
        "capability": "r0",
        "mechanism": "Compare the frozen supported rule under identical paper costs.",
        "falsification": "Reject benefit if the matched future result is adverse or inconclusive.",
        "rationale": "This synthetic consumed idea supports evaluation, not a preferred answer.",
        "dependency": None,
    }
    validate("researcher", answer, packet)
    profile = {
        "model": "synthetic-consumed-role-model",
        "role_contract": VERSION,
        "contract_sha256": contract_hash(),
        "timeout_seconds": 30,
        "hourly_wall_seconds": 120,
        "hourly_tokens": 65536,
        "token_allowance": 8192,
    }
    with bench.registry.transaction():
        bench.registry.db.execute(
            "INSERT INTO role_attempts(task,stage,attempt,started,finished,status,profile,packet,"
            "response,reason,wall_reserved,tokens_reserved) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                bench.identity,
                "idea",
                1,
                bench.now - 2,
                bench.now - 1,
                "answered",
                json.dumps(profile),
                json.dumps(packet),
                json.dumps({"answer": answer, "wall_seconds": 1.0, "tokens": {"eval_count": 77}}),
                None,
                30.0,
                8192,
            ),
        )
    consumed = bench.worker.get(bench.identity)["attempts"]

    def raw_consumed():
        return {
            table: [tuple(row) for row in bench.registry.db.execute(f"SELECT * FROM {table}")]
            for table in ("role_attempts", "role_attempt_allowances", "role_attempt_usage")
        }

    original_consumed = raw_consumed()
    original = bench.registry.transaction
    reject = [True]

    @contextmanager
    def transaction():
        with original():
            yield
            row = bench.registry.db.execute(
                "SELECT stage FROM role_tasks WHERE id=?", (bench.identity,)
            ).fetchone()
            if reject[0] and row and row[0] == "review":
                reject[0] = False
                raise sqlite3.OperationalError("Synthetic archive registry commit refused")

    monkeypatch.setattr(bench.registry, "transaction", transaction)
    assert not asyncio.run(bench.worker.step(bench.now))
    failed = bench.worker.get(bench.identity)
    assert failed["stage"] == "archive_evaluation" and failed["status"] == "failed"
    assert failed["evaluation"] == bench.evaluation and failed["attempts"] == consumed
    assert raw_consumed() == original_consumed
    retained = bench.owner.db.execute(
        "SELECT sha,segment,record FROM storage_records WHERE kind='role_evaluation'"
    ).fetchall()
    assert len(retained) == 1
    reference = f"capture-v2:{retained[0]['segment']}:{retained[0]['record']}:{retained[0]['sha']}"
    archived = bench.owner.reopen(reference)
    assert archived["evaluation"] == bench.evaluation
    # A failed archive stage is terminal for hot retention, but remains repairable.
    monkeypatch.setattr("trading.role_history.HOT_TASKS", 1)
    bench.worker.history.rollover()
    cold = bench.worker.get(bench.identity)
    assert cold["archive_reference"] and cold["evaluation"] == bench.evaluation
    assert cold["attempts"] == consumed
    assert bench.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0
    for table in ("role_attempt_allowances", "role_attempt_usage"):
        assert raw_consumed()[table] == original_consumed[table]
    # Leave a free hot slot for verified cold restoration and normal dispatch.
    monkeypatch.setattr("trading.role_history.HOT_TASKS", 2)
    assert bench.worker.transport is None
    retried = bench.worker.retry(bench.identity)
    assert retried["stage"] == "archive_evaluation" and retried["status"] == "queued"
    current = bench.worker.get(bench.identity)
    assert current["evaluation"] == bench.evaluation and current["attempts"] == consumed
    assert current["context"] == failed["context"] and current["proposal"] == failed["proposal"]
    with pytest.raises(ValueError, match="Only a failed model transport"):
        bench.worker.retry(bench.identity)
    assert bench.worker.get(bench.identity) == current
    assert asyncio.run(bench.worker.step(bench.now))
    reviewed = assert_exact_review(bench, consumed)
    assert reviewed["evaluation"]["detail_reference"] == reference
    assert bench.worker.transport is None
    after = bench.owner.db.execute(
        "SELECT sha,segment,record FROM storage_records WHERE kind='role_evaluation'"
    ).fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in retained]
    assert raw_consumed() == original_consumed
    assert bench.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 1
    assert (
        bench.registry.db.execute("SELECT count(*) FROM role_attempt_allowances").fetchone()[0] == 1
    )


def test_archive_retry_refuses_missing_full_inputs_without_changing_saved_task(bench):
    for unavailable in (None, {"evaluated_at": bench.now, "input_count": 1}):
        with bench.registry.transaction():
            bench.registry.db.execute(
                "UPDATE role_tasks SET status='failed',evaluation=? WHERE id=?",
                (json.dumps(unavailable), bench.identity),
            )
        before = bench.worker.get(bench.identity)
        with pytest.raises(ValueError, match="Original full evaluation is unavailable"):
            bench.worker.retry(bench.identity)
        assert bench.worker.get(bench.identity) == before
    assert bench.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0


def test_cancellation_drains_archive_before_releasing_lease(bench):
    entered, release = Event(), Event()

    @contextmanager
    def held_borrow(plan):
        with bench.recorder.research_store(plan) as owner:
            entered.set()
            assert release.wait(3), "Fixture archive was not released"
            yield owner

    bench.worker = RoleWorker(bench.registry, bench.worker.controller, storage_owner=held_borrow)

    async def run():
        task = asyncio.create_task(bench.worker.step(bench.now))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0.05)
            assert not task.done()
            row = bench.registry.db.execute(
                "SELECT owner,stage FROM role_tasks WHERE id=?", (bench.identity,)
            ).fetchone()
            assert row["owner"] == bench.worker.owner and row["stage"] == "archive_evaluation"
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)

    asyncio.run(run())
    assert_exact_review(bench)
    row = bench.registry.db.execute(
        "SELECT owner,lease_until FROM role_tasks WHERE id=?", (bench.identity,)
    ).fetchone()
    assert row["owner"] is None and row["lease_until"] is None
    asyncio.run(bench.recorder.flush())
    assert bench.recorder.status["state"] == "recording"


def test_archive_retry_refuses_owned_changed_stage_and_eight_active_questions(bench, monkeypatch):
    with bench.registry.transaction():
        bench.registry.db.execute(
            "UPDATE role_tasks SET status='failed',owner='other-owner',lease_until=? WHERE id=?",
            (bench.now + 30, bench.identity),
        )
    owned = bench.worker.get(bench.identity)
    with pytest.raises(ValueError, match="current owner"):
        bench.worker.retry(bench.identity)
    assert bench.worker.get(bench.identity) == owned
    with bench.registry.transaction():
        bench.registry.db.execute(
            "UPDATE role_tasks SET owner=NULL,lease_until=NULL WHERE id=?", (bench.identity,)
        )
    original_get = bench.worker.get

    def changed_owner(identity):
        original = original_get(identity)
        with bench.registry.transaction():
            bench.registry.db.execute(
                "UPDATE role_tasks SET owner='new-owner',lease_until=? WHERE id=?",
                (bench.now + 30, identity),
            )
        return original

    monkeypatch.setattr(bench.worker, "get", changed_owner)
    with pytest.raises(ValueError, match="current owner"):
        bench.worker.retry(bench.identity)
    monkeypatch.setattr(bench.worker, "get", original_get)
    assert (
        bench.registry.db.execute(
            "SELECT owner FROM role_tasks WHERE id=?", (bench.identity,)
        ).fetchone()[0]
        == "new-owner"
    )
    with bench.registry.transaction():
        bench.registry.db.execute(
            "UPDATE role_tasks SET stage='evaluate',owner=NULL,lease_until=NULL WHERE id=?",
            (bench.identity,),
        )
    changed = bench.worker.get(bench.identity)
    with pytest.raises(ValueError, match="Only a failed model transport"):
        bench.worker.retry(bench.identity)
    assert bench.worker.get(bench.identity) == changed
    with bench.registry.transaction():
        bench.registry.db.execute(
            "UPDATE role_tasks SET stage='archive_evaluation' WHERE id=?", (bench.identity,)
        )
        for index in range(8):
            bench.registry.db.execute(
                "INSERT INTO role_tasks(id,created,updated,stage,status,context) "
                "VALUES(?,?,?,?,?,?)",
                (
                    f"role-active-{index}",
                    bench.now,
                    bench.now,
                    "idea",
                    "queued",
                    json.dumps(bench.context),
                ),
            )
    before = bench.worker.get(bench.identity)
    with pytest.raises(ValueError, match="Eight active role questions"):
        bench.worker.retry(bench.identity)
    assert bench.worker.get(bench.identity) == before
    assert bench.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0


def test_explicit_standalone_archive_keeps_exact_retention(bench):
    bench.worker = RoleWorker(bench.registry, bench.worker.controller)
    original = copy.deepcopy(bench.evaluation)
    assert asyncio.run(bench.worker.step(bench.now))
    assert_exact_review(bench)
    assert bench.evaluation == original


def test_cancelled_history_maintenance_drains_real_rollover_before_owner_closes(bench, monkeypatch):
    monkeypatch.setattr("trading.role_history.HOT_TASKS", 2)
    terminal = "role-" + "c" * 32
    with bench.registry.transaction():
        bench.registry.db.execute(
            "INSERT INTO role_tasks(id,created,updated,stage,status,context,result) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                terminal,
                bench.now,
                bench.now,
                "complete",
                "done",
                json.dumps(bench.context),
                json.dumps({"action": "no_change", "reason": "Retained maintenance answer"}),
            ),
        )
    before = bench.worker.get(terminal)
    entered, release, finished = Event(), Event(), Event()

    @contextmanager
    def held_borrow(plan):
        with bench.recorder.research_store(plan) as owner:
            entered.set()
            assert release.wait(3), "Fixture maintenance was not released"
            yield owner

    bench.worker = RoleWorker(bench.registry, bench.worker.controller, storage_owner=held_borrow)

    def real_rollover():
        bench.worker.history.rollover()
        finished.set()

    async def run():
        task = asyncio.create_task(bench.worker._maintain("followups", real_rollover))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            for _ in range(5):
                await asyncio.sleep(0.01)
            assert not task.done() and not finished.is_set()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
        assert finished.is_set()

    asyncio.run(run())
    archived = bench.worker.get(terminal)
    assert archived["archive_reference"]
    for key in ("id", "created", "updated", "stage", "status", "context", "result", "attempts"):
        assert archived[key] == before[key]
    assert bench.recorder._storage is bench.owner
    asyncio.run(bench.recorder.flush())
    assert bench.recorder.status["state"] == "recording"
    assert bench.owner.reopen(bench.capture_reference) == bench.capture
