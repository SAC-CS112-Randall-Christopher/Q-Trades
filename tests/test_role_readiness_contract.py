"""Actual packet/readiness contract checks; disposable sources, no model calls."""

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_local_roles import declared
from test_persistent_research import TASK, note, query, task
from test_research_storage import plan_at

from trading.api import create_app
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry
from trading.local_role_model import LocalRoles
from trading.research_knowledge import ResearchKnowledge
from trading.research_storage import ResearchStorage
from trading.role_worker import RoleWorker


@pytest.mark.parametrize("rag_contract,compatible", [(None, False), ("source-rag-v1", True)])
@pytest.mark.parametrize("matching_source", [True, False])
def test_normal_api_readiness_agrees_with_real_retained_packet_preflight(
    tmp_path, monkeypatch, rag_contract, compatible, matching_source
):
    profile = declared() | {"enabled": True}
    if rag_contract:
        profile["rag_contract"] = rag_contract
    policy_path = tmp_path / "role-policy.json"
    policy_path.write_text(json.dumps(profile))
    original_policy = policy_path.read_bytes()
    transport = LocalRoles(tmp_path)
    monkeypatch.setattr(transport, "qualification", lambda role, policy: None)
    monkeypatch.setattr(transport, "observe", lambda policy: {"fixture": "No runtime request"})
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    storage = ResearchStorage(plan_at(tmp_path))
    try:
        knowledge = ResearchKnowledge(storage)
        if matching_source:
            knowledge.ingest(note())
        paper = SimpleNamespace(
            running=True, error=None, state={"last_tick": time.time()}, constrained=lambda: False
        )
        worker = RoleWorker(registry, SimpleNamespace(paper=paper), transport)
        task(worker)
        worker.knowledge = knowledge
        saved = worker.get(TASK)
        saved["context"]["knowledge"] = knowledge.retrieve(query())
        role, packet = worker._packet(saved)
        assert packet["retrieval_contract"] == "source-rag-v1"
        assert bool(packet["knowledge"]["passages"]) is matching_source
        if compatible:
            transport.preflight(role, packet, transport.policy())
        else:
            with pytest.raises(ValueError, match="separately qualified"):
                transport.preflight(role, packet, transport.policy())
        app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
        with TestClient(app) as client:
            app.state.lab = SimpleNamespace(roles=worker)
            readiness = client.get("/api/lab/roles").json()["readiness"]
        assert readiness["ready"] is compatible
        # Valid original-profile receipts remain independently visible, not RAG qualification.
        assert readiness["qualification_valid"] is True
        assert readiness["runtime_available"] is True
        assert readiness["stages"]["retrieval"]["state"] == (
            "compatible" if compatible else "incompatible"
        )
        if not compatible:
            assert "separately qualified" in readiness["stages"]["retrieval"]["next_action"]
        assert registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0
        assert policy_path.read_bytes() == original_policy
    finally:
        storage.close()
        registry.close()


def test_original_profile_readiness_without_reference_library_is_preserved(tmp_path, monkeypatch):
    profile = declared() | {"enabled": True}
    (tmp_path / "role-policy.json").write_text(json.dumps(profile))
    transport = LocalRoles(tmp_path)
    monkeypatch.setattr(transport, "qualification", lambda role, policy: None)
    monkeypatch.setattr(transport, "observe", lambda policy: {"fixture": "No runtime request"})
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    try:
        paper = SimpleNamespace(
            running=True, error=None, state={"last_tick": time.time()}, constrained=lambda: False
        )
        worker = RoleWorker(registry, SimpleNamespace(paper=paper), transport)
        result = worker.readiness()
        assert result["ready"] is True and result["qualification_valid"] is True
        assert "retrieval" not in result["stages"]
        assert registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0
    finally:
        registry.close()
