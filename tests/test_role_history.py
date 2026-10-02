"""Continuous role history retains old work; disposable stubs prove software only."""

import asyncio
import copy

import pytest
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_role_worker import ModelStub, make_lab

from trading.research_storage import ResearchStorage, save_plan
from trading.role_worker import Question, RoleWorker


class NoChange(ModelStub):
    def admit(self, role):
        return super().admit(role) | {"hourly_wall_seconds": 100000, "hourly_tokens": 10000000}

    def infer(self, role, packet, profile):
        return {
            "answer": {
                "action": "no_change",
                "evidence_ids": ["e0"],
                "capability": None,
                "mechanism": "Retain an unchanged reviewed method without new authority.",
                "falsification": "A new measured outcome would require another question.",
                "dependency": None,
                "rationale": "No measured benefit; retain the current reviewed method.",
            },
            "scope": "Disposable software response; no model or trading evidence",
        }


def test_failed_task_cannot_archive_while_original_call_can_still_finish(
    pg_store, tmp_path, monkeypatch
):
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    lab = make_lab(pg_store[0], tmp_path)
    save_plan(tmp_path, plan_at(tmp_path))

    class Delayed(NoChange):
        calls_started = 0

        def infer(self, *args):
            self.calls_started += 1
            self.entered.set()
            assert self.release.wait(5)
            return super().infer(*args)

    model = Delayed()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    question = worker.enqueue(
        Question(question="Keep the original unresolved call until it returns.")
    )

    async def check():
        pending = asyncio.create_task(worker.step(START))
        assert await asyncio.to_thread(model.entered.wait, 5)
        replacement = RoleWorker(lab.registry, lab)
        with lab.registry.transaction():
            lab.registry.db.execute(
                "UPDATE role_tasks SET lease_until=? WHERE id=?", (START - 1, question["id"])
            )
        replacement.enabled = True
        try:
            assert not await replacement.step(START)
            assert replacement.get(question["id"])["status"] == "failed"
            replacement.history.rollover()
            retained = replacement.get(question["id"])
            assert retained["archive_reference"] is None
            assert len(retained["attempts"]) == 1 and retained["attempts"][0]["finished"] is None
            replacement.retry(question["id"])
            assert replacement.get(question["id"])["attempts"][0]["status"] == "retry_authorized"
        finally:
            model.release.set()
            await pending
        current = worker.get(question["id"])
        assert current["attempts"][0]["response"]
        if current["status"] != "done":
            assert await replacement.step(START)  # Reuse the receipt under the current owner.
            current = replacement.get(question["id"])
        worker.history.rollover()
        cold = RoleWorker(lab.registry, lab).get(question["id"])
        assert cold["archive_reference"] and cold["attempts"] == current["attempts"]
        assert model.calls_started == 1 and pg_store[0].reconcile()["balanced"]

    asyncio.run(check())
    lab.registry.close()


def test_sequential_questions_cross_old_lifetime_limit_and_reopen(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(store, tmp_path)
    save_plan(tmp_path, plan_at(tmp_path))
    worker = RoleWorker(lab.registry, lab, NoChange())
    worker.enabled = True  # This owned software fixture cannot enable installed inference.
    original = copy.deepcopy(lab.paper.state)
    first = None
    for i in range(529):
        clock[0] = START + i
        task = worker.enqueue(
            Question(
                question=f"Retain history of synthetic question number {i:04d}.",
                request_id=f"history-request-{i:04d}",
            )
        )
        assert asyncio.run(worker.step(clock[0])), worker.get(task["id"])["reason"]
        saved = worker.get(task["id"])
        assert saved["status"] == "done" and len(saved["attempts"]) == 1
        if i == 0:
            first = saved
    assert first is not None
    page = worker.page(search="0000")
    assert len(page["tasks"]) == 1 and page["tasks"][0]["id"] == first["id"]
    assert page["history"]["retained"] == 529 and page["history"]["archived"] >= 17
    assert page["history"]["active"] == 0
    identities, cursor, before_id = [], 0, ""
    while True:
        page = worker.page(cursor, before_id)
        identities.extend(t["id"] for t in page["tasks"])
        if not page["next_before"]:
            break
        cursor, before_id = page["next_before"], page["next_before_id"]
    assert len(identities) == len(set(identities)) == 529
    restored = worker.get(first["id"])
    for key in ("context", "result", "attempts"):
        assert restored[key] == first[key]
    assert lab.paper.state == original and store.reconcile()["balanced"]
    restarted = RoleWorker(lab.registry, lab)
    assert restarted.get(first["id"])["result"] == first["result"]
    assert (
        restarted.enqueue(
            Question.model_validate(
                first["context"]["question"] | {"request_id": "history-request-0000"}
            )
        )["id"]
        == first["id"]
    )


def test_request_identities_cross_old_ceiling_without_rewriting_intent(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    worker = RoleWorker(lab.registry, lab)
    question = Question(question="Keep every request identity for this unchanged research intent.")
    first = worker.enqueue(question)
    for i in range(4100):
        request = question.model_copy(update={"request_id": f"retained-request-{i:04d}"})
        assert worker.enqueue(request)["id"] == first["id"]
    assert lab.registry.db.execute("SELECT count(*) FROM role_requests").fetchone()[0] == 4100
    with pytest.raises(ValueError, match="cannot be rewritten"):
        worker.enqueue(
            Question(
                question="A different question cannot use an old identity.",
                request_id="retained-request-0000",
            )
        )


@pytest.fixture
def history_worker(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)  # Proportional pressure.
    lab = make_lab(store, tmp_path)
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    worker = RoleWorker(lab.registry, lab, NoChange())
    worker.enabled = True
    task = worker.enqueue(Question(question="Retain the original complete historical question."))
    assert asyncio.run(worker.step(START))
    yield worker, worker.get(task["id"]), plan, store
    lab.registry.close()


@pytest.mark.parametrize("fault", ["outage", "commit", "quota"])
def test_archive_failure_preserves_hot_answers_then_recovers_same_limits(
    history_worker, monkeypatch, fault
):
    from pathlib import Path

    worker, original, plan, store = history_worker
    append = ResearchStorage.append
    filler = None
    if fault == "outage":

        def unavailable(*args, **kwargs):
            raise OSError("Owned archive fixture unavailable")

        monkeypatch.setattr(ResearchStorage, "append", unavailable)
    elif fault == "commit":
        worker.registry.db.execute(
            "CREATE TEMP TRIGGER history_commit_fault BEFORE UPDATE ON role_tasks "
            "WHEN NEW.archive_reference IS NOT NULL BEGIN SELECT RAISE(ABORT,'Injected crash'); END"
        )
    else:
        owned = ResearchStorage(plan)
        owned.close()
        filler = Path(plan.root) / "temporary" / "owned-quota-fixture"
        filler.write_bytes(b"x" * (plan.temporary_bytes - plan.scratch_bytes - 65536))
    next_question = Question(
        question="A subsequent question needs safe history continuation.",
        request_id="history-after-failure",
    )
    with pytest.raises(ValueError, match="continuation|capacity"):
        worker.enqueue(next_question)
    assert worker.get(original["id"]) == original
    assert not worker.registry.db.execute(
        "SELECT 1 FROM role_requests WHERE request_id=?", (next_question.request_id,)
    ).fetchone()
    if fault == "outage":
        monkeypatch.setattr(ResearchStorage, "append", append)
    elif fault == "commit":
        worker.registry.db.execute("DROP TRIGGER history_commit_fault")
    else:
        assert filler is not None and filler.parent == Path(plan.root) / "temporary"
        filler.unlink()  # Only the deliberately written disposable quota fixture.
    following = worker.enqueue(next_question)
    reopened = RoleWorker(worker.registry, worker.controller).get(original["id"])
    assert reopened["archive_reference"]
    for key in ("context", "result", "attempts"):
        assert reopened[key] == original[key]
    assert following["status"] == "queued" and store.reconcile()["balanced"]


def test_archival_keeps_unknown_attempt_charges_and_explicit_retry(history_worker, monkeypatch):
    worker, first, _, store = history_worker
    worker.transport.infer = lambda *args: (_ for _ in ()).throw(TimeoutError("Unknown completion"))
    worker.transport.admit = lambda role: {
        "timeout_seconds": 5,
        "hourly_wall_seconds": 60,
        "hourly_tokens": 16384,
        "token_allowance": 8192,
    }
    unknown = worker.enqueue(Question(question="Retain an unknown final model acknowledgment."))
    assert not asyncio.run(worker.step(START))
    assert worker.get(unknown["id"])["attempts"][0]["response"] is None
    following = worker.enqueue(
        Question(question="New research must retain the previous charged budget.")
    )
    assert not asyncio.run(worker.step(START))
    assert "allowance" in worker.get(following["id"])["reason"]
    assert worker.get(unknown["id"])["archive_reference"]
    total = worker.registry.db.execute(
        "SELECT sum(tokens_reserved),sum(wall_reserved) FROM role_attempt_allowances"
    ).fetchone()
    assert tuple(total) == (16384, 10)
    worker.retry(unknown["id"])
    assert worker.get(unknown["id"])["attempts"][0]["status"] == "retry_authorized"
    assert worker.get(unknown["id"])["archive_reference"] is None
    assert tuple(
        worker.registry.db.execute(
            "SELECT sum(tokens_reserved),sum(wall_reserved) FROM role_attempt_allowances"
        ).fetchone()
    ) == (16384, 10)
    assert worker.get(first["id"])["result"] == first["result"] and store.reconcile()["balanced"]


def test_actual_registry_full_retains_history_and_recovers_when_fixture_space_released(
    history_worker, monkeypatch
):
    import sqlite3

    worker, original, _, store = history_worker
    # Archive while headroom exists, then fill the actual SQLite ceiling, not a row counter.
    worker.history.rollover()
    db = worker.registry.db
    pages = db.execute("PRAGMA page_count").fetchone()[0]
    cap = db.execute(f"PRAGMA max_page_count={pages + 128}").fetchone()[0]
    db.execute("CREATE TABLE owned_quota_fixture(payload BLOB)")
    with pytest.raises(sqlite3.OperationalError, match="full"):
        while True:
            db.execute("INSERT INTO owned_quota_fixture VALUES(?)", (b"x" * 16384,))
    question = Question(question="Continue after releasing only the disposable storage filler.")
    with pytest.raises(ValueError, match="physical write headroom"):
        worker.enqueue(question)
    assert worker.get(original["id"])["result"] == original["result"]
    db.execute("DELETE FROM owned_quota_fixture")
    assert worker.enqueue(question)["status"] == "queued"
    assert db.execute("PRAGMA max_page_count").fetchone()[0] == cap
    assert worker.get(original["id"])["attempts"] == original["attempts"]
    assert store.reconcile()["balanced"]


def test_cold_usage_projection_keeps_endpoint_counts_and_unknowns(history_worker):
    worker, first, _, store = history_worker
    original_infer = worker.transport.infer

    def measured_fixture(*args):
        return original_infer(*args) | {
            "tokens": {"prompt_eval_count": 17, "eval_count": 11},
            "wall_seconds": 0.25,
        }

    worker.transport.infer = measured_fixture
    second = worker.enqueue(Question(question="Preserve synthetic recorded endpoint usage counts."))
    assert asyncio.run(worker.step(START))
    before = [dict(row) for row in worker.registry.db.execute("SELECT * FROM role_attempt_usage")]
    worker.history.rollover()
    after = [dict(row) for row in worker.registry.db.execute("SELECT * FROM role_attempt_usage")]
    assert sorted(before, key=lambda r: r["task"]) == sorted(after, key=lambda r: r["task"])
    rows = {r["task"]: r for r in after}
    assert rows[first["id"]]["input_tokens"] is None
    assert rows[second["id"]]["input_tokens"] == 17
    assert rows[second["id"]]["output_tokens"] == 11
    assert rows[second["id"]]["measured_wall_seconds"] == 0.25
    assert worker.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0
    RoleWorker(worker.registry, worker.controller)
    assert [
        dict(r) for r in worker.registry.db.execute("SELECT * FROM role_attempt_usage")
    ] == after
    assert store.reconcile()["balanced"]
