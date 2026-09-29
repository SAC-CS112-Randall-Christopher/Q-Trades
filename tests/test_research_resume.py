import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from scripts import evaluate_research_roles as evaluator


@pytest.fixture
def resource_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluator, "ROOT", tmp_path)
    folder = tmp_path / "docs/evidence"
    folder.mkdir(parents=True)
    profile = {
        "corpus_hash": "corpus",
        "protocol_hash": "protocol",
        "prompt_profile": "role-contract-only",
        "effective_protocol_hash": "protocol",
        "prompts": {"trainer": "frozen prompt"},
        "split": "dev",
        "seeds": [9281],
        "thinking": True,
        "stop_disqualified_role": False,
        "request_timeout_seconds": 600,
        "settings": {"num_thread": 6, "num_gpu": 0, "temperature": 0.6},
        "models": {"synthetic-test-only": {"digest": "digest"}},
        "runner_sha256": "old-source",
        "results": [],
        "ollama_origin": "http://127.0.0.1:11435",
        "runtime_profile": "trading-cpu-elastic-six-threads-v1",
        "ollama_version": "test-version",
    }
    cases = [{"id": f"dev-{i}", "role": "trainer"} for i in range(4)]
    previous = copy.deepcopy(profile)
    previous.update(finished_at="2026-09-28T16:47:00Z", stopped=evaluator.RESOURCE_STOP)
    previous["results"] = [
        {
            "model": "synthetic-test-only",
            "case": "dev-0",
            "role": "trainer",
            "seed": 9281,
            "settings": dict(profile["settings"], seed=9281),
            "request_timeout_seconds": 600,
            "complete": True,
            "passed": True,
            "response": "original final answer",
        }
    ]
    return folder / "original.json", previous, profile, cases


@pytest.mark.parametrize("passed", [True, False])
def test_explicit_resource_resume_keeps_original_answers_and_stop_receipt(resource_prefix, passed):
    path, previous, report, cases = resource_prefix
    previous["results"][0]["passed"] = passed
    path.write_text(json.dumps(previous), encoding="utf-8")
    original = path.read_bytes()
    evaluator.resume_prefix(path, report, cases, allow_resource_yield=True)
    assert path.read_bytes() == original
    assert report["results"] == previous["results"]
    assert report["resumed_from"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert report["resumed_from"]["previous_stop"] == evaluator.RESOURCE_STOP
    assert report["resumed_from"]["continuation_policy"] == "resource-yield-v1"
    assert "stopped" not in report
    assert "finished_at" not in report
    completed = {(r["model"], r["case"], r["seed"]) for r in report["results"]}
    assert ("synthetic-test-only", "dev-0", 9281) in completed


@pytest.mark.parametrize(
    "patch",
    [
        {"stopped": "Dedicated CPU runtime placement could not be verified"},
        {"stopped": None},
        {"finished_at": None},
        {"active_request": {"case": "dev-1"}},
        {"disqualified_roles": ["trainer"]},
    ],
)
def test_resource_resume_cannot_bypass_other_stop_or_inflight_states(resource_prefix, patch):
    path, previous, report, cases = resource_prefix
    previous.update(patch)
    path.write_text(json.dumps(previous), encoding="utf-8")
    with pytest.raises(ValueError):
        evaluator.resume_prefix(path, report, cases, allow_resource_yield=True)


def test_resource_resume_is_explicit_and_preserves_model_and_profile_identity(resource_prefix):
    path, previous, report, cases = resource_prefix
    path.write_text(json.dumps(previous), encoding="utf-8")
    with pytest.raises(ValueError, match="finished, stopped"):
        evaluator.resume_prefix(path, report, cases)
    changed = copy.deepcopy(report)
    changed["settings"]["num_thread"] = 12
    with pytest.raises(ValueError, match="frozen evaluation profile"):
        evaluator.resume_prefix(path, changed, cases, allow_resource_yield=True)
    changed = copy.deepcopy(report)
    changed["models"]["synthetic-test-only"]["digest"] = "replacement"
    with pytest.raises(ValueError, match="digests differ"):
        evaluator.resume_prefix(path, changed, cases, allow_resource_yield=True)


def test_resource_resume_rejects_reordered_or_duplicate_rows(resource_prefix):
    path, previous, report, cases = resource_prefix
    previous["results"] *= 2
    path.write_text(json.dumps(previous), encoding="utf-8")
    with pytest.raises(ValueError, match="unique, unfinished"):
        evaluator.resume_prefix(path, report, cases, allow_resource_yield=True)


def run_wait(monkeypatch, tmp_path, patches, limit, already_used=0):
    clock = [0.0]
    monkeypatch.setattr(evaluator.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        evaluator.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    healthy = {"running": True, "error": None, "stale": False, "research_constrained": False}
    samples = [healthy | patch for patch in patches]

    def health(_):
        return samples.pop(0) if len(samples) > 1 else samples[0]

    monkeypatch.setattr(evaluator, "health", health)
    saved = []
    monkeypatch.setattr(evaluator, "save", lambda report, path: saved.append(copy.deepcopy(report)))
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET" and request.url.path == "/api/ps"
        return httpx.Response(200, json={"models": []})

    report = {"results": [{"response": "retained"}], "resource_wait_used_seconds": already_used}
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reason = evaluator.await_resources(
            client,
            "synthetic-test-only",
            "http://127.0.0.1:11435",
            None,
            report,
            tmp_path / "report.json",
            {"id": "dev-next", "role": "trainer"},
            limit,
        )
    assert report["results"] == [{"response": "retained"}]
    return reason, report, saved, clock[0], calls


def test_resource_wait_persists_state_and_requires_stable_recovery(monkeypatch, tmp_path):
    reason, report, saved, elapsed, calls = run_wait(
        monkeypatch, tmp_path, [{"research_constrained": True}, {}], 120
    )
    assert reason is None
    assert elapsed == 45
    assert report["resource_wait_used_seconds"] == 45
    assert len(report["resource_waits"]) == 1
    assert report["resource_waits"][0]["outcome"] == "resumed"
    assert "waiting_for_resources" in saved[0]
    assert "waiting_for_resources" not in saved[-1]
    assert calls and all(method == "GET" for method, _ in calls)


@pytest.mark.parametrize("already_used, expected_elapsed", [(0, 30), (20, 10)])
def test_resource_wait_has_one_cumulative_budget(
    monkeypatch, tmp_path, already_used, expected_elapsed
):
    reason, report, saved, elapsed, calls = run_wait(
        monkeypatch, tmp_path, [{"research_constrained": True}], 30, already_used
    )
    assert reason == evaluator.RESOURCE_BLOCKER
    assert elapsed == expected_elapsed
    assert report["resource_wait_used_seconds"] == 30
    assert report["resource_waits"][0]["outcome"] == "stopped"
    assert "waiting_for_resources" not in saved[-1]
    assert not calls


def test_resource_wait_does_not_retry_a_failed_paper_worker(monkeypatch, tmp_path):
    reason, report, _, elapsed, _ = run_wait(
        monkeypatch, tmp_path, [{"research_constrained": True}, {"running": False}], 120
    )
    assert reason == "Trading worker health is unavailable or unhealthy"
    assert elapsed == 15
    assert report["resource_waits"][0]["outcome"] == "stopped"


def test_zero_wait_budget_preserves_existing_stop_behavior(monkeypatch, tmp_path):
    reason, report, saved, elapsed, calls = run_wait(
        monkeypatch, tmp_path, [{"research_constrained": True}], 0
    )
    assert reason == evaluator.RESOURCE_BLOCKER
    assert elapsed == 0
    assert not saved and not calls
    assert "resource_waits" not in report


def test_evaluator_restart_dispatches_only_unrun_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluator, "ROOT", tmp_path)
    evidence = tmp_path / "docs/evidence"
    evidence.mkdir(parents=True)
    corpus_folder = tmp_path / "docs/research"
    corpus_folder.mkdir()
    cases = [
        {
            "id": f"dev-trainer-{i}",
            "role": "trainer",
            "split": "dev",
            "evidence": [{"id": f"E{i}", "text": "Supplied method is valid."}],
            "checks": {"decision": "plan_training", "issues": [], "evidence_ids": [f"E{i}"]},
        }
        for i in range(4)
    ]
    (corpus_folder / "crypto-agent-eval-v3.json").write_text(json.dumps({"cases": cases}))
    ticks = [0]

    class Clock:
        @staticmethod
        def now(_):
            ticks[0] += 1
            return datetime(2026, 9, 28, tzinfo=UTC) + timedelta(seconds=ticks[0])

    monkeypatch.setattr(evaluator, "datetime", Clock)
    interrupted = [True]
    dispatched = []

    def respond(request):
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "synthetic-test-only", "digest": "digest"}]}
            )
        if path == "/api/version":
            return httpx.Response(200, json={"version": "test-version"})
        if path == "/api/status":
            return httpx.Response(
                200,
                json={
                    "paper": {
                        "running": True,
                        "error": None,
                        "stale": False,
                        "research_constrained": bool(interrupted[0] and dispatched),
                    }
                },
            )
        if path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["thinking"]})
        if path == "/api/chat":
            body = json.loads(request.content)
            item = json.loads(body["messages"][1]["content"])["evidence"][0]["id"]
            dispatched.append(item)
            answer = {
                "evidence_ids": [item],
                "issues": [],
                "decision": "plan_training",
                "rationale": "The supplied method meets the registered training requirements.",
            }
            return httpx.Response(
                200,
                json={
                    "done": True,
                    "done_reason": "stop",
                    "message": {"content": json.dumps(answer)},
                },
            )
        if path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        pytest.fail(f"Unexpected endpoint: {path}")

    client_type = httpx.Client
    monkeypatch.setattr(
        evaluator.httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    argv = ["evaluate", "--models", "synthetic-test-only", "--roles", "trainer", "--thinking"]
    monkeypatch.setattr("sys.argv", argv)
    evaluator.main()
    original_path = next(evidence.glob("research-roles-*.json"))
    original_bytes = original_path.read_bytes()
    original = json.loads(original_bytes)
    assert original["stopped"] == evaluator.RESOURCE_STOP
    assert len(original["results"]) == 1
    interrupted[0] = False
    monkeypatch.setattr(
        "sys.argv", argv + ["--resume-from", str(original_path), "--resume-resource-yield"]
    )
    evaluator.main()
    continued_path = next(p for p in evidence.glob("research-roles-*.json") if p != original_path)
    continued = json.loads(continued_path.read_text())
    assert dispatched == ["E0", "E1", "E2", "E3"]
    assert original_path.read_bytes() == original_bytes
    assert continued["results"][:1] == original["results"]
    assert len(continued["results"]) == 4
    assert "stopped" not in continued
    assert continued["resumed_from"]["sha256"] == hashlib.sha256(original_bytes).hexdigest()
