"""Development packet admission uses disposable SQLite and procedural responses only."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.lab_role_contract import packet_json, prompt
from trading.peft_profile import PROFILE
from trading.peft_role_model import PeftDevelopmentRoles
from trading.role_worker import RoleWorker

TASK = "role-" + "6" * 32


@pytest.fixture
def development(tmp_path, monkeypatch):
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    worker = RoleWorker(registry, None)
    context = {"question": {"question": "Which limitations follow from this procedural evidence?"}}
    with registry.transaction():
        registry.db.execute(
            "INSERT INTO role_tasks(id,created,updated,stage,status,context) "
            "VALUES(?,?,?,'idea','queued',?)",
            (TASK, time.time(), time.time(), json.dumps(context)),
        )
    packet = {
        "question": context["question"]["question"],
        "capabilities": {},
        "evidence": {"e0": {"basis": "procedural_qa", "fact": "No market outcome measured"}},
    }
    monkeypatch.setattr(worker, "_base_packet", lambda task: ("researcher", dict(packet)))
    model = PeftDevelopmentRoles(tmp_path)
    monkeypatch.setattr(model, "development_admit", lambda role: dict(PROFILE))
    try:
        yield worker, model, packet
    finally:
        registry.close()


@pytest.mark.parametrize("passages", [[], [{"citation": "k0", "text": "Procedural source"}]])
def test_rag_packet_is_refused_before_development_attempt_or_allowance(
    development, monkeypatch, passages
):
    worker, model, _ = development
    with worker.registry.transaction():
        context = worker.get(TASK)["context"] | {"knowledge": {"passages": passages}}
        worker.registry.db.execute(
            "UPDATE role_tasks SET context=? WHERE id=?", (json.dumps(context), TASK)
        )
    worker.knowledge = SimpleNamespace(check_passages=lambda *args, **kwargs: None)
    before = worker.get(TASK)
    launched = Mock()
    declaration = Mock(side_effect=AssertionError("No dispatch preparation is permitted"))
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launched)
    monkeypatch.setattr(model, "declaration", declaration)

    for _ in range(2):
        with pytest.raises(ValueError, match="RAG development packet requires"):
            asyncio.run(worker.development_answer(TASK, model))
        assert worker.get(TASK) == before
        assert (
            worker.registry.db.execute("SELECT count(*) FROM role_attempt_allowances").fetchone()[0]
            == 0
        )
    launched.assert_not_called()
    declaration.assert_not_called()


def test_large_compatible_packet_preflight_preserves_task_and_allowances(development):
    worker, model, packet = development
    packet["question"] = "Procedural oversized input " * 2000
    before = worker.get(TASK)
    assert len(packet_json(packet).encode()) + len(prompt("researcher").encode()) > 32768
    model.preflight("researcher", packet, PROFILE)
    assert worker.get(TASK) == before
    assert (
        worker.registry.db.execute("SELECT count(*) FROM role_attempt_allowances").fetchone()[0]
        == 0
    )


def test_compatible_original_packet_is_reserved_once_and_reopened_without_dispatch(
    development, monkeypatch
):
    worker, model, packet = development
    answer = {
        "action": "no_change",
        "evidence_ids": ["e0"],
        "capability": None,
        "mechanism": "No causal outcome exists in the procedural evidence.",
        "falsification": "An independently supported outcome would change this limitation.",
        "rationale": "This software fixture cannot establish useful market evidence.",
        "dependency": None,
    }

    def procedural_response(role, supplied, profile):
        assert role == "researcher" and supplied == packet and profile == PROFILE
        assert (
            worker.registry.db.execute("SELECT count(*) FROM role_attempt_allowances").fetchone()[0]
            == 1
        )
        return {"answer": answer, "complete": True, "raw_answer": "Procedural QA only"}

    transport = Mock(side_effect=procedural_response)
    monkeypatch.setattr(model, "infer", transport)
    before = fingerprint(worker.get(TASK)["context"])
    for _ in range(2):
        assert asyncio.run(worker.development_answer(TASK, model)).action == "no_change"
    saved = worker.get(TASK)
    assert saved["stage"] == "idea" and saved["status"] == "queued"
    assert fingerprint(saved["context"]) == before
    assert len(saved["attempts"]) == 1
    assert saved["attempts"][0]["stage"] == "development_idea"
    assert json.loads(saved["attempts"][0]["packet"]) == packet
    assert json.loads(saved["attempts"][0]["response"])["raw_answer"] == "Procedural QA only"
    transport.assert_called_once()
