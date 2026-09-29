import hashlib
import json
import os

from fastapi.testclient import TestClient

from trading.api import create_app
from trading.config import Settings
from trading.model_trials import MAX_BYTES, read_trials
from trading.research_protocol import protocol_hash


def receipt():
    return {
        "protocol_hash": protocol_hash(),
        "models": {"test-model": {}},
        "prompts": {"researcher": "PRIVATE PROMPT"},
        "seeds": [1],
        "split": "dev",
        "active_request": {"model": "test-model", "role": "researcher", "case": "C2"},
        "results": [
            {
                "case": "C1",
                "model": "test-model",
                "role": "researcher",
                "seed": 1,
                "passed": False,
                "complete": True,
                "seconds": 2,
                "critical": [],
                "errors": ["Unsupported finding"],
                "thinking": "PRIVATE REASONING",
                "response": json.dumps(
                    {
                        "rationale": "Final explanation for the operator.",
                        "decision": "request_data",
                        "evidence_ids": ["E1"],
                        "hidden_extra": "PRIVATE EXTRA",
                    }
                ),
            }
        ],
    }


def test_trials_are_read_only_and_expose_only_final_explanations(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    path = evidence / "research-roles-dev-20260928T100000Z.json"
    path.write_text(json.dumps(receipt()), encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    app = create_app(
        Settings(), tmp_path / "monitor.db", background=False, research_evidence=evidence
    )
    with TestClient(app) as client:
        response = client.get("/api/research/trials")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        value = response.json()
        assert value["agents_enabled"] is False
        assert value["runs"][0]["profiles"][0]["passed"] == 0
        assert value["runs"][0]["recent"][0]["rationale"] == "Final explanation for the operator."
        assert "PRIVATE" not in response.text
        assert client.post("/api/research/trials").status_code == 405
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_missing_finish_marker_becomes_unconfirmed_not_perpetually_running(tmp_path):
    path = tmp_path / "research-roles-dev-20260928T100000Z.json"
    path.write_text(json.dumps(receipt()), encoding="utf-8")
    os.utime(path, (100, 100))
    assert read_trials(tmp_path, now=101)["runs"][0]["state"] == "awaiting_response"
    assert read_trials(tmp_path, now=1000)["runs"][0]["state"] == "unconfirmed"


def test_viewer_bounds_history_preserves_errors_and_orders_both_splits_by_time(tmp_path):
    for i in range(10):
        split = "holdout" if i % 2 else "dev"
        path = tmp_path / f"research-roles-{split}-20260928T10{i:02d}00Z.json"
        path.write_text(json.dumps(receipt() | {"finished_at": "recorded"}), encoding="utf-8")
    corrupt = tmp_path / "research-roles-dev-20260928T110000Z.json"
    corrupt.write_bytes(b"x" * (MAX_BYTES + 1))
    value = read_trials(tmp_path)
    assert len(value["runs"]) == 8
    assert value["older_runs_omitted"] is True
    assert value["runs"][0]["state"] == "unavailable"
    assert "100900" in value["runs"][1]["id"]
    assert value["runs"][1]["state"] == "incomplete"
    assert len(list(tmp_path.iterdir())) == 11


def test_malformed_profile_rows_do_not_become_valid_scores(tmp_path):
    path = tmp_path / "research-roles-dev-20260928T100000Z.json"
    report = receipt()
    report["results"][0]["model"] = "undeclared-model"
    report["results"][0]["seconds"] = float("nan")
    path.write_text(json.dumps(report), encoding="utf-8")
    value = read_trials(tmp_path)
    assert value["runs"][0]["state"] == "unavailable"
    assert "profiles" not in value["runs"][0]
    assert value["warnings"]
