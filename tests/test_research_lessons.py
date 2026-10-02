"""Two-generation source proof with real disposable paper authority and model stub."""

import asyncio
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_autonomous_lab import admit, bars_at, close_window, tick_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_role_history import NoChange
from test_role_worker import ModelStub, make_lab

from trading.evidence_runtime import EvidenceRecorder
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker


class DataWaitStub(ModelStub):
    dependency = "new_closed_bars"

    def infer(self, role, packet, profile):
        result = super().infer(role, packet, profile)
        result["answer"].update(
            action="request_data",
            capability=None,
            dependency=self.dependency,
            evidence_ids=["e2"],
        )
        return result


class FollowupStub(ModelStub):
    def infer(self, role, packet, profile):
        result = super().infer(role, packet, profile)
        if role == "researcher" and "e1" in packet["evidence"]:
            result["answer"].update(action="propose_experiment", capability="r1")
        elif role == "researcher" and "e3" in packet["evidence"]:
            result["answer"].update(capability="r1")
        return result


@pytest.mark.parametrize("boundary", ["before", "deferred", "lost_ack", "selected"])
@pytest.mark.parametrize("archive", [False, True])
def test_followup_discovery_survives_archive_and_restart_at_each_selection_boundary(
    pg_store, tmp_path, monkeypatch, boundary, archive
):
    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    worker = RoleWorker(lab.registry, lab, FollowupStub())
    worker.enabled = True
    first = worker.enqueue(
        Question(question="After this comparison investigate a different range.")
    )
    done, score = complete(worker, lab, first, START)
    clock[0] = score["available_at"] + 3
    enqueue = worker.enqueue
    if boundary in {"deferred", "lost_ack"}:

        def interrupted(*args, **kwargs):
            if boundary == "lost_ack":
                enqueue(*args, **kwargs)
            raise OSError("Owned follow-up save interrupted before acknowledgment")

        monkeypatch.setattr(worker, "enqueue", interrupted)
        assert worker.select_followups() == {"selected": 0, "waiting": 0}
        monkeypatch.setattr(worker, "enqueue", enqueue)
    elif boundary == "selected":
        assert worker.select_followups() == {"selected": 1, "waiting": 0}
    if archive:
        monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
        worker.history.rollover()
        assert worker.get(first["id"])["archive_reference"]
    replacement = RoleWorker(lab.registry, lab, FollowupStub())
    assert replacement.get(first["id"])["result"] == done["result"]
    clock[0] += 61
    assert replacement.select_followups() == {
        "selected": 0 if boundary == "selected" else 1,
        "waiting": 0,
    }
    assert replacement.select_followups() == {"selected": 0, "waiting": 0}
    assert lab.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0] == 2
    selected = lab.registry.db.execute("SELECT state,next_task FROM research_selection").fetchall()
    assert len(selected) == 1 and selected[0]["state"] == "selected"
    assert selected[0]["next_task"] != first["id"]
    assert len(worker.transport.calls) == 3 and replacement.transport.calls == []
    assert store.reconcile()["balanced"]
    lab.registry.close()


@pytest.mark.parametrize("already_selected", [False, True])
def test_legacy_cold_followup_migration_preserves_selection_and_never_rescans(
    pg_store, tmp_path, monkeypatch, already_selected
):
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    lab = make_lab(pg_store[0], tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    worker = RoleWorker(lab.registry, lab, FollowupStub())
    worker.enabled = True
    task = worker.enqueue(
        Question(question="Preserve the older cold comparison's next experiment.")
    )
    done, score = complete(worker, lab, task, START)
    clock[0] = score["available_at"] + 3
    if already_selected:
        assert worker.select_followups()["selected"] == 1
    worker.history.rollover()
    assert worker.get(task["id"])["archive_reference"]
    # Only owned fixture metadata: represent the pre-repair archive exactly.
    with lab.registry.transaction():
        for trigger in ("role_followup_insert", "role_followup_update"):
            lab.registry.db.execute(f"DROP TRIGGER {trigger}")
        lab.registry.db.execute("DROP TABLE role_followups")
        lab.registry.db.execute("DROP TABLE role_followup_backfill")
    replacement = RoleWorker(lab.registry, lab, FollowupStub())
    reads = []
    read = replacement.history.read

    def tracked(row):
        reads.append(row["id"])
        return read(row)

    monkeypatch.setattr(replacement.history, "read", tracked)
    assert replacement.select_followups()["selected"] == (0 if already_selected else 1)
    assert replacement.get(task["id"])["result"] == done["result"]
    read_count = len(reads)
    assert replacement.select_followups() == {"selected": 0, "waiting": 0}
    assert len(reads) == read_count
    migration = lab.registry.db.execute("SELECT * FROM role_followup_backfill").fetchone()
    assert migration["cursor"] == migration["through"]
    assert lab.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0] == 2
    assert pg_store[0].reconcile()["balanced"]
    lab.registry.close()


def test_legacy_history_migration_is_bounded_and_restart_advances_cursor(
    pg_store, tmp_path, monkeypatch
):
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    lab = make_lab(pg_store[0], tmp_path)
    save_plan(tmp_path, plan_at(tmp_path))
    worker = RoleWorker(lab.registry, lab, NoChange())
    worker.enabled = True
    for i in range(12):
        worker.enqueue(Question(question=f"Retain older terminal software question {i}."))
        assert asyncio.run(worker.step())
    worker.history.rollover()
    with lab.registry.transaction():
        for trigger in ("role_followup_insert", "role_followup_update"):
            lab.registry.db.execute(f"DROP TRIGGER {trigger}")
        lab.registry.db.execute("DROP TABLE role_followups")
        lab.registry.db.execute("DROP TABLE role_followup_backfill")
    replacement = RoleWorker(lab.registry, lab)
    assert replacement.history.discover_followups() == 0
    migration = lab.registry.db.execute("SELECT * FROM role_followup_backfill").fetchone()
    assert migration["cursor"] == 8 and migration["through"] == 12
    restarted = RoleWorker(lab.registry, lab)
    assert restarted.history.discover_followups() == 0
    assert lab.registry.db.execute("SELECT cursor FROM role_followup_backfill").fetchone()[0] == 12
    assert restarted.history.discover_followups() == 0 and pg_store[0].reconcile()["balanced"]
    lab.registry.close()


def complete(worker, lab, task, at):
    recorder = EvidenceRecorder(lab.registry.path.parent / "research-evidence.sqlite")
    recorder.enqueue({"kind": "wire", "at": at, "source": "synthetic-two-generation-fixture"})
    asyncio.run(recorder.flush())
    for _ in range(5):
        assert asyncio.run(worker.step(at)), worker.get(task["id"])
    trials = []
    for i in range(1, 31):
        tick_lab(lab, at + i * 2)
        lab.step(at + i * 2)
        trials = [
            t
            for t in lab.paper.state["autonomous_lab"]["trials"].values()
            if t["proposal_id"] == "role-proposal-" + task["id"][5:]
        ]
        if trials and trials[0]["status"] == "active":
            break
    assert trials and trials[0]["status"] == "active", lab.inbox.page()
    score = close_window(lab, trials[0], "inconclusive")
    assert asyncio.run(worker.step(score["available_at"] + 1))
    assert asyncio.run(worker.step(score["available_at"] + 2))
    return worker.get(task["id"]), score


def test_two_generations_referenced_different_test_and_restart_dedupe(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(store, tmp_path, horizon_seconds=3600, hourly_compute_seconds=60)
    save_plan(tmp_path, plan_at(tmp_path))
    model = FollowupStub()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    first = worker.enqueue(
        Question(question="Compare the baseline then investigate a distinct supported mechanism."),
        START,
    )
    original = copy.deepcopy(lab.paper.state["accounts"]["primary"])
    done, score = complete(worker, lab, first, START)
    clock[0] = score["available_at"] + 3
    assert worker.select_followups() == {"selected": 1, "waiting": 0}
    replacement = RoleWorker(lab.registry, lab, model)
    replacement.enabled = True
    assert replacement.select_followups() == {"selected": 0, "waiting": 0}
    lessons = replacement.lessons.retrieve()["lessons"]
    second = replacement.get(lessons[0]["selection"]["next_task"])
    assert second["context"]["lesson"]["source"]["body"] == score
    assert set(second["context"]["catalog"]) == {"r1"}
    assert replacement._packet(second)[1]["evidence"]["e3"]["source_sha256"]
    second_done, second_score = complete(replacement, lab, second, clock[0])
    clock[0] = second_score["available_at"] + 3
    assert second_done["proposal"]["strategy"]["family"] == "range_reversion"
    assert replacement.select_followups() == {"selected": 0, "waiting": 1}
    assert len(replacement.lessons.retrieve()["lessons"]) == 2
    assert store.reconcile()["balanced"]
    for key in ("cash", "funding", "fees", "closed", "positions", "pending", "risk_policy"):
        assert lab.paper.state["accounts"]["primary"][key] == original[key]
    assert second_score["available_at"] > score["available_at"]
    assert len(model.calls) == 6
    lab.registry.close()


def test_retrieval_disclosure_access_not_weight_and_append_notes(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    worker = RoleWorker(lab.registry, lab, ModelStub())
    worker.enabled = True
    done, _ = complete(
        worker,
        lab,
        worker.enqueue(
            Question(
                question="Record an ordinary inconclusive comparison for supported retrieval."
            ),
            START,
        ),
        START,
    )
    identity = worker.lessons.record(done)
    clock[0] = done["result"]["outcome"]["body"]["available_at"] + 3
    before = worker.lessons.get(identity)
    after = worker.lessons.get(identity)
    assert (
        before["support"]
        == after["support"]
        == {"recorded_comparisons": 1, "independent_samples": None}
    )
    assert before["sha256"] == after["sha256"]
    assert after["access"]["reads"] == before["access"]["reads"] + 1
    assert worker.lessons.retrieve(outcome="inconclusive", horizon="short")["lessons"]
    assert not worker.lessons.retrieve(outcome="promising")["lessons"]
    first = worker.lessons.annotate(
        identity, "This explanatory annotation does not establish a recognition error."
    )
    second = worker.lessons.annotate(
        identity,
        "Additional interpretation supersedes the first; numerical facts remain fixed.",
        first,
    )
    assert worker.lessons.get(identity)["notes"][0]["seq"] == second
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        lab.registry.db.execute("UPDATE research_lessons SET outcome='promising'")
    assert (
        lab.registry.db.execute(
            "SELECT count(*) FROM evidence_windows WHERE origin='lesson disclosure'"
        ).fetchone()[0]
        == 1
    )
    assert worker.select_followups() == {"selected": 0, "waiting": 1}
    assert worker.select_followups() == {"selected": 0, "waiting": 0}
    lab.registry.close()


def test_data_wait_requires_changed_closed_source_not_refresh(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    worker = RoleWorker(lab.registry, lab, DataWaitStub())
    worker.enabled = True
    task = worker.enqueue(
        Question(
            question="Await a materially changed causal prefix before another model question."
        ),
        START,
    )
    assert asyncio.run(worker.step())
    assert worker.resume_sources(START + 1) == 0
    tick_lab(lab, START + 120)
    assert worker.resume_sources(START + 120) == 1
    assert worker.resume_sources(START + 121) == 0
    assert worker.get(task["id"])["stage"] == "complete"
    assert lab.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0] == 2
    assert worker.selection_metrics()["attempts"] == 1
    lab.registry.close()


def test_all_eight_data_waits_resume_atomically_after_restart_and_contention(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(store, tmp_path)
    model = DataWaitStub()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    tasks = [
        worker.enqueue(Question(question=f"Await new closed causal bars for question {i}."))
        for i in range(8)
    ]
    for _ in tasks:
        assert asyncio.run(worker.step())
    retained = {t["id"]: worker.get(t["id"])["attempts"] for t in tasks}
    assert all(worker.get(t["id"])["stage"] == "data_wait" for t in tasks)
    replacement = RoleWorker(lab.registry, lab, model)
    assert replacement.resume_sources(START + 120) == 0  # Clock alone is no new source.
    clock[0] += 120
    tick_lab(lab, clock[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda _: replacement.resume_sources(), range(2)))
    assert sum(counts) == 8
    assert replacement.resume_sources() == 0
    assert lab.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0] == 16
    assert (
        lab.registry.db.execute(
            "SELECT count(*) FROM role_tasks WHERE status NOT IN ('done','failed')"
        ).fetchone()[0]
        == 8
    )
    assert all(replacement.get(t["id"])["attempts"] == retained[t["id"]] for t in tasks)
    assert len(model.calls) == 8  # Polling/resume itself never invokes a model.
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_failed_successor_insert_retains_wait_and_retry_identity(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    worker = RoleWorker(lab.registry, lab, DataWaitStub())
    worker.enabled = True
    task = worker.enqueue(Question(question="Await more closed bars with retained failure proof."))
    assert asyncio.run(worker.step())
    before = worker.get(task["id"])
    tick_lab(lab, START + 120)
    lab.registry.db.execute(
        "CREATE TEMP TRIGGER fail_successor BEFORE INSERT ON role_tasks "
        "BEGIN SELECT RAISE(ABORT,'Injected successor failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="Injected successor"):
        worker.resume_sources(START + 120)
    assert worker.get(task["id"]) == before
    lab.registry.db.execute("DROP TRIGGER fail_successor")
    assert worker.resume_sources(START + 120) == 1
    assert worker.resume_sources(START + 120) == 0
    assert lab.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0] == 2
    lab.registry.close()


def test_typed_outcome_wait_requires_recorded_maturity_and_discloses_before_resume(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    pending = admit(lab, START)
    model = DataWaitStub()
    model.dependency = "mature_outcome"
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    task = worker.enqueue(
        Question(question="Wait for the offered comparison's actual mature outcome.")
    )
    assert asyncio.run(worker.step())
    requirement = worker.get(task["id"])["result"]["wait_requirement"]
    assert requirement["trial_id"] == pending["id"]
    prior_bars = lab.paper.history["BTCUSD"]
    lab.paper.history["BTCUSD"] = bars_at(START + 120)
    assert worker.resume_sources(START + 120) == 0  # More prices cannot stand in for labels.
    lab.paper.history["BTCUSD"] = prior_bars
    score = close_window(lab, pending, "inconclusive")
    assert worker.resume_sources(score["available_at"] - 1) == 0
    clock[0] = score["available_at"] + 1
    assert worker.resume_sources() == 1
    successor = lab.registry.db.execute(
        "SELECT id FROM role_tasks WHERE stage='idea' AND status='queued'"
    ).fetchone()[0]
    assert worker.get(successor)["context"]["dependency_evidence"]["body"] == score
    assert lab.registry.db.execute(
        "SELECT 1 FROM evidence_windows WHERE request_id=?",
        ("role-dependency:" + successor,),
    ).fetchone()
    assert worker.resume_sources() == 0 and len(model.calls) == 1
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_new_unbound_data_dependency_fails_with_answer_retained_and_slot_released(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    model = DataWaitStub()
    model.dependency = "Await labels and candles without a permitted condition identity"
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    task = worker.enqueue(
        Question(question="An ambiguous condition must not infer unseen evidence.")
    )
    assert not asyncio.run(worker.step())
    failed = worker.get(task["id"])
    assert failed["status"] == "failed"
    assert "offered wait requirement" in failed["reason"]
    assert failed["attempts"][0]["status"] == "failed"
    assert json.loads(failed["attempts"][0]["response"])["answer"]["dependency"] == model.dependency
    tick_lab(lab, START + 120)
    assert worker.resume_sources(START + 120) == 0
    worker.enqueue(Question(question="A valid successor can use the released active slot."))
    assert len(model.calls) == 1
    lab.registry.close()


def test_unbound_historical_text_does_not_infer_maturity(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    worker = RoleWorker(lab.registry, lab, DataWaitStub())
    task = worker.enqueue(Question(question="Retain an earlier unbound historical data wait."))
    # Legacy saved state, not a response accepted by the current contract.
    worker._update(
        task,
        "data_wait",
        "waiting",
        result={"answer": {"dependency": "Await unknown labels"}, "wait_requirement": None},
    )
    before = worker.get(task["id"])
    tick_lab(lab, START + 120)
    assert worker.resume_sources(START + 120) == 0
    assert worker.get(task["id"]) == before
    assert worker.transport.calls == []
    lab.registry.close()


def test_selection_allowance_totals_survive_history_rollover(pg_store, tmp_path, monkeypatch):
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(pg_store[0], tmp_path)
    save_plan(tmp_path, plan_at(tmp_path))
    worker = RoleWorker(lab.registry, lab, NoChange())
    worker.enabled = True
    for i in range(2):
        worker.enqueue(
            Question(question=f"Keep the charged allowance for historical question {i}.")
        )
        assert asyncio.run(worker.step())
    before = worker.selection_metrics()
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    worker.history.rollover()
    assert lab.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0
    assert worker.selection_metrics() == before
    assert before["attempts"] == 2 and before["reserved_token_allowance"] == 16384
    lab.registry.close()
