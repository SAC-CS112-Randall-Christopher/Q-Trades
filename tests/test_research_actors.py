"""Scoped local HTTP adapter/real disposable paper proof; no actual Crik transport."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_autonomous_lab import close_window, tick_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_role_worker import ModelStub, make_lab

from trading.api import create_app
from trading.config import Settings
from trading.evidence_runtime import EvidenceRecorder
from trading.research_actors import ActorAnswer, ActorGrant, ResearchActors
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker


@pytest.fixture
def scope(pg_store, tmp_path, monkeypatch):
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    recorder.enqueue({"kind": "wire", "at": START, "source": "synthetic-external-adapter"})
    asyncio.run(recorder.flush())
    model = ModelStub()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    task = worker.enqueue(
        Question(question="Compare the reviewed prospective rules with matched costs."), START
    )
    actors = ResearchActors(worker)
    grant = actors.grant(
        ActorGrant(
            actor="qa-external",
            tasks=[task["id"]],
            processing_location="Local disposable adapter QA; no external service",
        )
    )
    yield SimpleNamespace(
        store=store,
        lab=lab,
        model=model,
        worker=worker,
        task=task,
        actors=actors,
        grant=grant,
        clock=clock,
        directory=tmp_path,
    )
    lab.registry.close()


def answer(scope, claim, **change):
    packet = claim["packet"]
    value = scope.model.infer("researcher", packet, {})["answer"]
    scope.model.calls.clear()
    return ActorAnswer(claim=claim["claim"], answer=value | change)


def test_http_external_proposal_normal_paper_outcome_and_granted_result(scope):
    s = scope
    original = copy.deepcopy(s.lab.paper.state["accounts"]["primary"])
    app = create_app(Settings(), s.directory / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.lab.roles = s.worker
        headers = {"Authorization": "Bearer " + s.grant["token"]}
        route = "/api/research/actors/tasks/claim"
        assert client.post(route, json={"task": s.task["id"]}).status_code == 403
        claim = client.post(route, json={"task": s.task["id"]}, headers=headers).json()
        assert "DSN" not in json.dumps(claim) and "context" not in claim and "catalog" not in claim
        assert not asyncio.run(s.worker.step(START))  # Shared ownership prevents local inference.
        command = answer(s, claim).model_dump()
        delivered = client.post("/api/research/actors/answers", json=command, headers=headers)
        assert delivered.status_code == 200 and delivered.json()["status"] == "recorded"
        assert (
            client.post("/api/research/actors/answers", json=command, headers=headers).json()[
                "status"
            ]
            == "already_recorded"
        )
        for _ in range(5):
            assert asyncio.run(s.worker.step(START))
        assert s.model.calls == ["reviewer"]  # Same required review, no new researcher verdict.
        for i in range(1, 5):
            tick_lab(s.lab, START + i * 2)
            s.lab.step(START + i * 2)
        trial = (
            next(
                t
                for t in s.lab.paper.state["autonomous_lab"]["trials"].values()
                if t["proposal_id"] == "role-proposal-" + s.task["id"][5:]
            )
            if s.lab.paper.state["autonomous_lab"]["trials"]
            else None
        )
        assert trial is not None, {
            "inbox": [(p["status"], p["reason"]) for p in s.lab.inbox.page()["proposals"]],
            "controller": s.lab.paper.state["autonomous_lab"]["reason"],
            "error": s.lab.last_error,
        }
        assert trial["status"] == "active"
        score = close_window(s.lab, trial, "inconclusive")
        s.clock[0] = score["available_at"] + 1
        assert asyncio.run(s.worker.step())
        # Mature outcomes can outlive a credential; reconnect requires a fresh
        # explicit local grant, never an automatic extension of external access.
        fresh = s.actors.grant(
            ActorGrant(
                actor="qa-external", tasks=[s.task["id"]], processing_location="Local adapter QA"
            )
        )
        headers = {"Authorization": "Bearer " + fresh["token"]}
        follow = s.actors.claim(fresh["token"], s.task["id"])
        assert "e1" in follow["packet"]["evidence"]
        s.actors.answer(fresh["token"], answer(s, follow))
        assert asyncio.run(s.worker.step())
        result = client.get(
            f"/api/research/actors/tasks/{s.task['id']}/result", headers=headers
        ).json()
        assert result["status"] == "done" and result["result"]["outcome"]["body"] == score
        assert result["result"]["followup"]["action"] == "no_change"
        assert "attempts" not in result and "context" not in result
        assert (
            s.lab.registry.db.execute(
                "SELECT count(*) FROM evidence_windows WHERE origin='role task disclosure'"
            ).fetchone()[0]
            == 1
        )
        assert (
            s.lab.registry.db.execute(
                "SELECT count(*) FROM lab_proposals WHERE request_id=?",
                ("role-proposal-" + s.task["id"][5:],),
            ).fetchone()[0]
            == 1
        )
        assert (
            s.store.connection.execute(
                "SELECT count(*) FROM paper_events WHERE kind='lab_trial_funded' "
                "AND body->>'trial_id'=%s",
                (trial["id"],),
            ).fetchone()["count"]
            == 1
        )
    assert {
        k: v for k, v in s.lab.paper.state["accounts"]["primary"].items() if k != "valuation_at"
    } == {k: v for k, v in original.items() if k != "valuation_at"}
    assert s.store.reconcile()["balanced"]


def test_scope_actor_spoofing_urls_operator_and_revoked_access_fail(scope):
    s = scope
    before = s.store.read()
    other = s.worker.enqueue(
        Question(question="An unrelated permitted deterministic research question."), START
    )
    with pytest.raises(ValueError, match="outside"):
        s.actors.claim(s.grant["token"], other["id"])
    app = create_app(Settings(), s.directory / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.lab.roles = s.worker
        headers = {"Authorization": "Bearer " + s.grant["token"], "X-Local-Operator": "1"}
        assert (
            client.post(
                "/api/research/actors/grants", headers=headers, json=s.grant["scope"]
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/autonomous/control",
                headers=headers,
                json={"action": "pause", "target": "all"},
            ).status_code
            == 403
        )
        for extra in (
            {"actor": "operator"},
            {"url": "http://127.0.0.1/private"},
            {"tool": "delete"},
        ):
            assert (
                client.post(
                    "/api/research/actors/tasks/claim",
                    headers=headers,
                    json={"task": s.task["id"]} | extra,
                ).status_code
                == 422
            )
        assert (
            client.get(
                f"/api/research/actors/tasks/{other['id']}/result", headers=headers
            ).status_code
            == 403
        )
        assert client.get("/api/lab/roles/tasks/" + other["id"], headers=headers).status_code == 403
        assert (
            client.get("/api/research/actors/tasks/maintenance", headers=headers)
            .json()["authority"]
            .startswith("No delete")
        )
    s.actors.revoke(s.grant["id"])
    with pytest.raises(ValueError, match="revoked"):
        s.actors.result(s.grant["token"], s.task["id"])
    assert s.store.read() == before


def test_lease_expiry_unknown_completion_explicit_retry_and_stale_answer(scope):
    s = scope
    claim = s.actors.claim(s.grant["token"], s.task["id"])
    response = answer(s, claim)
    s.clock[0] += 91
    with pytest.raises(ValueError, match="expired"):
        s.actors.answer(s.grant["token"], response)
    assert not asyncio.run(s.worker.step())
    assert "unknown" in s.worker.get(s.task["id"])["reason"]
    s.worker.retry(s.task["id"])
    replacement = ResearchActors(s.worker)
    claim2 = replacement.claim(s.grant["token"], s.task["id"])
    with pytest.raises(ValueError, match="expired"):
        replacement.answer(s.grant["token"], response)
    replacement.answer(s.grant["token"], answer(s, claim2))
    assert asyncio.run(s.worker.step())
    assert s.worker.get(s.task["id"])["stage"] == "evaluate"
    assert len(s.worker.get(s.task["id"])["attempts"]) == 2


def test_budget_and_renewal_persist_across_reconnect(scope):
    s = scope
    limited = s.actors.grant(
        ActorGrant(
            actor="qa-budget",
            tasks=[s.task["id"]],
            requests=2,
            processing_location="Local adapter QA",
        )
    )
    claim = s.actors.claim(limited["token"], s.task["id"])
    s.clock[0] += 60
    renewed = ResearchActors(s.worker).renew(limited["token"], claim["claim"])
    assert renewed["lease_until"] == START + 150
    row = s.lab.registry.db.execute(
        "SELECT wall_reserved FROM role_attempts WHERE task=?", (s.task["id"],)
    ).fetchone()
    assert row[0] == 150
    with pytest.raises(ValueError, match="allowance"):
        ResearchActors(s.worker).result(limited["token"], s.task["id"])
    assert (
        s.lab.registry.db.execute(
            "SELECT requests_used FROM research_actors WHERE id=?", (limited["id"],)
        ).fetchone()[0]
        == 2
    )


def test_invalid_external_output_retained_without_verdict_retry(scope):
    s = scope
    claim = s.actors.claim(s.grant["token"], s.task["id"])
    with pytest.raises(ValueError, match="Non-executable"):
        s.actors.answer(s.grant["token"], answer(s, claim, risk="unlimited"))
    task = s.worker.get(s.task["id"])
    assert task["status"] == "failed" and task["attempts"][0]["response"]
    with pytest.raises(ValueError, match="Completed verdicts"):
        s.worker.retry(s.task["id"])
    assert s.lab.inbox.page()["proposals"] == []


def test_external_capacity_does_not_block_independent_local_work(scope):
    s = scope
    tasks = [s.task["id"]] + [
        s.worker.enqueue(
            Question(
                question=f"Independent prospective mechanism number {i} with no prior verdict."
            ),
            START,
        )["id"]
        for i in range(3)
    ]
    grant = s.actors.grant(
        ActorGrant(actor="qa-capacity", tasks=tasks, processing_location="Local adapter QA")
    )
    s.actors.claim(grant["token"], tasks[0])
    s.actors.claim(grant["token"], tasks[1])
    with pytest.raises(ValueError, match="Two external"):
        s.actors.claim(grant["token"], tasks[2])
    assert asyncio.run(s.worker.step())
    assert any(s.worker.get(t)["stage"] == "evaluate" for t in tasks[2:])
    assert s.store.reconcile()["balanced"]


def test_revocation_keeps_financial_positions_history_and_answer(scope):
    s = scope
    claim = s.actors.claim(s.grant["token"], s.task["id"])
    s.actors.answer(s.grant["token"], answer(s, claim))
    for _ in range(5):
        assert asyncio.run(s.worker.step())
    for i in range(1, 5):
        tick_lab(s.lab, START + i * 2, eligible=True)
        s.lab.step(START + i * 2)
    tick_lab(s.lab, START + 11, eligible=True)
    before = s.store.read()
    assert any(a["positions"] or a["pending"] for a in before["accounts"].values())
    events = s.store.export(0, 1000)["records"]
    attempts = copy.deepcopy(s.worker.get(s.task["id"])["attempts"])
    s.actors.revoke(s.grant["id"])
    assert s.store.read() == before and s.store.export(0, 1000)["records"] == events
    assert s.worker.get(s.task["id"])["attempts"] == attempts
    assert s.store.reconcile()["balanced"]


def test_stale_local_worker_cannot_overwrite_external_answer(scope):
    s = scope
    stale = s.worker.get(s.task["id"]) | {"_claimed_owner": s.worker.owner}
    claim = s.actors.claim(s.grant["token"], s.task["id"])
    s.actors.answer(s.grant["token"], answer(s, claim))
    assert not s.worker._update(
        stale, "complete", "done", result={"invented": "stale local answer"}
    )
    assert s.worker.get(s.task["id"])["stage"] == "idea"
    assert asyncio.run(s.worker.step())
    assert s.worker.get(s.task["id"])["stage"] == "evaluate"
