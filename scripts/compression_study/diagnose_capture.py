"""Bounded observation of the unchanged capture-owner test in private disposable state."""

import argparse
import contextlib
import io
import os
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

import psutil

from trading.ownership import CollectorLock

from .codecs import StudyError
from .resources import MEMORY_LIMIT, Scratch, own_memory, workloads

NODE = (
    "tests/test_capture_recovery.py::"
    "test_normal_recorder_retries_busy_startup_recovers_and_records_without_manual_repair"
)
LIMIT = 2000


def diagnostic(task: dict[str, Any]) -> dict[str, Any]:
    from .run import source_identity

    if source_identity() != task["source_files"]:
        raise StudyError("Source changed before capture diagnostic")
    if os.name == "nt" and psutil.Process().nice() != psutil.IDLE_PRIORITY_CLASS:
        raise StudyError("Capture diagnostic child must remain at IDLE priority")
    base_temp = Path(task["basetemp"])
    if base_temp.exists():
        raise StudyError("Capture diagnostic never reuses a pytest basetemp")
    progress = Path(task["progress_receipt"]).open("x", encoding="utf-8", buffering=1)
    origin = time.perf_counter()

    def observe(entry: dict[str, Any]) -> None:
        # Private diagnostic observations, not durable publication or benchmark samples.
        progress.write(json.dumps(entry, allow_nan=False) + "\n")

    observe({"at_s": 0.0, "event": "diagnostic-start"})
    import_started, import_cpu = time.perf_counter(), time.process_time()
    import pytest

    import_timing = {
        "wall_s": time.perf_counter() - import_started,
        "cpu_s": time.process_time() - import_cpu,
    }
    observe({"at_s": time.perf_counter() - origin, "event": "pytest-import", **import_timing})
    events: list[dict[str, Any]] = []
    frames: dict[int, int] = {}
    threads: dict[int, int] = {}
    reports: list[dict[str, Any]] = []
    dropped = 0

    def profile(frame: FrameType, event: str, arg: Any) -> None:
        nonlocal dropped
        if event not in {"call", "return"}:
            return
        filename = frame.f_code.co_filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        name = frame.f_code.co_name
        selected = (
            filename == "research_storage.py"
            and name in {
                "__init__", "_initialize", "_recovery_source", "_housekeeping",
                "continue_legacy", "continue_compact", "admission", "append", "snapshot", "close",
            }
            or filename == "evidence_runtime.py"
            and name in {"_write_batch", "_write_batch_inner", "_mature_due"}
            or filename == "ownership.py" and name in {"acquire", "release"}
            or filename == "test_capture_recovery.py" and name == "observe"
        )
        if not selected:
            return
        if len(events) >= LIMIT:
            dropped += 1
            return
        frame_number = frames.setdefault(id(frame), len(events) + 1)
        thread_number = threads.setdefault(threading.get_ident(), len(threads) + 1)
        entry: dict[str, Any] = {
            "at_s": time.perf_counter() - origin, "event": event,
            "source": filename, "function": name, "frame": frame_number, "thread": thread_number,
        }
        recorder = frame.f_locals.get("recorder")
        if recorder is None and filename == "evidence_runtime.py":
            recorder = frame.f_locals.get("self")
        if recorder is not None and hasattr(recorder, "status"):
            entry["recorder_state"] = recorder.status.get("state")
            entry["recorder_reason"] = recorder.status.get("reason")
        events.append(entry)
        observe(entry)
        if event == "return":
            frames.pop(id(frame), None)

    class Observer:
        def pytest_collection_finish(self, session: Any) -> None:
            observe({"at_s": time.perf_counter() - origin, "event": "collection-finished"})

        def pytest_runtest_setup(self, item: Any) -> None:
            observe({"at_s": time.perf_counter() - origin, "event": "test-setup"})

        def pytest_runtest_call(self, item: Any) -> None:
            entry = {"at_s": time.perf_counter() - origin, "event": "test-call"}
            events.append(entry)
            observe(entry)

        def pytest_runtest_logreport(self, report: Any) -> None:
            reports.append({
                "when": report.when, "outcome": report.outcome, "duration_s": report.duration,
            })
            observe({"at_s": time.perf_counter() - origin, "event": "test-report", **reports[-1]})

    out, err = io.StringIO(), io.StringIO()
    previous, thread_previous = sys.getprofile(), threading.getprofile()
    try:
        if task["diagnostic_mode"] == "trace":
            threading.setprofile(profile)
            sys.setprofile(profile)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exit_code = int(pytest.main(
                ["-q", "-p", "no:cacheprovider", "--tb=long", "--basetemp", str(base_temp), NODE],
                plugins=[Observer()],
            ))
    finally:
        sys.setprofile(previous)
        threading.setprofile(thread_previous)
        progress.close()
    return {
        "operation": "capture-diagnostic", "mode": task["diagnostic_mode"],
        "pytest_exit_code": exit_code, "reports": reports, "events": events,
        "dropped_events": dropped, "import_pytest": import_timing,
        "elapsed_wall_s": time.perf_counter() - origin,
        "startup": getattr(sys, "_compression_startup", {}),
        "memory": own_memory(), "pytest_stdout": out.getvalue(), "pytest_stderr": err.getvalue(),
        "limitation": (
            "Tracing adds overhead; current observations do not explain historical failures"
        ),
    }


def execute(args: argparse.Namespace) -> Path:
    from .run import source_identity, supervised, write_json

    if os.name == "nt":
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    scratch = Scratch(Path(args.scratch), args.owner_token, Path(args.live_root))
    lock = CollectorLock(scratch.work / ".study.claim")
    lock.acquire()
    try:
        folder = scratch.work / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-capture-" + uuid.uuid4().hex[:8]
        )
        folder.mkdir()
        sources = source_identity()
        metadata = {
            "source_base": args.base, "source_files": sources, "workload": workloads(),
            "diagnostic_mode": args.diagnose_capture,
            "operation_deadline_seconds": 60, "memory_limit_bytes": MEMORY_LIMIT,
        }
        write_json(folder / "run-start.json", metadata)
        scratch.check(additional=32 * 1024**2)
        task = {
            **metadata, "operation": "capture-diagnostic", "basetemp": str(folder / "pytest"),
            "progress_receipt": str(folder / "progress-private.jsonl"),
        }
        write_json(folder / "task.json", task)
        try:
            result = supervised(folder / "task.json", folder / "receipt.json",
                                deadline=time.monotonic() + 60)
        except Exception as exc:
            write_json(folder / "results-private.json", {
                **metadata, "failures": [{"failure_type": type(exc).__name__, "reason": str(exc)}],
                "source_unchanged": sources == source_identity(), "status": "failed-diagnostic",
            })
            return folder
        result["source_unchanged"] = sources == source_identity()
        failures = []
        if result["pytest_exit_code"]:
            failures.append({"failure_type": "CaptureTestFailure"})
        if not result["source_unchanged"]:
            failures.append({"reason": "Source changed during capture diagnostic"})
        write_json(folder / "results-private.json", {**metadata, **result, "failures": failures})
        return folder
    finally:
        lock.release()
