import asyncio
import json
import time

import pytest
from test_experiment_registry import plan, shifted_inputs

from trading.experiment_lab import ExperimentLab
from trading.experiment_worker import code_fingerprint


@pytest.mark.parametrize("failure", ["memory", "timeout", "pressure"])
def test_stuck_memory_or_pressure_attempt_is_terminated_retained_and_fenced(
    tmp_path, monkeypatch, failure
):
    import trading.experiment_lab as module

    calls = 0

    def ready():
        nonlocal calls
        calls += 1
        return failure != "pressure" or calls == 1

    lab = ExperimentLab(tmp_path / "registry.sqlite", None, ready)
    frozen = plan(evidence_kind="synthetic_qa")
    lab.registry.reserve(frozen, code_fingerprint())
    lab.registry.inputs(frozen.request_id, shifted_inputs())
    recorded = {}

    class Child:
        pid = 12345
        terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    child = Child()

    def popen(args, **kwargs):
        recorded.update(args=args, **kwargs)
        return child

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module, "constrain_child", lambda pid: None)
    monkeypatch.setattr(
        module, "child_rss", lambda pid: 257 * 1024**2 if failure == "memory" else 100
    )
    monkeypatch.setattr(module, "WALL_SECONDS", 0.01 if failure == "timeout" else 25)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-must-not-reach-worker")
    monkeypatch.setenv("DATABASE_URL", "synthetic-financial-dsn-must-not-reach-worker")
    assert asyncio.run(lab.run_once())
    assert child.terminated
    receipt = lab.registry.get(frozen.request_id)
    assert receipt["status"] == "failed" and receipt["result"] is None
    assert any(e["kind"] == "worker_resources" for e in receipt["events"])
    assert "OPENAI_API_KEY" not in recorded["env"] and "DATABASE_URL" not in recorded["env"]
    assert not recorded.get("shell")
    with pytest.raises(ValueError, match="consumed"):
        lab.registry.reserve(plan("another-feature", feature="spread_bps"), code_fingerprint())
    lab.registry.close()


def test_shutdown_cancels_owned_child_retains_expired_attempt_and_can_reopen(tmp_path, monkeypatch):
    import trading.experiment_lab as module

    path = tmp_path / "registry.sqlite"
    lab = ExperimentLab(path, None, lambda: True)
    frozen = plan(evidence_kind="synthetic_qa")
    lab.registry.reserve(frozen, code_fingerprint())
    lab.registry.inputs(frozen.request_id, shifted_inputs())

    class Child:
        pid = 12345
        terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    child = Child()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(module, "constrain_child", lambda pid: None)
    monkeypatch.setattr(module, "child_rss", lambda pid: 100)

    async def run():
        task = asyncio.create_task(lab.run_once())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)

    asyncio.run(run())
    assert child.terminated and lab.child is None
    lab.registry.close()
    reopened = ExperimentLab(path, None, lambda: True)
    assert reopened.registry.status(frozen.request_id) == "running"
    assert any(
        json.loads(e["body"])["gpu"] is False
        for e in reopened.registry.get(frozen.request_id)["events"]
        if e["kind"] == "worker_resources"
    )
    reopened.registry.close()


def test_real_worker_supervision_targets_the_fitting_process(tmp_path):
    import os

    lab = ExperimentLab(tmp_path / "registry.sqlite", None, lambda: True)
    frozen = plan(evidence_kind="synthetic_qa")
    lab.registry.reserve(frozen, code_fingerprint())
    lab.registry.inputs(frozen.request_id, shifted_inputs())
    asyncio.run(lab.run_once())
    receipt = lab.registry.get(frozen.request_id)
    assert receipt["status"] == "completed"
    actual = next(
        json.loads(e["body"]) for e in receipt["events"] if e["kind"] == "worker_identity"
    )
    measured = next(
        json.loads(e["body"]) for e in receipt["events"] if e["kind"] == "worker_resources"
    )
    assert actual["pid"] == measured["supervised_pid"]
    if os.name == "nt":
        assert 1 <= actual["processors_allowed"] <= 2 and actual["priority_class"] == 0x40
        assert 0 < measured["peak_rss_bytes"] <= 256 * 1024**2
    lab.registry.close()


def test_disk_pressure_pauses_research_without_changing_financial_authority(tmp_path):
    from trading.tiered_runtime import TieredPaperRuntime

    runtime = object.__new__(TieredPaperRuntime)
    runtime._constrained_until = 0
    runtime.disk_free = 4 * 1024**3
    runtime._capture_failure = None
    # This fixture isolates disk admission with a current successful readback.
    runtime._readback_error = None
    runtime._readback_audit_mono = time.monotonic()
    runtime.receipts = {"balanced": True}
    assert runtime.constrained()
    lab = ExperimentLab(tmp_path / "registry.sqlite", None, lambda: not runtime.constrained())
    frozen = plan(evidence_kind="synthetic_qa")
    lab.registry.reserve(frozen, code_fingerprint())
    lab.registry.inputs(frozen.request_id, shifted_inputs())
    assert not asyncio.run(lab.run_once())
    assert lab.registry.status(frozen.request_id) == "queued" and lab.child is None
    runtime.disk_free = 6 * 1024**3
    assert asyncio.run(lab.run_once())
    assert lab.registry.status(frozen.request_id) == "completed"
    assert lab.snapshot()["limits"]["paid_usd"] == "0"
    lab.registry.close()
