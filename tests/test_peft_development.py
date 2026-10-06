"""Procedural metadata/answers and owned native child tests. No trained model calls."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_paper_store import pg_store as pg_store
from test_role_worker import ModelStub, make_lab

from trading.autonomous_lab import InputWait
from trading.ownership import CollectorLock
from trading.peft_child_owner import ChildOwner
from trading.peft_profile import NAME, PROFILE, digest
from trading.peft_role_model import PeftDevelopmentRoles
from trading.role_worker import Question, RoleWorker


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def declared(tmp_path, monkeypatch):
    private, lab, directory = tmp_path / "private", tmp_path / "lab", tmp_path / "development"
    lab.mkdir()
    source = lab / "src/llm_lab/handoff.py"
    source.parent.mkdir(parents=True)
    source.write_text("# Procedural source fixture, no loader or model.\n")
    python = lab / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"procedural interpreter marker")
    base, run = private / "base", private / "run"
    base.mkdir(parents=True)
    adapter = run / "best-adapter"
    adapter.mkdir(parents=True)
    files = {"adapter_model.safetensors": "fixture-hash"}
    run_sha = write(
        run / "run.json",
        {
            "status": "trained",
            "best_step": 80,
            "base_directory": str(base),
            "base_sha256": "b" * 64,
            "profile_sha256": "c" * 64,
            "candidate_files": files,
            "recipe": {"model_kind": "qwen3_5_text", "enable_thinking": False},
            "masking": {"template_sha256": digest("procedural-template")},
        },
    )
    candidate = private / "named-models" / (NAME + ".json")
    candidate_sha = write(
        candidate,
        {
            "version": "lab-named-adapter-v1",
            "name": NAME,
            "base_model": "Qwen/Qwen3.5-4B",
            "base_directory": str(base),
            "run_directory": str(run),
            "adapter_directory": str(adapter),
            "selected_step": 80,
            "base_sha256": "b" * 64,
            "profile_sha256": "c" * 64,
            "adapter_files": files,
        },
    )
    write(
        directory / "training-lab.json",
        {
            "format": "qtrades-local-lab-v1",
            "private_root": str(private),
            "lab_root": str(lab),
            "python": str(python),
            "lab_source_sha256": digest(
                {"handoff.py": hashlib.sha256(source.read_bytes()).hexdigest()}
            ),
            "timeout_seconds": 30,
            "profile": {},
            "policy": {},
        },
    )
    write(
        directory / "development-serving.json",
        {
            "format": "qtrades-peft-development-v1",
            "candidate": str(candidate),
            "candidate_sha256": candidate_sha,
            "run_sha256": run_sha,
        },
    )
    monkeypatch.setattr(
        "trading.peft_role_model.LocalRoles.paper_guard",
        lambda self: {
            "running": True,
            "error": None,
            "stale": False,
            "research_constrained": False,
        },
    )
    monkeypatch.setattr("trading.peft_role_model.available_memory", lambda: 64 * 1024**3)
    return PeftDevelopmentRoles(directory), candidate, source


def test_declaration_is_metadata_only_and_never_confers_operating_admission(declared):
    model, _, _ = declared
    profile = model.development_admit("researcher")
    assert profile["device"] == "cpu" and profile["precision"] == "float32"
    assert profile["development_only"] and profile["identity"]["base_sha256"] == "b" * 64
    with pytest.raises(ValueError, match="no operating qualification"):
        model.admit("researcher")


@pytest.mark.parametrize("changed", ["alias", "source", "guard"])
def test_changed_identity_or_closed_guard_refuses_before_any_model_dispatch(
    declared, monkeypatch, changed
):
    model, candidate, source = declared
    launched = Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launched)
    if changed == "alias":
        candidate.write_text("{}")
    elif changed == "source":
        source.write_text("# changed")
    else:

        def refused(_):
            raise ValueError("Operating paper health/resource guard constrains optional inference")

        monkeypatch.setattr("trading.peft_role_model.LocalRoles.paper_guard", refused)
    with pytest.raises(ValueError):
        model.development_admit("researcher")
    launched.assert_not_called()


class DevelopmentStub(ModelStub):
    def development_admit(self, role):
        return super().admit(role) | {"development_only": True}

    def infer(self, role, packet, profile):
        return super().infer(role, packet, profile) | {"complete": True, "raw_answer": "fixture"}


def test_normal_question_development_answer_is_retained_once_without_financial_dispatch(
    pg_store, tmp_path
):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    worker = RoleWorker(lab.registry, lab)
    task = worker.enqueue(
        Question(question="Procedural developer question using the ordinary evidence.")
    )
    before = store.read()
    fake = DevelopmentStub()
    answer = asyncio.run(worker.development_answer(task["id"], fake))
    assert answer.action == "propose_experiment"
    assert asyncio.run(worker.development_answer(task["id"], fake)) == answer
    assert fake.calls == ["researcher"]
    saved = worker.get(task["id"])
    assert saved["stage"] == "idea" and saved["status"] == "queued" and not worker.enabled
    assert saved["attempts"][0]["stage"] == "development_idea"
    assert json.loads(saved["attempts"][0]["response"])["raw_answer"] == "fixture"
    assert store.read() == before and store.reconcile()["balanced"]
    # The same completed development answer cannot satisfy operating dispatch.
    task["_claimed_owner"] = worker.owner
    with pytest.raises(InputWait, match="disabled"):
        asyncio.run(worker._answer(task))
    used = lab.registry.db.execute("SELECT count(*) FROM role_attempt_allowances").fetchone()[0]
    assert used == 1
    lab.registry.close()


@pytest.mark.parametrize("bad", ["incomplete", "invalid", "unknown"])
def test_original_failed_or_unknown_development_attempt_never_silently_repeats(
    pg_store, tmp_path, bad
):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    worker = RoleWorker(lab.registry, lab)
    task = worker.enqueue(Question(question="Procedural original-response preservation check."))
    fake = DevelopmentStub()
    original = fake.infer

    def response(role, packet, profile):
        result = original(role, packet, profile)
        if bad == "unknown":
            raise TimeoutError("Procedural unknown answer")
        return result | ({"complete": False} if bad == "incomplete" else {"answer": {"bad": True}})

    fake.infer = response
    for _ in range(2):
        with pytest.raises((ValueError, TimeoutError)):
            asyncio.run(worker.development_answer(task["id"], fake))
    assert len(fake.calls) == 1
    attempt = worker.get(task["id"])["attempts"][0]
    assert attempt["status"] == "failed"
    assert bool(attempt["response"]) == (bad != "unknown")
    assert store.reconcile()["balanced"]
    lab.registry.close()


@pytest.mark.skipif(os.name != "nt", reason="Native process-handle ownership is Windows specific")
def test_child_lifetime_uses_original_handle_and_job_close(tmp_path):
    finished = tmp_path / "completed"
    code = "import pathlib,sys,time; time.sleep(30); pathlib.Path(sys.argv[1]).write_text('done')"
    with subprocess.Popen(
        [sys.executable, "-c", code, str(finished)], creationflags=subprocess.CREATE_NO_WINDOW
    ) as child:
        owned = ChildOwner(child)
        assert child.poll() is None
        started = time.monotonic()
        owned.close()
        child.wait(timeout=10)  # Windows job-close may use exit code zero.
        assert time.monotonic() - started < 5 and not finished.exists()
        owned.close()


def test_bounded_transport_retains_request_and_answer_with_owned_procedural_child(
    declared, monkeypatch
):
    model, _, _ = declared
    _, _, profile = model.declaration()
    original_popen = subprocess.Popen
    observed = []
    # A clearly procedural child exercises the real supervisor/receipt/locks;
    # it does not implement a production fallback or import a model library.
    code = """
import json, pathlib, sys, time
p=pathlib.Path(sys.argv[1]); r=json.loads((p/'request.json').read_text())
while not (p/'owner-ready').exists(): time.sleep(.01)
(p/'response.json').write_text(sys.argv[2])
"""
    response = {
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
        "raw_answer": "procedural",
        "answer": {},
        "peak_rss_bytes": 1,
    }

    def launch(command, **kwargs):
        observed.append((command, kwargs))
        request = json.loads((Path(command[-1]) / "request.json").read_text())
        value = json.dumps({"request_sha256": digest(request), "response": response})
        return original_popen([sys.executable, "-c", code, command[-1], value], **kwargs)

    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launch)
    result = model.infer(
        "researcher", {"question": "Procedural", "evidence": {}, "capabilities": {}}, profile
    )
    assert result["raw_answer"] == "procedural"
    assert observed[0][0][1:3] == ["-m", "trading.peft_role_runner"]
    assert observed[0][1]["env"]["CUDA_VISIBLE_DEVICES"] == ""
    assert observed[0][1]["env"]["HF_HUB_OFFLINE"] == "1"
    assert (
        len(
            list(
                (
                    Path(model.declaration()[0]["private_root"]) / "qtrades-development-inference"
                ).iterdir()
            )
        )
        == 1
    )
    lock = CollectorLock(model.directory / "research-inference.lock")
    lock.acquire()
    lock.release()


@pytest.mark.parametrize("fault", ["timeout", "pressure", "guard"])
def test_supervisor_stops_only_its_owned_procedural_child_and_retains_failure(
    declared, monkeypatch, fault
):
    model, _, _ = declared
    cfg, selected, profile = model.declaration()
    if fault == "timeout":
        profile = profile | {"timeout_seconds": 0.4}  # Finite procedural supervisor test.
        monkeypatch.setattr(model, "declaration", lambda: (cfg, selected, profile))
    original_popen = subprocess.Popen
    children = []

    def launch(command, **kwargs):
        child = original_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launch)
    if fault == "pressure":
        monkeypatch.setattr("trading.peft_role_model.ChildOwner.rss", lambda owner: 25 * 1024**3)
    if fault == "guard":
        calls = []

        def guard(_):
            calls.append(1)
            if len(calls) > 1:
                raise ValueError("Procedural protected guard closed")
            return {"research_constrained": False}

        monkeypatch.setattr("trading.peft_role_model.LocalRoles.paper_guard", guard)
    with pytest.raises(ValueError, match="Development job"):
        model.infer(
            "researcher", {"question": "Procedural", "evidence": {}, "capabilities": {}}, profile
        )
    assert len(children) == 1 and children[0].poll() is not None
    job = next((Path(cfg["private_root"]) / "qtrades-development-inference").iterdir())
    saved = json.loads((job / "dispatch.json").read_text())
    assert saved["status"] != "answered" and saved["wall_seconds"] < 10
    lock = CollectorLock(model.directory / "research-inference.lock")
    lock.acquire()
    lock.release()


def test_normal_question_uses_actual_transport_and_original_receipt_path_with_procedural_child(
    pg_store, declared, monkeypatch
):
    store, _ = pg_store
    model, _, _ = declared
    lab = make_lab(store, model.directory, horizon_seconds=3600)
    worker = RoleWorker(lab.registry, lab)
    task = worker.enqueue(
        Question(question="Procedural ordinary question through direct transport.")
    )
    before = store.read()
    original_popen = subprocess.Popen
    code = """
import pathlib,sys,time
p=pathlib.Path(sys.argv[1])
while not (p/'owner-ready').exists(): time.sleep(.01)
(p/'response.json').write_text(sys.argv[2])
"""
    calls = []

    def launch(command, **kwargs):
        job = Path(command[-1])
        request = json.loads((job / "request.json").read_text())
        packet = json.loads(request["packet_json"])
        calls.append(packet)
        assert packet == worker._packet(worker.get(task["id"]))[1]
        answer = ModelStub().infer("researcher", packet, {})["answer"]
        profile = model.declaration()[2]
        response = {
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
            "raw_answer": json.dumps(answer),
            "answer": answer,
            "peak_rss_bytes": 1,
        }
        return original_popen(
            [
                sys.executable,
                "-c",
                code,
                str(job),
                json.dumps(
                    {
                        "request_sha256": digest(request),
                        "response": response,
                    }
                ),
            ],
            **kwargs,
        )

    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launch)
    answer = asyncio.run(worker.development_answer(task["id"], model))
    saved = worker.get(task["id"])
    response = json.loads(saved["attempts"][0]["response"])
    assert response["raw_answer"] == json.dumps(answer.model_dump())
    assert saved["stage"] == "idea" and saved["status"] == "queued"
    assert store.read() == before and store.reconcile()["balanced"]
    assert len(calls) == 1
    lab.registry.close()


def test_late_original_response_is_retained_when_development_cancellation_races(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    worker = RoleWorker(lab.registry, lab)
    task = worker.enqueue(Question(question="Procedural late answer wins a cancellation race."))
    fake = DevelopmentStub()
    fake.slow = True
    fake.cancel = lambda: fake.release.set()

    async def run():
        answer = asyncio.create_task(worker.development_answer(task["id"], fake))
        assert await asyncio.to_thread(fake.entered.wait, 3)
        answer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await answer

    asyncio.run(run())
    retained = worker.get(task["id"])["attempts"][0]
    assert json.loads(retained["response"])["raw_answer"] == "fixture"
    assert len(fake.calls) == 1 and retained["finished"] is not None
    assert asyncio.run(worker.development_answer(task["id"], fake)).action == "propose_experiment"
    assert len(fake.calls) == 1 and store.reconcile()["balanced"]
    lab.registry.close()
