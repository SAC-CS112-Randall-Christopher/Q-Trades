"""Owned procedural children, retained failure resources and normal API reopening.

These children never import a loader, touch trained weights or call a provider.
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_peft_development import declared as declared

from trading.api import create_app
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import DevelopmentTransportFailure
from trading.role_worker import RoleWorker

TASK = "role-" + "7" * 32
PACKET = {
    "question": "Which limitations follow from this procedural evidence?",
    "capabilities": {},
    "evidence": {"e0": {"basis": "procedural_qa", "fact": "No market outcome measured"}},
}
ANSWER = {
    "action": "no_change",
    "evidence_ids": ["e0"],
    "capability": None,
    "mechanism": "No causal outcome exists in the procedural evidence.",
    "falsification": "An independently supported outcome would change this limitation.",
    "rationale": "This software fixture cannot establish useful market evidence.",
    "dependency": None,
}


@pytest.fixture
def failure_task(declared, monkeypatch):
    model, _, _ = declared
    registry = ExperimentRegistry(model.directory / "registry.sqlite")
    worker = RoleWorker(registry, None)
    with registry.transaction():
        registry.db.execute(
            "INSERT INTO role_tasks(id,created,updated,stage,status,context) "
            "VALUES(?,?,?,'idea','queued',?)",
            (TASK, time.time(), time.time(), json.dumps({"question": PACKET["question"]})),
        )
    monkeypatch.setattr(worker, "_base_packet", lambda task: ("researcher", dict(PACKET)))
    try:
        yield model, worker
    finally:
        registry.close()


def response(profile, answer=None):
    return {
        "identity": profile["identity"],
        "settings_sha256": digest(PROFILE),
        "placement": {
            "device": "cpu",
            "precision": "float32",
            "priority_class": 64,
            "processors_allowed": 2,
            "adapter_active": ["default"],
            "adapter_weights_verified": True,
            "trainable_params": 0,
        },
        "complete": True,
        "raw_answer": "Original procedural answer",
        "answer": ANSWER if answer is None else answer,
        "peak_rss_bytes": 1,
    }


def child_launcher(monkeypatch, profile, fault, raw_answer=None):
    original_popen = subprocess.Popen
    children = []
    jobs = []
    code = """
import pathlib, sys, time
p = pathlib.Path(sys.argv[1])
while not (p/'owner-ready').exists(): time.sleep(.01)
time.sleep(.08)
if sys.argv[2] == 'timeout': time.sleep(30)
if sys.argv[2] == 'exit': sys.exit(7)
(p/'response.json').write_text(pathlib.Path(sys.argv[3]).read_text())
"""

    def launch(command, **kwargs):
        job = Path(command[-1])
        jobs.append(job)
        request = json.loads((job / "request.json").read_text())
        assert json.loads(request["packet_json"]) == PACKET
        value = {"request_sha256": digest(request), "response": response(profile)}
        if raw_answer is not None:
            value["response"]["raw_answer"] = raw_answer
        if fault == "identity":
            value["response"]["identity"] = {}
        elif fault == "invalid_answer":
            value["response"]["answer"] = {"bad": True}
        serialized = json.dumps(value)
        if fault == "receipt":
            serialized = "Invalid private receipt at " + str(job)
        fixture_input = job / "procedural-child-input.json"
        fixture_input.write_text(serialized)
        child = original_popen(
            [sys.executable, "-c", code, str(job), fault, str(fixture_input)], **kwargs
        )
        children.append(child)
        return child

    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launch)
    return children, jobs


@pytest.mark.parametrize(
    "fault,status",
    [
        ("timeout", "timeout"),
        ("exit", "child_exit"),
        ("identity", "model_identity"),
        ("receipt", "response_receipt"),
    ],
)
def test_actual_failed_child_retains_resources_once_and_reopens_in_normal_api(
    failure_task, monkeypatch, fault, status
):
    model, worker = failure_task
    cfg, selected, profile = model.declaration()
    if fault == "timeout":
        profile = profile | {"timeout_seconds": 0.4}
        monkeypatch.setattr(model, "declaration", lambda: (cfg, selected, profile))
    children, jobs = child_launcher(monkeypatch, profile, fault)
    before = worker.get(TASK)
    with pytest.raises(DevelopmentTransportFailure) as caught:
        asyncio.run(worker.development_answer(TASK, model))
    assert len(children) == 1 and children[0].poll() is not None
    saved = worker.get(TASK)
    attempt = saved["attempts"][0]
    receipt = json.loads(attempt["response"])
    assert receipt == caught.value.receipt
    assert receipt["kind"] == "development_transport_failure" and receipt["complete"] is False
    assert receipt["status"] == status
    assert 0 < receipt["wall_seconds"] < 10
    assert receipt["rss_observations"] > 0 and receipt["peak_rss_bytes"] > 0
    assert receipt["exit_code"] == children[0].returncode
    assert receipt["child_terminated"] is True and receipt["cleanup_complete"] is True
    assert receipt["profile_sha256"] == digest(profile)
    assert receipt["private_job"] == jobs[0].name and len(receipt["private_job"]) == 32
    private = json.loads((jobs[0] / "dispatch.json").read_text())
    assert {key: private[key] for key in receipt} == receipt
    assert private["reason"].startswith(receipt["exception_type"] + ": ")
    assert len(json.dumps(receipt).encode()) <= 2048
    assert json.loads(attempt["packet"]) == PACKET
    assert json.loads(attempt["profile"]) == profile
    assert attempt["status"] == "failed" and attempt["finished"] > attempt["started"]
    for key in ("stage", "status", "context", "result", "proposal", "evaluation"):
        assert saved[key] == before[key]
    assert (
        worker.registry.db.execute("SELECT count(*) FROM role_attempt_allowances").fetchone()[0]
        == 1
    )
    with pytest.raises(ValueError, match="transport failed; no invisible retry"):
        asyncio.run(worker.development_answer(TASK, model))
    assert len(children) == 1 and worker.get(TASK)["attempts"][0] == attempt
    app = create_app(Settings(), model.directory / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.lab = SimpleNamespace(roles=worker)
        page = client.get(f"/api/lab/roles/tasks/{TASK}")
        assert page.status_code == 200
        exposed = page.json()["attempts"][0]
        assert exposed["response"] == receipt and exposed["profile"] == profile
        assert exposed["status"] == "failed" and "packet" not in exposed
        assert str(model.directory) not in page.text and str(jobs[0]) not in page.text
        assert str(Path(cfg["private_root"])) not in page.text
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with worker.registry.transaction():
            worker.registry.db.execute(
                "UPDATE role_attempts SET response='{}' WHERE task=?", (TASK,)
            )


def test_unsampled_failure_rss_remains_unknown(failure_task, monkeypatch):
    model, worker = failure_task
    profile = model.declaration()[2]
    child_launcher(monkeypatch, profile, "exit")
    monkeypatch.setattr("trading.peft_role_model.child_rss", lambda pid: 0)
    with pytest.raises(DevelopmentTransportFailure):
        asyncio.run(worker.development_answer(TASK, model))
    receipt = worker.view(TASK)["attempts"][0]["response"]
    assert receipt["rss_observations"] == 0 and receipt["peak_rss_bytes"] is None
    assert receipt["exit_code"] == 7 and receipt["status"] == "child_exit"


def test_semantically_invalid_original_answer_stays_original_and_failed(failure_task, monkeypatch):
    model, worker = failure_task
    profile = model.declaration()[2]
    children, jobs = child_launcher(monkeypatch, profile, "invalid_answer")
    for _ in range(2):
        with pytest.raises(ValueError):
            asyncio.run(worker.development_answer(TASK, model))
    attempt = worker.view(TASK)["attempts"][0]
    assert attempt["status"] == "failed"
    assert attempt["response"]["answer"] == {"bad": True}
    assert attempt["response"]["complete"] is True
    assert attempt["response"]["raw_answer"] == "Original procedural answer"
    assert "transport_failure" not in attempt["response"] and len(children) == 1
    assert json.loads((jobs[0] / "dispatch.json").read_text())["status"] == "answered"


@pytest.mark.parametrize("fault", ["close", "dispatch"])
@pytest.mark.parametrize("near_bound", [False, True])
def test_cleanup_failure_preserves_original_answer_and_honest_failed_status(
    failure_task, monkeypatch, fault, near_bound
):
    model, worker = failure_task
    profile = model.declaration()[2]
    raw = "Original procedural answer" + ("x" * 30800 if near_bound else "")
    children, jobs = child_launcher(monkeypatch, profile, "valid", raw)
    from trading.peft_child_owner import ChildOwner

    close = ChildOwner.close

    def failed_after_close(self):
        close(self)
        raise OSError("Procedural private cleanup path must not be published")

    if fault == "close":
        monkeypatch.setattr("trading.peft_role_model.ChildOwner.close", failed_after_close)
    else:
        write_text = Path.write_text

        def failed_private_dispatch(self, *args, **kwargs):
            if self.name == "dispatch.json":
                raise OSError("Procedural private dispatch path must not be published")
            return write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", failed_private_dispatch)
    with pytest.raises(DevelopmentTransportFailure) as failed:
        asyncio.run(worker.development_answer(TASK, model))
    assert failed.value.response is not None
    assert len(json.dumps(failed.value.response, sort_keys=True).encode()) <= 32768
    attempt = worker.view(TASK)["attempts"][0]
    original = attempt["response"]
    assert original["answer"] == ANSWER and original["raw_answer"] == raw
    assert original["complete"] is True and attempt["status"] == "failed"
    receipt = original["transport_failure"]
    assert receipt["status"] == ("cleanup" if fault == "close" else "dispatch_receipt")
    assert receipt["cleanup_complete"] is (fault != "close")
    assert receipt["cleanup_error_types"] == (["OSError"] if fault == "close" else [])
    assert receipt["child_terminated"] is True
    assert "must not be published" not in json.dumps(attempt)
    bounded_original = {key: value for key, value in original.items() if key != "transport_failure"}
    assert len(json.dumps(bounded_original, sort_keys=True).encode()) <= 32768
    assert len(json.dumps({"transport_failure": receipt}, sort_keys=True).encode()) <= 2048
    assert len(json.dumps(original, sort_keys=True).encode()) <= 34816
    if near_bound:
        assert len(json.dumps(original, sort_keys=True).encode()) > 32768
    else:
        assert len(json.dumps(original, sort_keys=True).encode()) < 32768
    private_response = json.loads((jobs[0] / "response.json").read_text())["response"]
    assert private_response["answer"] == original["answer"]
    assert private_response["raw_answer"] == original["raw_answer"]
    app = create_app(Settings(), model.directory / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.lab = SimpleNamespace(roles=worker)
        page = client.get(f"/api/lab/roles/tasks/{TASK}")
        assert page.status_code == 200 and page.json()["attempts"][0]["response"] == original
    with pytest.raises(ValueError, match="transport failed; no invisible retry"):
        asyncio.run(worker.development_answer(TASK, model))
    assert len(children) == 1
