"""Transport handoff and retained resource refusal; no loader or model execution."""

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest
from test_development_failure_receipts import (
    ANSWER,
    PACKET,
    TASK,
    response,
)
from test_development_failure_receipts import (
    failure_task as failure_task,
)
from test_peft_development import declared as declared

from trading.peft_profile import digest
from trading.peft_role_model import DevelopmentTransportFailure


def procedural_process(
    monkeypatch, profile, *, owned_peak, reported_peak=1, pin_fails=False, cpu_limit_fails=False
):
    """A procedural process boundary, with resident use distinct from launcher use."""
    state = {"events": [], "jobs": [], "owners": [], "launches": 0, "rss_reads": 0}

    class Child:
        pid = 12345
        returncode = None
        resumed = False
        cpu_limited = False

        def poll(self):
            return self.returncode

        def terminate(self):
            state["events"].append("terminate")
            self.returncode = 1

        def wait(self, timeout):
            if self.returncode is None:
                assert self.resumed, "The procedural child must remain paused before resume"
                self.returncode = 0
            return self.returncode

    child = Child()

    def launch(command, **kwargs):
        state["launches"] += 1
        state["creationflags"] = kwargs["creationflags"]
        job = Path(command[-1])
        state["jobs"].append(job)
        assert (job / "request.json").is_file()
        assert not (job / "owner-ready").exists()
        assert json.loads(json.loads((job / "request.json").read_text())["packet_json"]) == PACKET
        state["events"].append("launch")
        return child

    class Owner:
        def __init__(self, target, *, memory_limit=None, suspended=False):
            state["events"].append("pin")
            assert target is child and not child.resumed
            assert memory_limit == profile["max_rss_bytes"]
            if os.name == "nt":
                assert suspended is True
            assert not (state["jobs"][0] / "owner-ready").exists()
            if pin_fails:
                raise OSError("Procedural ownership establishment failed")
            self.target = target
            state["owners"].append(self)

        def resume(self):
            state["events"].append("resume")
            job = state["jobs"][0]
            assert (job / "owner-ready").read_text() == "owned"
            assert not self.target.resumed
            if os.name == "nt":
                assert self.target.cpu_limited, "Imports must inherit the frozen processor ceiling"
            self.target.resumed = True
            request = json.loads((job / "request.json").read_text())
            result = response(profile) | {"peak_rss_bytes": reported_peak}
            (job / "response.json").write_text(
                json.dumps({"request_sha256": digest(request), "response": result})
            )

        def rss(self):
            state["events"].append("owned_rss")
            assert self.target.resumed
            state["rss_reads"] += 1
            return owned_peak

        def close(self):
            state["events"].append("close")
            assert self.target.poll() is not None

    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launch)
    monkeypatch.setattr("trading.peft_role_model.ChildOwner", Owner)
    # The old launcher measurement is intentionally harmless. The protected
    # descendant aggregate must govern both refusal and retained peak instead.
    import trading.peft_role_model as module

    def limit_cpu(pid, *, distinct_cores=False):
        state["events"].append("cpu_limit")
        assert pid == child.pid and distinct_cores is True
        assert state["owners"] and not child.resumed
        assert not (state["jobs"][0] / "owner-ready").exists()
        if cpu_limit_fails:
            raise OSError("Procedural suspended-child processor limit failed")
        child.cpu_limited = True

    monkeypatch.setattr(module, "constrain_child", limit_cpu, raising=False)
    monkeypatch.setattr(module, "child_rss", lambda pid: 1, raising=False)
    state["child"] = child
    return state


def test_paused_child_is_pinned_with_frozen_limit_then_released_after_owner_ready(
    declared, monkeypatch
):
    model, _, _ = declared
    profile = model.declaration()[2]
    peak = 16 * 1024**2
    state = procedural_process(monkeypatch, profile, owned_peak=peak, reported_peak=1)
    answer = model.infer("researcher", PACKET, profile)
    pinned = ["launch", "pin"] + (["cpu_limit"] if os.name == "nt" else [])
    assert state["events"] == pinned + ["resume", "owned_rss", "close"]
    if os.name == "nt":
        assert state["creationflags"] & 0x4  # CREATE_SUSPENDED
        assert state["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert state["launches"] == state["rss_reads"] == 1
    assert answer["peak_rss_bytes"] == peak
    assert answer["complete"] is True and answer["answer"] == ANSWER
    retained = json.loads((state["jobs"][0] / "dispatch.json").read_text())
    assert retained["peak_rss_bytes"] == peak and retained["rss_observations"] == 1
    assert retained["cleanup_complete"] is True and retained["exit_code"] == 0
    assert retained["profile_sha256"] == digest(profile)


def test_failed_pin_never_releases_the_child_or_publishes_owner_ready(declared, monkeypatch):
    model, _, _ = declared
    profile = model.declaration()[2]
    state = procedural_process(monkeypatch, profile, owned_peak=1, pin_fails=True)
    with pytest.raises(DevelopmentTransportFailure) as caught:
        model.infer("researcher", PACKET, profile)
    assert state["events"] == ["launch", "pin", "terminate"]
    assert not state["child"].resumed and state["rss_reads"] == 0
    assert not (state["jobs"][0] / "owner-ready").exists()
    assert not (state["jobs"][0] / "response.json").exists()
    assert caught.value.receipt["complete"] is False
    assert caught.value.receipt["status"] == "child_ownership"
    assert caught.value.receipt["peak_rss_bytes"] is None
    assert caught.value.receipt["rss_observations"] == 0
    assert caught.value.receipt["child_terminated"] is True
    assert caught.value.receipt["cleanup_complete"] is False
    assert "OwnerCleanupUnverified" in caught.value.receipt["cleanup_error_types"]
    if os.name == "nt":
        assert state["creationflags"] & 0x4


def test_owned_descendant_over_budget_fails_even_when_launcher_rss_is_small(declared, monkeypatch):
    model, _, _ = declared
    profile = model.declaration()[2]
    peak = profile["max_rss_bytes"] + 1
    state = procedural_process(monkeypatch, profile, owned_peak=peak)
    with pytest.raises(DevelopmentTransportFailure) as caught:
        model.infer("researcher", PACKET, profile)
    retained = caught.value.receipt
    assert state["rss_reads"] == 1 and state["launches"] == 1
    assert retained["kind"] == "development_transport_failure"
    assert retained["status"] == "memory_budget" and retained["complete"] is False
    assert retained["peak_rss_bytes"] == peak and retained["rss_observations"] == 1
    assert retained["child_terminated"] is True and retained["cleanup_complete"] is True
    assert retained["profile_sha256"] == digest(profile)
    assert state["child"].poll() == 1 and "terminate" in state["events"]


def test_owner_ready_publication_failure_cleans_the_still_paused_child(declared, monkeypatch):
    model, _, _ = declared
    profile = model.declaration()[2]
    state = procedural_process(monkeypatch, profile, owned_peak=1)
    write = Path.write_text

    def fail_ready(path, *args, **kwargs):
        if path.name == "owner-ready":
            raise OSError("Procedural ownership-ready publication failed")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_ready)
    with pytest.raises(DevelopmentTransportFailure) as caught:
        model.infer("researcher", PACKET, profile)
    pinned = ["launch", "pin"] + (["cpu_limit"] if os.name == "nt" else [])
    assert state["events"] == pinned + ["terminate", "close"]
    assert not state["child"].resumed and state["rss_reads"] == 0
    assert caught.value.receipt["complete"] is False
    assert caught.value.receipt["child_terminated"] is True
    assert caught.value.receipt["cleanup_complete"] is True
    assert caught.value.receipt["peak_rss_bytes"] is None


@pytest.mark.skipif(os.name != "nt", reason="Suspended processor handoff is Windows-specific")
def test_processor_limit_failure_never_releases_the_pinned_child(declared, monkeypatch):
    model, _, _ = declared
    profile = model.declaration()[2]
    state = procedural_process(monkeypatch, profile, owned_peak=1, cpu_limit_fails=True)
    with pytest.raises(DevelopmentTransportFailure) as caught:
        model.infer("researcher", PACKET, profile)
    assert state["events"] == ["launch", "pin", "cpu_limit", "terminate", "close"]
    assert not state["child"].resumed and state["rss_reads"] == 0
    assert not (state["jobs"][0] / "owner-ready").exists()
    assert not (state["jobs"][0] / "response.json").exists()
    assert caught.value.receipt["complete"] is False
    assert caught.value.receipt["child_terminated"] is True
    assert caught.value.receipt["cleanup_complete"] is True


def test_late_reported_over_budget_peak_retains_exact_answer_as_failed_once(
    failure_task, monkeypatch
):
    model, worker = failure_task
    profile = model.declaration()[2]
    peak = profile["max_rss_bytes"] + 1
    state = procedural_process(monkeypatch, profile, owned_peak=1, reported_peak=peak)
    before = worker.get(TASK)
    with pytest.raises(DevelopmentTransportFailure) as caught:
        asyncio.run(worker.development_answer(TASK, model))
    failure = caught.value
    assert failure.receipt["status"] == "memory_budget"
    assert failure.response["complete"] is True
    assert failure.response["answer"] == ANSWER
    assert failure.response["raw_answer"] == "Original procedural answer"
    assert failure.response["peak_rss_bytes"] == peak
    attempt = worker.view(TASK)["attempts"][0]
    assert attempt["status"] == "failed"
    assert attempt["response"]["answer"] == ANSWER
    assert attempt["response"]["raw_answer"] == failure.response["raw_answer"]
    assert attempt["response"]["complete"] is True
    assert attempt["response"]["transport_failure"]["status"] == "memory_budget"
    assert attempt["profile"] == profile
    after = worker.get(TASK)
    assert all(before[key] == after[key] for key in ("stage", "status", "context", "result"))
    with pytest.raises(
        ValueError, match="Retained development transport failed; no invisible retry"
    ):
        asyncio.run(worker.development_answer(TASK, model))
    assert state["launches"] == 1 and len(after["attempts"]) == 1
    assert (
        worker.registry.db.execute(
            "SELECT count(*) FROM role_attempt_allowances WHERE task=?", (TASK,)
        ).fetchone()[0]
        == 1
    )
