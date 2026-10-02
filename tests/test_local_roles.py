"""Transport boundary tests; these fixtures never qualify a model."""

import hashlib
import json

import httpx
import pytest

from trading.experiment_registry import fingerprint
from trading.lab_role_contract import contract_hash
from trading.local_role_model import LocalRoles
from trading.ownership import CollectorLock


def declared():
    return {
        "enabled": False,
        "origin": "http://127.0.0.1:11435",
        "runtime_profile": "trading-cpu-elastic-six-threads-v1",
        "model": "qwen3.5:4b",
        "model_digest": "synthetic-digest",
        "template_sha256": "synthetic-template",
        "server_version": "synthetic-server",
        "thinking": False,
        "timeout_seconds": 120,
        "hourly_wall_seconds": 1800,
        "hourly_tokens": 65536,
        "options": {"num_gpu": 0, "num_thread": 6, "num_ctx": 8192, "num_predict": 768},
    }


def test_policy_qualifications_and_activation_remain_distinct(tmp_path, monkeypatch):
    transport = LocalRoles(tmp_path)
    assert transport.readiness()["qualified"] is False
    (tmp_path / "role-policy.json").write_text(json.dumps(declared()))
    profile = transport.policy()
    rows = [
        {
            "role": role,
            "case": str(i),
            "seed": seed,
            "complete": True,
            "passed": True,
            "critical": False,
            "placement_valid": True,
        }
        for role in ("researcher", "reviewer")
        for i in range(12)
        for seed in (92811, 92823, 92837)
    ]
    report = {
        "split": "holdout",
        "contract_sha256": contract_hash(),
        "profile_sha256": fingerprint({k: v for k, v in profile.items() if k != "enabled"}),
        "rows": rows,
        "roles": {
            r: {"complete": 36, "passed": 36, "critical": 0, "placement_valid": True}
            for r in ("researcher", "reviewer")
        },
    }
    raw = json.dumps(report).encode()
    (tmp_path / "role-qualification.json").write_bytes(raw)
    policy = declared() | {"qualification_sha256": hashlib.sha256(raw).hexdigest()}
    (tmp_path / "role-policy.json").write_text(json.dumps(policy))
    monkeypatch.setattr(transport, "observe", lambda profile: {"scope": "transport fixture"})
    assert transport.readiness()["qualified"] is True
    assert transport.readiness()["enabled"] is False
    with pytest.raises(ValueError, match="disabled"):
        transport.admit("reviewer")
    policy["options"]["num_predict"] = 1024
    (tmp_path / "role-policy.json").write_text(json.dumps(policy))
    assert "stale" in transport.readiness()["roles"]["reviewer"]["reason"]


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "http://127.0.0.1:11434"},
        {"model": "unapproved:1b"},
        {"options": {"num_gpu": 1, "num_thread": 6}},
        {"hourly_wall_seconds": 3600},
    ],
)
def test_unapproved_placement_models_or_allowances_rejected(tmp_path, change):
    (tmp_path / "role-policy.json").write_text(json.dumps(declared() | change))
    with pytest.raises(ValueError):
        LocalRoles(tmp_path).policy()


def test_resource_guard_blocks_before_any_model_request_and_does_not_unload(tmp_path, monkeypatch):
    transport = LocalRoles(tmp_path)
    monkeypatch.setattr(transport, "observe", lambda profile: {})
    requests = []
    real_client = httpx.Client

    def dispatch(request):
        requests.append(str(request.url))
        assert request.method == "GET" and request.url.port == 8780
        return httpx.Response(
            200,
            json={
                "paper": {
                    "running": True,
                    "error": None,
                    "stale": False,
                    "research_constrained": True,
                }
            },
        )

    monkeypatch.setattr(
        "trading.local_role_model.httpx.Client",
        lambda **kw: real_client(transport=httpx.MockTransport(dispatch), **kw),
    )
    with pytest.raises(ValueError, match="constrains optional"):
        transport.infer("researcher", {"evidence": {}}, declared())
    assert requests == ["http://127.0.0.1:8780/api/status"]
    subsequent = CollectorLock(tmp_path / "research-inference.lock")
    subsequent.acquire()
    subsequent.release()


def test_action_fields_cannot_be_silently_omitted():
    from trading.lab_role_contract import Idea, schema

    assert {"capability", "dependency"} <= set(schema("researcher")["required"])
    with pytest.raises(ValueError):
        Idea.model_validate(
            {
                "action": "propose_experiment",
                "evidence_ids": ["e0"],
                "mechanism": "A reviewed prospective mechanism",
                "falsification": "A matched measured falsification",
                "rationale": "Only the permitted exploratory paper comparison",
            }
        )


def test_data_wait_uses_exact_offered_condition_and_preserves_legacy_contract():
    from trading.lab_role_contract import validate

    answer = {
        "action": "request_data",
        "evidence_ids": ["e2"],
        "capability": None,
        "mechanism": "Wait for a later eligible closed causal source.",
        "falsification": "Do not infer without the declared missing evidence.",
        "rationale": "No new support is available until the recorded condition occurs.",
        "dependency": "new_closed_bars",
    }
    packet = {
        "capabilities": {},
        "evidence": {
            "e2": {"request_data_conditions": {"new_closed_bars": {"kind": "closed_bars"}}}
        },
    }
    assert validate("researcher", answer, packet).dependency == "new_closed_bars"
    free_text = answer | {"dependency": "Wait for arbitrary labels"}
    with pytest.raises(ValueError, match="offered wait requirement"):
        validate("researcher", free_text, packet)
    with pytest.raises(ValueError, match="offered wait requirement"):
        validate(
            "researcher", answer, packet | {"evidence": {"e2": {"request_data_conditions": {}}}}
        )
    assert validate(
        "researcher", free_text, {"capabilities": {}, "evidence": {"e2": {}}}
    ).dependency
