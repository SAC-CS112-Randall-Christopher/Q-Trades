"""Two-generation source proof with real disposable paper authority and model stub."""

import asyncio
import copy
import sqlite3

import pytest
from test_autonomous_lab import close_window, tick_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_role_worker import ModelStub, make_lab

from trading.evidence_runtime import EvidenceRecorder
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker


class FollowupStub(ModelStub):
    def infer(self, role, packet, profile):
        result = super().infer(role, packet, profile)
        if role == "researcher" and "e1" in packet["evidence"]:
            result["answer"].update(action="propose_experiment", capability="r1")
        elif role == "researcher" and "e3" in packet["evidence"]:
            result["answer"].update(capability="r1")
        return result


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
    worker = RoleWorker(lab.registry, lab, ModelStub())
    task = worker.enqueue(
        Question(
            question="Await a materially changed causal prefix before another model question."
        ),
        START,
    )
    worker._update(task, "data_wait", "waiting", reason="Await newly closed bars")
    assert worker.resume_sources(START + 1) == 0
    tick_lab(lab, START + 120)
    assert worker.resume_sources(START + 120) == 1
    assert worker.resume_sources(START + 121) == 0
    assert worker.get(task["id"])["stage"] == "complete"
    assert lab.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0] == 2
    assert not worker.selection_metrics()["attempts"]
    lab.registry.close()
