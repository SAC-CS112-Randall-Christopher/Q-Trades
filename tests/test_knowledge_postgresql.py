"""Full disposable financial/role continuation with RAG; stubs are not model proof."""

import asyncio
import copy

from test_autonomous_lab import close_window, tick_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_persistent_research import dispatch, note, policy, response
from test_research_storage import plan_at
from test_role_worker import ModelStub, make_lab

from trading.evidence_runtime import EvidenceRecorder
from trading.research_knowledge import ResearchKnowledge
from trading.research_reviews import ResearchReviews, ReviewDecision
from trading.research_storage import ResearchStorage, save_plan
from trading.role_worker import Question, RoleWorker


def test_real_role_producer_after_review_retrieves_accepted_annotation(
    pg_store, tmp_path, monkeypatch
):
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    storage = ResearchStorage(plan)
    knowledge = ResearchKnowledge(storage)
    knowledge.ingest(note())
    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    recorder.enqueue({"kind": "wire", "at": START, "source": "synthetic-persistent-role-QA"})
    asyncio.run(recorder.flush())
    model = ModelStub()
    worker = RoleWorker(lab.registry, lab, model)
    worker.knowledge = knowledge
    worker.enabled = True
    original = copy.deepcopy(lab.paper.state["accounts"]["primary"])
    task = worker.enqueue(
        Question(question="Do transaction costs and nonfills limit the matched causal evidence?"),
        START,
    )
    assert worker.get(task["id"])["context"]["knowledge"]["passages"]
    for _ in range(5):
        assert asyncio.run(worker.step(START))
    for i in range(1, 5):
        clock[0] = START + i * 2
        tick_lab(lab, clock[0])
        lab.step(clock[0])
    trial = next(
        t
        for t in lab.paper.state["autonomous_lab"]["trials"].values()
        if t["proposal_id"] == "role-proposal-" + task["id"][5:]
    )
    score = close_window(lab, trial, "inconclusive")
    clock[0] = score["available_at"] + 1
    assert asyncio.run(worker.step(clock[0]))
    clock[0] += 1
    assert asyncio.run(worker.step(clock[0]))
    assert worker.get(task["id"])["stage"] == "complete"
    reviews = ResearchReviews(worker, knowledge)
    worker.reviews = reviews
    run = reviews.reserve(task["id"], "fixture:financial-role-continuation", policy())
    dispatch(reviews, run)
    reviews.retain(run["id"], response(run))
    before_review_effects = copy.deepcopy(store.read())
    reviews.decide(
        run["id"],
        ReviewDecision(
            expected_revision=0,
            disposition="accept_annotation",
            reason="Operator checked procedural findings; no market/model proof claimed.",
        ),
    )
    source = reviews.get(run["id"])["correction"][0]["source"]
    reviews.continue_questions()
    reviews.continue_questions()
    follow = reviews.get(run["id"])["followups"][0]
    assert follow["state"] == "queued", follow
    child = worker.get(follow["task"])
    assert any(p["source"] == source for p in child["context"]["knowledge"]["passages"])
    assert worker._packet(child)[1]["retrieval_contract"] == "source-rag-v1"
    assert store.read() == before_review_effects and store.reconcile()["balanced"]
    assert {
        k: v for k, v in store.read()["accounts"]["primary"].items() if k != "valuation_at"
    } == {k: v for k, v in original.items() if k != "valuation_at"}
    assert model.calls == ["researcher", "reviewer", "researcher"]
    storage.close()
    lab.registry.close()
