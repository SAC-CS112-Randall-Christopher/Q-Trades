import httpx
import pytest

from scripts import evaluate_research_roles as evaluator
from scripts.evaluate_research_roles import health, runtime_blocker
from scripts.run_qualification_queue import declared_screen_roles, screen_passed
from trading.research_resources import ELASTIC_CPU_RUNTIME


def client_for(response):
    return httpx.Client(transport=httpx.MockTransport(lambda request: response), trust_env=False)


def test_arcgis_resident_model_blocks_trading_inference_without_unloading_it():
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    sample = {"running": True, "error": None, "stale": False, "research_constrained": False}
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        assert "runtime" in runtime_blocker(client, sample, "qwen3:14b")
        assert runtime_blocker(client, sample, "qwen3:8b") is None
        assert "runtime" in runtime_blocker(client, sample, None)
    assert calls == [("GET", "/api/ps")] * 3


def test_dedicated_runtime_does_not_wait_on_arcgis_resident_models():
    calls = []

    def respond(request):
        calls.append(request.url.port)
        models = [{"name": "arcgis-model"}] if request.url.port == 11434 else []
        return httpx.Response(200, json={"models": models})

    sample = {"running": True, "error": None, "stale": False, "research_constrained": False}
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        assert runtime_blocker(client, sample, None, "http://127.0.0.1:11435") is None
    assert calls == [11435]


@pytest.mark.parametrize("failure", [ValueError("stale"), OSError("process exited")])
def test_stale_or_dead_elastic_supervision_blocks_before_a_model_request(monkeypatch, failure):
    def unavailable(path, *, include_worker):
        assert include_worker is False
        raise failure

    monkeypatch.setattr(evaluator, "capture_resources", unavailable)
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("No request"))
    ) as client:
        sample = {"running": True, "error": None, "stale": False, "research_constrained": False}
        assert "supervision is unavailable" in runtime_blocker(
            client, sample, None, "http://127.0.0.1:11435", ELASTIC_CPU_RUNTIME
        )


def test_elastic_preflight_allows_unloaded_runtime_but_rejects_changed_priority(monkeypatch):
    server = {"priority_class": 64, "affinity": 4095, "available_affinity": 4095}
    monkeypatch.setattr(
        evaluator,
        "capture_resources",
        lambda *args, **kwargs: {
            "profile": ELASTIC_CPU_RUNTIME,
            "inference_threads": 6,
            "server": server,
        },
    )
    sample = {"running": True, "error": None, "stale": False, "research_constrained": False}
    with client_for(httpx.Response(200, json={"models": []})) as client:
        assert (
            runtime_blocker(client, sample, None, "http://127.0.0.1:11435", ELASTIC_CPU_RUNTIME)
            is None
        )
        server["priority_class"] = 32
        assert "differs" in runtime_blocker(
            client, sample, None, "http://127.0.0.1:11435", ELASTIC_CPU_RUNTIME
        )


@pytest.mark.parametrize(
    "roles", [[], ["trainer", "trainer"], ["unknown"], "trainer", [["trainer"]]]
)
def test_frozen_role_subset_rejects_duplicate_or_unknown_work(roles):
    with pytest.raises(ValueError):
        declared_screen_roles({"screen_roles": roles})


def test_frozen_role_subset_does_not_repeat_failed_researcher():
    assert declared_screen_roles({"screen_roles": ["trainer", "reviewer"]}) == [
        "trainer",
        "reviewer",
    ]
    with pytest.raises(ValueError):
        declared_screen_roles({"screen_roles": ["trainer"], "screen_all_roles": True})
    assert declared_screen_roles({"screen_all_roles": True}) == [
        "researcher",
        "trainer",
        "reviewer",
    ]
    assert declared_screen_roles({}) is None


@pytest.mark.parametrize(
    "patch",
    [
        {"running": False},
        {"stale": True},
        {"error": "disk error"},
        {"research_constrained": True},
        {"research_constrained": None},
    ],
)
def test_unhealthy_or_constrained_worker_cannot_start_optional_inference(patch):
    def forbidden(request):
        raise AssertionError("No model runtime access should follow a failed worker gate")

    sample = {"running": True, "error": None, "stale": False, "research_constrained": False}
    with httpx.Client(transport=httpx.MockTransport(forbidden), trust_env=False) as client:
        assert runtime_blocker(client, sample | patch, "qwen3:14b")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="unavailable"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"paper": None}),
    ],
)
def test_failed_health_read_is_recorded_so_completed_answers_can_be_saved(response):
    with client_for(response) as client:
        result = health(client)
    assert result["running"] is False
    assert result["error"].startswith("Health unavailable")


def test_partial_or_repeated_dev_results_cannot_schedule_acceptance():
    rows = [
        {
            "model": "candidate",
            "role": "trainer",
            "case": f"dev-{i}",
            "complete": True,
            "passed": True,
            "critical": [],
            "runtime_after": {"running": True, "error": None, "stale": False},
        }
        for i in range(4)
    ]
    report = {"finished_at": "recorded", "results": rows}
    assert screen_passed(report, "candidate", "trainer")
    assert not screen_passed(report | {"results": rows[:3]}, "candidate", "trainer")
    assert not screen_passed(report | {"results": [rows[0]] * 4}, "candidate", "trainer")
    assert not screen_passed(report | {"stopped": "worker unhealthy"}, "candidate", "trainer")
    rows[-1]["critical"] = ["Unsafe experiment approval"]
    assert not screen_passed(report, "candidate", "trainer")
