"""Normal role packets must pass real transport sizing, without any network call."""

import asyncio
import copy
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_autonomous_lab import admit, close_window, tick_lab
from test_local_roles import declared
from test_memory_quality import fitted
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_role_worker import ModelStub, make_lab

from trading.api import create_app
from trading.config import Settings
from trading.evidence_runtime import EvidenceRecorder
from trading.lab_role_contract import packet_json
from trading.local_role_model import LocalRoles
from trading.memory_quality import validate_artifact
from trading.research_evidence import digest
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker


class NoNetwork(RuntimeError):
    pass


class MemoryStub(ModelStub):
    def infer(self, role, packet, profile):
        answer = super().infer(role, packet, profile)
        if role == "researcher" and "e1" not in packet["evidence"]:
            answer["answer"]["capability"] = "r2"
        return answer


def assert_transport_accepts(worker, task, tmp_path, monkeypatch):
    role, packet = worker._packet(task)
    print(
        json.dumps(
            {
                "role": role,
                "packet_bytes": len(packet_json(packet).encode()),
                "parts": {k: len(json.dumps(v).encode()) for k, v in packet.items()},
                "evidence_parts": {
                    k: len(json.dumps(v).encode()) for k, v in packet["evidence"].items()
                },
            }
        )
    )
    transport = LocalRoles(tmp_path)

    def stop_before_network(profile):
        raise NoNetwork("Passed real size check; all observation/network calls prohibited")

    monkeypatch.setattr(transport, "observe", stop_before_network)
    with pytest.raises(NoNetwork):
        transport.infer(role, packet, declared())
    print(
        json.dumps(
            {
                "role": role,
                "stage": task["stage"],
                "preflight": transport.preflight(role, packet, declared()),
            }
        )
    )
    return packet


@pytest.mark.parametrize("library_rows", [12, 128])
@pytest.mark.parametrize("maximum_question", [False, True])
def test_memory_and_followup_packets_pass_actual_adapter_before_network(
    pg_store, tmp_path, monkeypatch, library_rows, maximum_question
):
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600, hourly_compute_seconds=60)
    save_plan(tmp_path, plan_at(tmp_path))
    capture = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    capture.enqueue({"kind": "wire", "at": START, "source": "synthetic-preflight-fixture"})
    asyncio.run(capture.flush())
    plan, rows, result, artifact = fitted()
    if library_rows == 128:
        # Declared maximum-size synthetic fixture; not 128 measured market groups.
        library = []
        for i in range(128):
            row = copy.deepcopy(artifact["library"][i % 12])
            row.update(
                group=f"qa-size-{i}",
                episode=f"qa-size-{i}",
                at=artifact["train_end"] - (128 - i) * 5000,
                available_at=artifact["train_end"] - (128 - i) * 5000 + 2701,
            )
            library.append(row)
        artifact["library"] = library
        artifact.pop("sha256")
        artifact["sha256"] = digest(artifact)
        result["candidate_group"] = [result["candidate_group"][0]]
    validate_artifact(artifact)
    plan = plan.model_copy(update={"numerical_daily_usd": "0", "contextual_daily_usd": "0"})
    lab.registry.reserve(plan, "synthetic-preflight-source")
    lab.registry.inputs(plan.request_id, {"episodes": rows, "scope": "Synthetic size fixture"})
    job = lab.registry.claim()
    assert job and lab.registry.finish(plan.request_id, job["lease"], result, None)
    worker = RoleWorker(lab.registry, lab, ModelStub())
    worker.enabled = True
    ordinary = worker.enqueue(
        Question(question="Check an ordinary bounded role packet before inference.")
    )
    assert_transport_accepts(worker, ordinary, tmp_path, monkeypatch)
    for _ in range(3):
        assert asyncio.run(worker.step())
    assert_transport_accepts(worker, worker.get(ordinary["id"]), tmp_path, monkeypatch)
    worker._update(worker.get(ordinary["id"]), "complete", "done", reason="Preflight control only")
    assert worker.get(ordinary["id"])["status"] == "done"
    worker.transport = MemoryStub()
    parent = admit(lab, START)
    score = close_window(lab, parent, "promising")
    clock[0] = score["available_at"] + 4
    tick_lab(lab, clock[0])
    task = worker.enqueue(
        Question(
            question=("Compare supported frozen memory with its preserved parent. " * 12)[:500]
            if maximum_question
            else "Compare the supported frozen memory filter with its preserved parent.",
            parent=parent["id"],
        )
    )
    assert "r2" in task["context"]["catalog"]
    researcher = assert_transport_accepts(worker, task, tmp_path, monkeypatch)
    for _ in range(3):
        assert asyncio.run(worker.step()), worker.get(task["id"])["reason"]
    review = worker.get(task["id"])
    assert review["stage"] == "review"
    assert (
        review["proposal"]["strategy"]["entry_filter"]["artifact"]["sha256"] == artifact["sha256"]
    )
    reviewer = assert_transport_accepts(worker, review, tmp_path, monkeypatch)
    capture.enqueue({"kind": "wire", "at": clock[0], "source": "synthetic-preflight-fixture"})
    asyncio.run(capture.flush())
    for _ in range(2):
        assert asyncio.run(worker.step())
    trials = []
    for i in range(1, 25):
        tick_lab(lab, clock[0] + i * 2)
        lab.step(clock[0] + i * 2)
        trials = [
            t
            for t in lab.paper.state["autonomous_lab"]["trials"].values()
            if t["proposal_id"] == "role-proposal-" + task["id"][5:]
        ]
        if trials and trials[0]["status"] == "active":
            break
    assert trials and trials[0]["status"] == "active", lab.last_error
    score = close_window(lab, trials[0], "inconclusive")
    clock[0] = score["available_at"] + 1
    assert asyncio.run(worker.step())
    assert_transport_accepts(worker, worker.get(task["id"]), tmp_path, monkeypatch)
    assert asyncio.run(worker.step())
    completed = worker.get(task["id"])
    lesson = worker.lessons.record(completed)
    next_task = worker.enqueue(
        Question(
            question="Test a supported different mechanism using the recorded memory comparison.",
            parent=parent["id"],
            lesson=lesson,
        )
    )
    assert_transport_accepts(worker, next_task, tmp_path, monkeypatch)
    assert completed["proposal"]["strategy"]["entry_filter"]["artifact"] == artifact
    assert (
        json.loads(
            lab.registry.db.execute(
                "SELECT body FROM role_components WHERE sha256=?", (artifact["sha256"],)
            ).fetchone()[0]
        )
        == artifact
    )
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.lab.roles = worker
        saved = []
        offset = 0
        while offset is not None:
            page = client.get(f"/api/lab/roles/tasks/{task['id']}/components/r2?offset={offset}")
            assert page.status_code == 200
            body = page.json()
            assert body["artifact_sha256"] == artifact["sha256"]
            assert len(body["library"]) <= 8
            saved.extend(body["library"])
            offset = body["next_offset"]
        assert saved == artifact["library"]
        assert client.get(f"/api/lab/roles/tasks/{task['id']}/components/r0").status_code == 404
    assert (
        lab.registry.db.execute(
            "SELECT count(*) FROM evidence_windows WHERE origin='role component disclosure'"
        ).fetchone()[0]
        == 1
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        lab.registry.db.execute("UPDATE role_components SET body='{}'")
    assert '"library"' not in json.dumps(researcher) + json.dumps(reviewer)
    assert store.reconcile()["balanced"]
    lab.registry.close()
