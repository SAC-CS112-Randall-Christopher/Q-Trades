"""Finite GET-only paper observation; the sole operator invokes the original route.

No model dispatch, registry/financial SQL, process control or activation occurs
here. Same-host monotonic timestamps identify measured work and phase bounds.
The observer cannot establish actual model-child coexistence from request time.
"""

import argparse
import hashlib
import json
import math
import re
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

from trading.peft_profile import regular

BASE = "http://127.0.0.1:8780"
RESPONSE_BYTES = 2 * 1024**2
OUTPUT_BYTES = 32 * 1024**2
RECORD_BYTES = 65536


def encoded(value: Any) -> bytes:
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    if len(raw) > RECORD_BYTES:
        raise ValueError("Selected observation exceeds its private record bound")
    return raw


def failure_reason(exc: Exception) -> str:
    """Bounded diagnostics without copying response payloads or request secrets."""
    if isinstance(exc, httpx.HTTPStatusError):
        return "Loopback HTTP response " + str(exc.response.status_code)
    if isinstance(exc, json.JSONDecodeError):
        return ("Invalid JSON response: " + exc.msg)[:256]
    if isinstance(exc, UnicodeError):
        return "Invalid UTF-8 status response"
    if type(exc) in (ValueError, TimeoutError):
        return str(exc)[:256]  # Observer's own schema, identity and budget messages.
    return type(exc).__name__ + " during loopback observation or private receipt write"


def get_json(client: httpx.Client, path: str, deadline: float, now=time.monotonic):
    if path not in {"/api/status", "/api/health"}:
        raise ValueError("Observer reads only the existing loopback status/health routes")
    remaining = deadline - now()
    if remaining <= 0:
        raise TimeoutError("Observation deadline reached before request")
    raw = bytearray()
    with client.stream(
        "GET", BASE + path, timeout=min(2.0, remaining), follow_redirects=False
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            if now() >= deadline:
                raise TimeoutError("Observation deadline reached during response")
            if len(raw) + len(chunk) > RESPONSE_BYTES:
                raise ValueError("Status response exceeds 2MiB")
            raw.extend(chunk)

    def reject_nonfinite(value):
        raise ValueError("Nonfinite JSON value: " + value)

    body = json.loads(raw, parse_constant=reject_nonfinite)
    if not isinstance(body, dict):
        raise ValueError("Status response is not an object")
    return body, len(raw), hashlib.sha256(raw).hexdigest()


def phase_bounds(start: float, baseline: float, middle: float, recovery: float):
    values = (baseline, middle, recovery)
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in (start, *values)):
        raise ValueError("Phase bounds must be finite numeric monotonic values")
    if not (0 < baseline <= 300 and 20 < middle <= 600 and 0 < recovery <= 300):
        raise ValueError("Require baseline<=300, 20<middle<=600 and recovery<=300 seconds")
    if sum(values) > 1200:
        raise ValueError("Session exceeds its absolute 1200-second budget")
    return {
        "baseline_start": start,
        "middle_start": start + baseline,
        "cancel_at_monotonic": start + baseline + middle - 20,
        "recovery_start": start + baseline + middle,
        "session_end": start + sum(values),
        "cleanup_reserve_seconds": 20,
    }


def phase_at(bounds, observed_mono):
    if observed_mono < bounds["baseline_start"]:
        return "before_session"
    if observed_mono < bounds["middle_start"]:
        return "baseline"
    if observed_mono < bounds["recovery_start"]:
        return "middle"
    if observed_mono < bounds["session_end"]:
        return "recovery"
    return "after_session"


class WorkTrace:
    """Bounded deduplication of the existing latest-twenty diagnostic window."""

    def __init__(self, session_start: float | None = None):
        self.session_start = session_start
        self.epoch = None
        self.last_number = None
        self.last_mono = None
        self.seen = {}

    def consume(self, guard):
        epoch, count, window = (
            guard.get("observation_epoch"),
            guard.get("work_observations"),
            guard.get("current_window"),
        )
        if not isinstance(epoch, str) or not re.fullmatch(r"[0-9a-f]{32}", epoch):
            raise ValueError("Missing process observation epoch")
        if type(count) is not int or count < 0 or not isinstance(window, list) or len(window) > 20:
            raise ValueError("Missing bounded cumulative work window")
        gaps, fresh, pending = [], [], {}
        last_number, last_mono = self.last_number, self.last_mono
        if self.epoch is not None and epoch != self.epoch:
            gaps.append({"kind": "process_observation_restart", "previous_epoch": self.epoch})
            last_number, last_mono = None, None
        if last_number is not None and count < last_number:
            raise ValueError("Cumulative work counter regressed within one epoch")
        previous = 0
        for sample in window:
            if not isinstance(sample, dict):
                raise ValueError("Work observation is not an object")
            number, stamp, elapsed = (
                sample.get("work_number"),
                sample.get("observed_mono"),
                sample.get("elapsed_ms"),
            )
            if (
                type(number) is not int
                or not previous < number <= count
                or sample.get("observation_epoch") != epoch
                or any(
                    type(v) not in (float, int) or not math.isfinite(v) for v in (stamp, elapsed)
                )
                or elapsed < 0
            ):
                raise ValueError("Invalid actual work identity/duration")
            previous = number
            identity = (epoch, number)
            digest = hashlib.sha256(encoded(sample)).hexdigest()
            if identity in self.seen:
                if self.seen[identity] != digest:
                    raise ValueError("An observed work identity changed")
                continue
            if len(self.seen) + len(pending) >= 10000:
                raise ValueError("Finite work-observation count exhausted")
            if last_number is not None:
                if number <= last_number or (last_mono is not None and stamp < last_mono):
                    raise ValueError("Unseen work observation regressed")
                if last_mono is not None and stamp - last_mono > 2:
                    gaps.append(
                        {
                            "kind": "completed_work_observation_gap",
                            "seconds": stamp - last_mono,
                            "observation_epoch": epoch,
                            "work_number": number,
                        }
                    )
                if number != last_number + 1:
                    gaps.append(
                        {
                            "kind": "missing_work_numbers",
                            "first": last_number + 1,
                            "last": number - 1,
                            "observation_epoch": epoch,
                        }
                    )
            pending[identity] = digest
            last_number, last_mono = number, stamp
            fresh.append(sample)
        if window and previous != count:
            gaps.append({"kind": "cumulative_count_outside_retained_window", "count": count})
        if count and not window:
            gaps.append({"kind": "missing_retained_window", "count": count})
        if self.epoch is None and self.session_start is not None and window:
            first = window[0]
            if first["work_number"] > 1 and first["observed_mono"] >= self.session_start:
                gaps.append(
                    {
                        "kind": "initial_session_boundary_unverified",
                        "first_retained_work_number": first["work_number"],
                        "first_retained_observed_mono": first["observed_mono"],
                        "session_start_mono": self.session_start,
                        "unobserved_prefix_last_work_number": first["work_number"] - 1,
                        "scope": "Cannot prove omitted work predates the session; not zero gaps",
                    }
                )
        if count == 0:
            last_number = 0  # A completed empty snapshot anchors subsequent sequence coverage.
        # A malformed response cannot partially advance deduplication and erase
        # otherwise valid observations from the next complete response.
        self.epoch, self.last_number, self.last_mono = epoch, last_number, last_mono
        self.seen.update(pending)
        return fresh, gaps


def select_status(body):
    paper = body["paper"]
    performance = paper["performance"]
    guard = performance["resource_guard"]
    accounts = paper["accounts"]
    if not isinstance(accounts, dict) or len(accounts) > 20:
        raise ValueError("Account observation exceeds the existing twenty-slot bound")
    activity = {}
    for name, account in accounts.items():
        if not isinstance(account["positions"], dict) or not isinstance(account["pending"], dict):
            raise ValueError("Natural position/pending-order observation unavailable")
        activity[name] = {
            "positions": len(account["positions"]),
            "pending_orders": len(account["pending"]),
            "valuation_fresh": account["valuation_fresh"],
        }
    selected = {
        "paper": {
            key: paper[key]
            for key in (
                "running",
                "error",
                "stale",
                "paused",
                "started_at",
                "last_tick",
                "gaps",
                "research_constrained",
            )
        },
        "journal": paper["journal"],
        "financial_readback": performance["financial_readback"],
        "resource_guard": {
            key: value
            for key, value in guard.items()
            if key not in {"current_window", "last_trigger", "unreported_peak"}
        },
        "storage": paper["storage"],
        "research_evidence": paper["research_evidence"],
        "natural_account_activity": activity,
    }
    encoded(selected)
    return selected, guard


def run_session(
    output: Path, expected_commit: str, bounds, client, now=time.monotonic, sleep=time.sleep
):
    """Observe only. Separate operator command and final receipts remain authoritative."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("Expected installed commit must be full lowercase 40-hex")
    regular(output.absolute())
    output.mkdir()  # Exclusive directory; never replace a previous receipt.
    trace = WorkTrace(bounds["baseline_start"])
    phases, gaps = {name: [] for name in ("baseline", "middle", "recovery")}, []
    total_bytes, polls, health_checks = 0, 0, {}
    controls = {
        "format": "qtrades-finite-coexistence-observer-v1",
        "expected_commit": expected_commit,
        "bounds": bounds,
        "model_dispatch_by_observer": False,
    }
    (output / "session-control.json").write_bytes(encoded(controls))
    active_phase = None
    stopped, stopped_reason = None, None
    with (output / "observations.jsonl").open("xb") as observations:

        def record(row):
            nonlocal total_bytes
            raw = encoded(row) + b"\n"
            if total_bytes + len(raw) > OUTPUT_BYTES:
                raise ValueError("Finite private observation output budget exhausted")
            observations.write(raw)
            observations.flush()
            total_bytes += len(raw)

        try:
            while now() < bounds["session_end"]:
                requested = now()
                phase = phase_at(bounds, requested)
                if phase != active_phase:
                    active_phase = phase
                    try:
                        health, size, digest = get_json(
                            client, "/api/health", bounds["session_end"], now
                        )
                        if health.get("code_commit") != expected_commit:
                            raise ValueError(
                                "Installed health identity differs from approved commit"
                            )
                        health_checks[phase] = True
                        record(
                            {
                                "kind": "phase_health",
                                "phase": phase,
                                "body": health,
                                "response_bytes": size,
                                "response_sha256": digest,
                            }
                        )
                    except Exception as exc:
                        health_checks[phase] = False
                        gap = {
                            "kind": "phase_identity_unavailable",
                            "phase": phase,
                            "error_type": type(exc).__name__,
                            "error_reason": failure_reason(exc),
                            "at_mono": now(),
                        }
                        gaps.append(gap)
                        record(gap)
                    if phase == "middle":
                        control = controls | {
                            "phase": phase,
                            "recorded_mono": now(),
                            "installed_identity_verified": health_checks[phase],
                            "full_guard_recheck_required": True,
                            "dispatch_authorized_by_observer": False,
                        }
                        (output / "dispatch-window.json").write_bytes(encoded(control))
                try:
                    body, size, digest = get_json(client, "/api/status", bounds["session_end"], now)
                    selected, guard = select_status(body)
                    fresh, missing = trace.consume(guard)
                    for gap in missing:
                        gap = gap | {"phase": phase, "at_mono": now()}
                        gaps.append(gap)
                        record(gap)
                    for sample in fresh:
                        measured_phase = phase_at(bounds, sample["observed_mono"])
                        record({"kind": "whole_work", "phase": measured_phase, "sample": sample})
                        if measured_phase in phases:
                            phases[measured_phase].append(sample["elapsed_ms"])
                    record(
                        {
                            "kind": "status",
                            "phase": phase,
                            "requested_mono": requested,
                            "completed_mono": now(),
                            "response_bytes": size,
                            "response_sha256": digest,
                            "selected": selected,
                        }
                    )
                except Exception as exc:
                    gap = {
                        "kind": "status_unavailable_or_invalid",
                        "phase": phase,
                        "error_type": type(exc).__name__,
                        "error_reason": failure_reason(exc),
                        "at_mono": now(),
                    }
                    gaps.append(gap)
                    record(gap)
                polls += 1
                if polls >= 1300:
                    raise ValueError("Finite observation request count exhausted")
                sleep(max(0, min(1.0 - (now() - requested), bounds["session_end"] - now())))
        except Exception as exc:
            stopped = type(exc).__name__
            stopped_reason = failure_reason(exc)
    finished = now()
    overrun = max(0, finished - bounds["session_end"])
    summary = {
        **controls,
        "finished_mono": finished,
        "deadline_overrun_seconds": overrun,
        "incomplete_observation": (
            finished < bounds["session_end"] or stopped is not None or overrun > 0 or bool(gaps)
        ),
        "polls": polls,
        "recorded_bytes": total_bytes,
        "phase_identity_checks": health_checks,
        "coverage_gap_count": len(gaps),
        "coverage_gap_kinds": {
            kind: sum(row["kind"] == kind for row in gaps) for kind in {row["kind"] for row in gaps}
        },
        "coverage_gap_receipts": "All gaps retained in observations.jsonl",
        "stopped_error_type": stopped,
        "stopped_error_reason": stopped_reason,
        "reached_session_end": finished >= bounds["session_end"],
        "phases": {
            name: {
                "distinct_work_samples": len(values),
                "median_ms": statistics.median(values) if values else None,
                "maximum_ms": max(values) if values else None,
                "target_exceedances_over100": sum(v > 100 for v in values),
                "blocking_samples_at_or_above500": sum(v >= 500 for v in values),
                "severe_samples_at_or_above1000": sum(v >= 1000 for v in values),
            }
            for name, values in phases.items()
        },
        "actual_child_coexistence_verified": False,
        "operating_acceptance": False,
        "scope": "GET-only observer; child identity, original attempt/result and financial "
        "preservation require the separate existing owners' receipts; missing "
        "samples cannot establish continuous coverage or causation",
    }
    (output / "summary.json").write_bytes(encoded(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--baseline-seconds", type=float, default=300)
    parser.add_argument("--middle-seconds", type=float, default=600)
    parser.add_argument("--recovery-seconds", type=float, default=300)
    args = parser.parse_args()
    bounds = phase_bounds(
        time.monotonic(), args.baseline_seconds, args.middle_seconds, args.recovery_seconds
    )
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        summary = run_session(args.output_dir, args.expected_commit, bounds, client)
    print(
        json.dumps(
            {
                "output": str(args.output_dir),
                "reached_session_end": summary["reached_session_end"],
                "coverage_gaps": summary["coverage_gap_count"],
                "stopped_error_type": summary["stopped_error_type"],
            }
        )
    )


if __name__ == "__main__":
    main()
