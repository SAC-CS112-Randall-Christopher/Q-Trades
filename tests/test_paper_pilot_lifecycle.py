"""Owned PostgreSQL paper lifecycle with software pilot answers; no actual model."""

import asyncio
import copy

from test_autonomous_lab import close_window, tick_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_role_worker import ModelStub, make_lab

from trading.evidence_runtime import EvidenceRecorder
from trading.research_storage import save_plan
from trading.role_worker import PAPER_RESEARCH_PILOT, Question, RoleWorker


class PilotCycleFixture(ModelStub):
    paper_pilot = True

    def policy(self):
        return {"grant_id": "synthetic-lifecycle-grant", "enabled": True}


def test_pilot_ordinary_paper_inbox_and_mature_outcome_keep_existing_financial_owner(
    pg_store, tmp_path, monkeypatch
):
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    recorder.enqueue({"kind": "wire", "at": START, "source": "synthetic-pilot-lifecycle"})
    asyncio.run(recorder.flush())
    model = PilotCycleFixture()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    worker.paper_admission = lambda: True
    lab.can_research = lambda: False  # Optional worker admission cannot relax this owner.
    originals = copy.deepcopy(lab.paper.state["accounts"])
    task = worker.enqueue(
        Question(question="Compare the issued method using the existing ordinary paper owner."),
        START,
    )
    try:
        for _ in range(5):
            assert asyncio.run(worker.step(START))
        submitted = worker.get(task["id"])
        assert submitted["stage"] == "outcome"
        assert submitted["context"]["execution_mode"] == PAPER_RESEARCH_PILOT
        assert submitted["context"]["qualified"] is False
        assert lab.paper.state["accounts"] == originals
        lab.step(START + 1)
        assert lab.paper.state["autonomous_lab"]["trials"] == {}
        assert asyncio.run(worker.step(START + 2))
        assert worker.get(task["id"])["stage"] == "outcome"
        assert worker.get(task["id"])["status"] == "waiting"
        assert model.calls == ["researcher", "reviewer"]
        # Only the existing financial owner admits/funds the ordinary comparison.
        lab.can_research = lambda: True
        for i in range(1, 10):
            # Respect the actual owner's persisted thirty-second refusal backoff.
            clock[0] = START + 31 + i * 2
            recorder.enqueue(
                {"kind": "wire", "at": clock[0], "source": "synthetic-pilot-lifecycle"}
            )
            asyncio.run(recorder.flush())
            tick_lab(lab, clock[0])
            lab.step(clock[0])
            trials = list(lab.paper.state["autonomous_lab"]["trials"].values())
            if trials and trials[0]["status"] == "active":
                break
        assert trials and trials[0]["status"] == "active", lab.last_error
        assert len(lab.paper.state["accounts"]) <= 20
        score = close_window(lab, trials[0], "inconclusive")
        assert asyncio.run(worker.step(score["available_at"] + 31))
        assert asyncio.run(worker.step(score["available_at"] + 32))
        completed = worker.get(task["id"])
        assert completed["status"] == "done"
        assert completed["result"]["outcome"]["body"] == score
        assert completed["result"]["followup"]["action"] == "no_change"
        assert completed["context"]["qualified"] is False
        assert model.calls == ["researcher", "reviewer", "researcher"]
        assert store.reconcile()["balanced"]
        for name, account in originals.items():
            assert {
                k: v for k, v in lab.paper.state["accounts"][name].items() if k != "valuation_at"
            } == {k: v for k, v in account.items() if k != "valuation_at"}
    finally:
        lab.registry.close()
