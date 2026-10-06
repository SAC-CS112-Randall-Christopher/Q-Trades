"""Finite source/HTTP fixtures; no operating requests or trained-model execution."""

import asyncio
import copy
import json
import sys
import time
from types import SimpleNamespace

import httpx
import pytest
from test_paper_store import pg_store as pg_store
from test_peft_development import DevelopmentStub
from test_role_worker import make_lab

from scripts import answer_development_role as route
from scripts.observe_model_coexistence import (
    RESPONSE_BYTES,
    WorkTrace,
    failure_reason,
    get_json,
    phase_bounds,
    run_session,
)
from trading.role_worker import Question, RoleWorker

EPOCH = "e" * 32
COMMIT = "a" * 40


def guard(numbers, epoch=EPOCH):
    return {
        "observation_epoch": epoch,
        "work_observations": max(numbers, default=0),
        "current_window": [
            {
                "observation_epoch": epoch,
                "work_number": number,
                "observed_mono": 1000.0 + number - 1,
                "at": 1800000000.0 + number,
                "elapsed_ms": 50.0,
            }
            for number in numbers
        ],
    }


def status(work):
    return {
        "paper": {
            "running": True,
            "error": None,
            "stale": False,
            "paused": False,
            "started_at": 1800000000.0,
            "last_tick": 1800000100.0,
            "gaps": 0,
            "research_constrained": False,
            "accounts": {
                "fixture": {"positions": {"BTCUSD": {}}, "pending": {}, "valuation_fresh": True}
            },
            "journal": {
                "available": False,
                "status": "expired",
                "balanced": True,
                "revision": 100,
                "audit_age_seconds": 121,
            },
            "performance": {
                "resource_guard": work,
                "financial_readback": {"available": False, "status": "expired"},
            },
            "storage": {"capture_error": None, "disk_free_gib": 30},
            "research_evidence": {"fixture": True},
        }
    }


def test_phase_budgets_reserve_twenty_seconds_without_extending_profile():
    bounds = phase_bounds(1000, 300, 600, 300)
    assert bounds["middle_start"] == 1300
    assert bounds["cancel_at_monotonic"] == 1880
    assert bounds["recovery_start"] == 1900
    assert bounds["session_end"] == 2200
    assert bounds["cleanup_reserve_seconds"] == 20


@pytest.mark.parametrize(
    "values",
    [
        (301, 600, 300),
        (300, 601, 300),
        (300, 600, 301),
        (0, 600, 300),
        (300, 20, 300),
        (float("nan"), 600, 300),
    ],
)
def test_invalid_phase_budgets_refuse(values):
    with pytest.raises(ValueError):
        phase_bounds(1000, *values)


def test_overlapping_windows_deduplicate_and_missing_sequence_is_explicit():
    trace = WorkTrace()
    samples, gaps = trace.consume(guard([1, 2, 3]))
    assert len(samples) == 3 and not gaps
    samples, gaps = trace.consume(guard([2, 3, 4]))
    assert [s["work_number"] for s in samples] == [4] and not gaps
    samples, gaps = trace.consume(guard([7, 8]))
    assert [s["work_number"] for s in samples] == [7, 8]
    assert gaps == [
        {
            "kind": "completed_work_observation_gap",
            "seconds": 3.0,
            "observation_epoch": EPOCH,
            "work_number": 7,
        },
        {"kind": "missing_work_numbers", "first": 5, "last": 6, "observation_epoch": EPOCH},
    ]


def test_restart_is_not_stitched_into_previous_work_epoch():
    trace = WorkTrace()
    trace.consume(guard([1, 2]))
    samples, gaps = trace.consume(guard([1], "f" * 32))
    assert len(samples) == 1
    assert gaps == [{"kind": "process_observation_restart", "previous_epoch": EPOCH}]


def test_distinct_consecutive_work_can_share_coarse_monotonic_timestamp():
    trace = WorkTrace()
    same_clock = guard([1, 2])
    same_clock["current_window"][1]["observed_mono"] = 1000.0
    samples, gaps = trace.consume(same_clock)
    assert [row["work_number"] for row in samples] == [1, 2] and not gaps
    assert trace.consume(same_clock) == ([], [])
    regressed = copy.deepcopy(same_clock)
    regressed["work_observations"] = 3
    regressed["current_window"].append(
        same_clock["current_window"][1] | {"work_number": 3, "observed_mono": 999.9}
    )
    with pytest.raises(ValueError, match="regressed"):
        trace.consume(regressed)


def test_changed_identity_and_counter_regression_are_not_accepted():
    trace = WorkTrace()
    trace.consume(guard([1, 2]))
    changed = guard([1, 2])
    changed["current_window"][0]["elapsed_ms"] = 60
    with pytest.raises(ValueError, match="identity changed"):
        trace.consume(changed)
    with pytest.raises(ValueError, match="counter regressed"):
        trace.consume(guard([1]))


def test_invalid_tail_does_not_erase_valid_work_from_next_complete_response():
    trace = WorkTrace()
    malformed = guard([1, 2])
    malformed["current_window"][1]["elapsed_ms"] = float("nan")
    with pytest.raises(ValueError):
        trace.consume(malformed)
    samples, gaps = trace.consume(guard([1, 2]))
    assert len(samples) == 2 and not gaps


def test_retained_pre_session_history_can_prove_omitted_prefix_is_historical():
    trace = WorkTrace(1000.0)
    historical = guard(list(range(81, 101)))
    for index, sample in enumerate(historical["current_window"]):
        sample["observed_mono"] = 990.0 + index * 0.5
    samples, gaps = trace.consume(historical)
    assert len(samples) == 20 and not gaps


def test_empty_counter_anchor_exposes_later_missed_sequence():
    trace = WorkTrace(1000.0)
    assert trace.consume(guard([])) == ([], [])
    _, gaps = trace.consume(guard([81, 82]))
    assert gaps == [
        {"kind": "missing_work_numbers", "first": 1, "last": 80, "observation_epoch": EPOCH}
    ]


def test_failure_reason_is_bounded_without_copying_http_response_body():
    request = httpx.Request("GET", "http://127.0.0.1:8780/api/status")
    response = httpx.Response(403, request=request, text="private payload secret")
    error = httpx.HTTPStatusError("private payload secret", request=request, response=response)
    assert failure_reason(error) == "Loopback HTTP response 403"
    assert len(failure_reason(ValueError("x" * 1000))) == 256


def test_stream_read_stops_at_bound_before_json_decode():
    def response(request):
        return httpx.Response(200, content=b" " * (RESPONSE_BYTES + 1))

    with httpx.Client(transport=httpx.MockTransport(response), trust_env=False) as client:
        with pytest.raises(ValueError, match="2MiB"):
            get_json(client, "/api/status", 1002, now=lambda: 1000)


def test_remote_redirect_is_never_followed_even_with_following_client():
    calls = []

    def response(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.invalid/private"})

    with httpx.Client(
        transport=httpx.MockTransport(response), follow_redirects=True, trust_env=False
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            get_json(client, "/api/status", 1002, now=lambda: 1000)
    assert calls == ["http://127.0.0.1:8780/api/status"]


def test_expired_read_and_unknown_route_make_no_request():
    calls = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: calls.append(request)), trust_env=False
    ) as client:
        with pytest.raises(TimeoutError):
            get_json(client, "/api/status", 1000, now=lambda: 1000)
        with pytest.raises(ValueError):
            get_json(client, "@example.invalid", 1002, now=lambda: 1000)
    assert not calls


def test_completed_http_fixture_retains_expired_audit_and_unknown_child(tmp_path):
    clock = [1000.0]
    calls = []

    def response(request):
        calls.append(request.url.path)
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"code_commit": COMMIT})
        number = int(clock[0] - 1000) + 1
        return httpx.Response(200, json=status(guard(list(range(max(1, number - 2), number + 1)))))

    def sleep(seconds):
        clock[0] += seconds

    output = tmp_path / "fresh-private-fixture"
    with httpx.Client(transport=httpx.MockTransport(response), trust_env=False) as client:
        summary = run_session(
            output, COMMIT, phase_bounds(1000, 1, 21, 1), client, now=lambda: clock[0], sleep=sleep
        )
    assert summary["reached_session_end"] and not summary["stopped_error_type"]
    assert summary["phase_identity_checks"] == dict.fromkeys(
        ["baseline", "middle", "recovery"], True
    )
    assert [v["distinct_work_samples"] for v in summary["phases"].values()] == [1, 21, 1]
    assert summary["coverage_gap_count"] == 0
    assert summary["deadline_overrun_seconds"] == 0 and not summary["incomplete_observation"]
    assert not summary["actual_child_coexistence_verified"] and not summary["operating_acceptance"]
    control = json.loads((output / "dispatch-window.json").read_text())
    assert control["bounds"]["cancel_at_monotonic"] == 1002
    assert control["installed_identity_verified"] and control["full_guard_recheck_required"]
    assert not control["dispatch_authorized_by_observer"]
    rows = [json.loads(row) for row in (output / "observations.jsonl").read_text().splitlines()]
    observed = next(row["selected"] for row in rows if row["kind"] == "status")
    assert observed["journal"]["balanced"] is True and observed["journal"]["available"] is False
    assert observed["journal"]["status"] == observed["financial_readback"]["status"] == "expired"
    assert observed["natural_account_activity"]["fixture"]["positions"] == 1
    assert set(calls) == {"/api/health", "/api/status"}
    with httpx.Client(transport=httpx.MockTransport(response), trust_env=False) as client:
        with pytest.raises(FileExistsError):
            run_session(
                output,
                COMMIT,
                phase_bounds(1000, 1, 21, 1),
                client,
                now=lambda: clock[0],
                sleep=sleep,
            )


def test_finite_http_outage_retains_all_failures_and_unverified_dispatch_identity(tmp_path):
    clock = [1000.0]

    def response(request):
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"code_commit": "b" * 40})
        raise httpx.ConnectError("Procedural fixture unavailable", request=request)

    def sleep(seconds):
        clock[0] += seconds

    output = tmp_path / "fresh-outage-fixture"
    with httpx.Client(transport=httpx.MockTransport(response), trust_env=False) as client:
        summary = run_session(
            output, COMMIT, phase_bounds(1000, 1, 21, 1), client, now=lambda: clock[0], sleep=sleep
        )
    assert summary["reached_session_end"] and not summary["stopped_error_type"]
    assert summary["coverage_gap_count"] == 26
    assert summary["coverage_gap_kinds"] == {
        "phase_identity_unavailable": 3,
        "status_unavailable_or_invalid": 23,
    }
    assert not any(summary["phase_identity_checks"].values())
    rows = [json.loads(row) for row in (output / "observations.jsonl").read_text().splitlines()]
    assert len(rows) == summary["coverage_gap_count"]
    control = json.loads((output / "dispatch-window.json").read_text())
    assert not control["installed_identity_verified"]
    assert not control["dispatch_authorized_by_observer"]
    assert not summary["operating_acceptance"] and not summary["actual_child_coexistence_verified"]
    assert summary["incomplete_observation"]


def test_first_partial_window_after_baseline_retains_unverified_beginning(tmp_path):
    clock = [1000.0]
    partial = guard(list(range(81, 101)))
    for index, sample in enumerate(partial["current_window"], start=1):
        sample["observed_mono"] = 1000.0 + index * 0.005

    def response(request):
        if request.url.path == "/api/health":
            if clock[0] == 1000:
                clock[0] += 0.5  # First status is delayed while actual work accumulates.
            return httpx.Response(200, json={"code_commit": COMMIT})
        return httpx.Response(200, json=status(partial))

    def sleep(seconds):
        clock[0] += seconds

    output = tmp_path / "partial-first-window-fixture"
    with httpx.Client(transport=httpx.MockTransport(response), trust_env=False) as client:
        summary = run_session(
            output, COMMIT, phase_bounds(1000, 1, 21, 1), client, now=lambda: clock[0], sleep=sleep
        )
    assert summary["coverage_gap_count"] == 1
    rows = [json.loads(row) for row in (output / "observations.jsonl").read_text().splitlines()]
    missing = [row for row in rows if row["kind"] == "initial_session_boundary_unverified"]
    assert len(missing) == 1 and missing[0]["first_retained_work_number"] == 81
    assert summary["incomplete_observation"]


def test_delayed_response_discloses_deadline_overrun_as_incomplete(tmp_path):
    clock, calls = [1000.0], []

    def response(request):
        calls.append(request.url.path)
        clock[0] = 1024.0
        return httpx.Response(200, json={"code_commit": COMMIT})

    with httpx.Client(transport=httpx.MockTransport(response), trust_env=False) as client:
        summary = run_session(
            tmp_path / "delayed-response-fixture",
            COMMIT,
            phase_bounds(1000, 1, 21, 1),
            client,
            now=lambda: clock[0],
            sleep=lambda seconds: None,
        )
    assert summary["deadline_overrun_seconds"] == 1
    assert summary["incomplete_observation"] and summary["reached_session_end"]
    assert calls == ["/api/health"]  # No further request after the deadline.


@pytest.mark.parametrize("deadline", ["0", "nan", "inf", "-inf"])
def test_cli_invalid_or_expired_deadline_refuses_before_registry(tmp_path, monkeypatch, deadline):
    created = []
    monkeypatch.setattr(route, "ExperimentRegistry", lambda path: created.append(path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "answer_development_role.py",
            "--registry",
            str(tmp_path / "absent.sqlite3"),
            "--task",
            "original",
            "--authorized-development-inference",
            "--cancel-at-monotonic=" + deadline,
        ],
    )
    with pytest.raises(SystemExit) as error:
        route.main()
    assert error.value.code == 2 and not created


def test_deadline_waits_for_existing_async_owner_cleanup(monkeypatch):
    retained = []
    # Control admission time without changing asyncio's scheduling clock.
    monkeypatch.setattr(route, "time", SimpleNamespace(monotonic=lambda: 1000.0))

    async def execute():
        entered = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        class Owner:
            async def development_answer(self, task, transport):
                try:
                    entered.set()
                    await asyncio.Event().wait()
                finally:
                    cleanup_started.set()
                    await release_cleanup.wait()
                    retained.append((task, transport))

        pending = asyncio.create_task(
            route.answer_with_deadline(Owner(), "original", "transport", 1000.01)
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            await asyncio.wait_for(cleanup_started.wait(), timeout=5)
            assert not pending.done()  # Check before asyncio.run can perform shutdown cleanup.
            release_cleanup.set()
            with pytest.raises(TimeoutError):
                await pending
            assert retained == [("original", "transport")]
        finally:
            release_cleanup.set()
            if not pending.done():
                pending.cancel()
            await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), timeout=5)

    asyncio.run(execute())


def test_expired_deadline_refuses_before_async_owner_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(route, "time", SimpleNamespace(monotonic=lambda: 1000.0))

    class Owner:
        async def development_answer(self, task, transport):
            calls.append((task, transport))

    with pytest.raises(TimeoutError, match="expired before dispatch"):
        asyncio.run(route.answer_with_deadline(Owner(), "original", "transport", 1000.0))
    assert not calls


def test_normal_return_without_experiment_deadline_is_unchanged():
    original = {"complete": False, "raw_answer": "retained original"}

    class Owner:
        async def development_answer(self, task, transport):
            return original

    assert asyncio.run(route.answer_with_deadline(Owner(), "original", None, None)) is original


def test_real_worker_deadline_retains_late_original_once_without_stage_change(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    worker = RoleWorker(lab.registry, lab)
    task = worker.enqueue(Question(question="Procedural original deadline/retention fixture."))
    original = copy.deepcopy(worker.get(task["id"]))
    model = DevelopmentStub()
    model.slow = True
    model.cancel = lambda: model.release.set()

    async def execute():
        with pytest.raises(TimeoutError):
            await route.answer_with_deadline(worker, task["id"], model, time.monotonic() + 0.5)

    try:
        asyncio.run(execute())
        retained = worker.get(task["id"])
        assert retained["stage"] == original["stage"] == "idea"
        assert retained["status"] == original["status"]
        assert len(retained["attempts"]) == 1
        assert json.loads(retained["attempts"][0]["response"])["raw_answer"] == "fixture"
        assert retained["attempts"][0]["finished"] is not None
        assert (
            asyncio.run(worker.development_answer(task["id"], model)).action == "propose_experiment"
        )
        assert len(model.calls) == 1 and store.reconcile()["balanced"]
    finally:
        lab.registry.close()
