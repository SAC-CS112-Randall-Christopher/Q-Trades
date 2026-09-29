import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from trading import research_resources as resources
from trading.research_inference import cpu_placement_valid


def observed():
    return {
        "profile": resources.ELASTIC_CPU_RUNTIME,
        "inference_threads": 6,
        "server": {"priority_class": 64, "affinity": 4095, "available_affinity": 4095},
        "worker": {"priority_class": 64, "affinity": 4095, "available_affinity": 4095},
    }


@pytest.mark.parametrize(
    "change",
    [
        {"priority_class": 32},
        {"priority_class": 32768},
        {"affinity": 2560},
        {"available_affinity": 65535},
        {"affinity": None},
    ],
)
def test_elastic_placement_rejects_priority_or_capacity_mismatch(change):
    value = observed()
    assert resources.elastic_resources_valid(value)
    for component in ("server", "worker"):
        bad = copy.deepcopy(value)
        bad[component].update(change)
        assert not resources.elastic_resources_valid(bad)


def test_cpu_placement_cannot_qualify_six_threads_under_the_old_profile():
    row = {
        "settings": {"num_gpu": 0, "num_thread": 6},
        "model_runtime_after": [{"name": "test", "digest": "digest", "size_vram": 0}],
        "resource_state_after": observed(),
    }
    assert cpu_placement_valid(row, "test", "digest", resources.ELASTIC_CPU_RUNTIME)
    assert not cpu_placement_valid(row, "test", "digest")
    row.pop("resource_state_after")
    assert not cpu_placement_valid(row, "test", "digest", resources.ELASTIC_CPU_RUNTIME)


def test_stale_runtime_state_cannot_be_used_as_current_placement(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "state": "running",
                "updated_at": (datetime.now(UTC) - timedelta(seconds=31)).isoformat(),
            }
        )
    )
    monkeypatch.setattr(
        resources, "_process", lambda *args: pytest.fail("Do not inspect stale PIDs")
    )
    with pytest.raises(ValueError, match="stale"):
        resources.capture_resources(path)


def test_current_state_requires_independent_server_and_worker_observations(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "state": "running",
                "updated_at": datetime.now(UTC).isoformat(),
                "origin": "http://127.0.0.1:11435",
                "profile": resources.ELASTIC_CPU_RUNTIME,
                "server_pid": 10,
                "executable": "server.exe",
                "server_started_at": "server-start",
                "last_budgeted_worker_pid": 20,
                "worker_executable": "worker.exe",
                "worker_started_at": "worker-start",
                "inference_threads": 6,
            }
        )
    )
    calls = []

    def record(*args):
        calls.append(args)
        return observed()["worker"]

    monkeypatch.setattr(resources, "_process", record)
    assert resources.elastic_resources_valid(resources.capture_resources(path))
    assert calls == [(10, "server.exe", "server-start"), (20, "worker.exe", "worker-start")]
