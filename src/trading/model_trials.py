"""Bounded, read-only presentation of local model evaluation receipts."""

import hashlib
import json
import math
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from trading.research_protocol import ROLES, protocol_hash

NAME = re.compile(r"research-roles-(dev|holdout)-(\d{8}T\d{6}Z)\.json\Z")
MAX_SCAN = 500
MAX_RUNS = 8
MAX_READS = 24
MAX_BYTES = 2_000_000
MAX_ROWS = 1000


def short(value: Any, limit: int = 900) -> str:
    return value[:limit] if isinstance(value, str) else ""


def strings(value: Any, limit: int = 8) -> list[str]:
    return (
        [short(v, 240) for v in value[:limit] if isinstance(v, str)]
        if isinstance(value, list)
        else []
    )


def result_view(row: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    try:
        answer = json.loads(row.get("response", ""))
    except (TypeError, ValueError):
        answer = {}
    if not isinstance(answer, dict):
        answer = {}
    inputs = evidence.get(short(row.get("case"), 160))
    # Whitelist final explanation fields. Never expose prompts or private reasoning.
    return {
        "case": short(row.get("case"), 160),
        "model": short(row.get("model"), 160),
        "role": short(row.get("role"), 30),
        "seed": row.get("seed") if isinstance(row.get("seed"), int) else None,
        "seconds": row.get("seconds") if isinstance(row.get("seconds"), (int, float)) else None,
        "passed": row.get("passed") is True,
        "complete": row.get("complete") is True,
        "errors": strings(row.get("errors")),
        "critical": strings(row.get("critical")),
        "decision": short(answer.get("decision"), 60),
        "rationale": short(answer.get("rationale")),
        "evidence_ids": strings(answer.get("evidence_ids"), 12),
        "input_evidence": inputs,
        "explanation_truncated": len(str(answer.get("rationale", ""))) > 900,
    }


def run_view(
    report: dict[str, Any], name: str, modified: float, now: float, evidence: dict[str, Any]
) -> dict[str, Any]:
    rows = report.get("results", [])
    if (
        not isinstance(rows, list)
        or len(rows) > MAX_ROWS
        or any(not isinstance(r, dict) for r in rows)
    ):
        raise ValueError("Invalid or oversized results collection")
    models = report.get("models", {})
    roles = report.get("prompts", {})
    seeds = report.get("seeds", [])
    if not isinstance(models, dict) or len(models) > 20 or not isinstance(roles, dict):
        raise ValueError("Invalid profile metadata")
    if not models or not roles or not set(roles) <= set(ROLES):
        raise ValueError("Missing profile metadata")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 20:
        raise ValueError("Invalid seed metadata")
    if report.get("split") not in {"dev", "holdout"}:
        raise ValueError("Invalid evaluation split")
    for row in rows:
        if row.get("model") not in models or row.get("role") not in roles:
            raise ValueError("Result does not match the declared profiles")
        duration = row.get("seconds")
        if isinstance(duration, (int, float)) and (not math.isfinite(duration) or duration < 0):
            raise ValueError("Invalid duration")
    expected = (12 if report.get("split") == "holdout" else 4) * len(seeds)
    profiles: list[dict[str, Any]] = []
    for model in models:
        for role in ROLES:
            if role not in roles:
                continue
            selected = [r for r in rows if r.get("model") == model and r.get("role") == role]
            durations = [
                r["seconds"] for r in selected if isinstance(r.get("seconds"), (int, float))
            ]
            profiles.append(
                {
                    "model": short(model, 160),
                    "role": role,
                    "mode": "Direct"
                    if not report.get("thinking")
                    else (
                        "Reasoning requested"
                        if not selected or any("thinking_chars" not in r for r in selected)
                        else "Reasoning observed"
                        if any(r.get("thinking_chars", 0) > 0 for r in selected)
                        else "Direct output observed"
                    ),
                    "completed": len(selected),
                    "planned": expected,
                    "passed": sum(r.get("passed") is True for r in selected),
                    "unsafe": sum(bool(r.get("critical")) for r in selected),
                    "incomplete": sum(r.get("complete") is not True for r in selected),
                    "median_seconds": round(statistics.median(durations), 1) if durations else None,
                }
            )
    timeout = report.get("request_timeout_seconds", 120)
    if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        timeout = 120
    state = "awaiting_response"
    if report.get("stopped"):
        state = "stopped"
    elif report.get("finished_at"):
        state = "completed" if len(rows) == sum(p["planned"] for p in profiles) else "incomplete"
    elif now - modified > timeout + 45:
        state = "unconfirmed"
    active = report.get("active_request")
    activity = None
    if isinstance(active, dict) and not report.get("finished_at") and not report.get("stopped"):
        activity = {k: short(active.get(k), 160) for k in ("case", "model", "role", "started_at")}
    failed = [r for r in reversed(rows) if r.get("passed") is not True]
    failed.sort(key=lambda r: not bool(r.get("critical")))
    origin = report.get("resumed_from")
    continuation = None
    if isinstance(origin, dict):
        count = origin.get("recorded_responses")
        continuation = {
            "receipt": short(origin.get("receipt"), 240),
            "recorded_responses": count
            if isinstance(count, int) and 0 <= count <= MAX_ROWS
            else None,
        }
    return {
        "id": name,
        "state": state,
        "split": short(report.get("split"), 20),
        "started_at": short(report.get("started_at"), 50),
        "updated_at": datetime.fromtimestamp(modified, UTC).isoformat(),
        "thinking_requested": report.get("thinking") is True,
        "prompt_profile": short(report.get("prompt_profile", "role-contract-only"), 100),
        "request_timeout_seconds": timeout,
        "profiles": profiles,
        "activity": activity,
        "continued_from": continuation,
        "stopped_reason": short(report.get("stopped"), 500),
        "failures": [result_view(r, evidence) for r in failed[:6]],
        "failures_omitted": max(0, len(failed) - 6),
        "recent": [result_view(r, evidence) for r in rows[-3:][::-1]],
        "results_omitted": max(0, len(rows) - 3),
    }


def read_trials(directory: Path, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    result: dict[str, Any] = {
        "generated_at": datetime.fromtimestamp(now, UTC).isoformat(),
        "agents_enabled": False,
        "runs": [],
        "warnings": [],
        "scan_truncated": False,
        "older_runs_omitted": False,
        "earlier_contract_runs_omitted": 0,
    }
    if not directory.exists():
        return result
    corpus_hash = ""
    evidence: dict[str, Any] = {}
    try:
        with (directory.parent / "research/crypto-agent-eval-v3.json").open("rb") as stream:
            corpus_raw = stream.read(MAX_BYTES + 1)
        if len(corpus_raw) <= MAX_BYTES:
            corpus = json.loads(corpus_raw)
            for case in corpus["cases"][:1000]:
                items = case["evidence"]
                # Show only complete, bounded input packets; never quietly trim evidence.
                if len(items) <= 12 and all(
                    isinstance(e.get("text"), str) and len(e["text"]) <= 2400 for e in items
                ):
                    evidence[case["id"]] = [
                        {"id": short(e.get("id"), 100), "text": e["text"]} for e in items
                    ]
            corpus_hash = hashlib.sha256(corpus_raw).hexdigest()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        evidence = {}
    candidates: list[tuple[str, Path]] = []
    try:
        for index, path in enumerate(directory.iterdir()):
            if index >= MAX_SCAN:
                result["scan_truncated"] = True
                break
            matched = NAME.fullmatch(path.name)
            if matched:
                candidates.append((matched[2], path))
        # Bounded matching files and reads; historical files are never changed/deleted.
        for reads, (_, path) in enumerate(sorted(candidates, reverse=True)):
            if len(result["runs"]) >= MAX_RUNS or reads >= MAX_READS:
                result["older_runs_omitted"] = True
                break
            try:
                if path.resolve().parent != directory.resolve():
                    raise ValueError("Receipt must remain inside the evidence directory")
                with path.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Receipt exceeds the 2 MB viewer limit")
                report = json.loads(raw)
                if not isinstance(report, dict):
                    raise ValueError("Invalid receipt")
                if report.get("protocol_hash") != protocol_hash():
                    result["earlier_contract_runs_omitted"] += 1
                    continue
                inputs = evidence if report.get("corpus_hash") == corpus_hash else {}
                result["runs"].append(
                    run_view(report, path.name, path.stat().st_mtime, now, inputs)
                )
            except (OSError, ValueError, TypeError, KeyError):
                result["runs"].append({"id": path.name, "state": "unavailable"})
                result["warnings"].append(
                    "A trial record could not be read within the viewer limits."
                )
    except OSError:
        result["warnings"].append("The local trial history is temporarily unavailable.")
    return result


class ModelTrials:
    def __init__(self, directory: Path):
        self.directory = directory
        self._lock = Lock()
        self._expires = 0.0
        self._cached: dict[str, Any] = {}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if time.monotonic() >= self._expires:
                self._cached = read_trials(self.directory)
                self._expires = time.monotonic() + 5
            return self._cached
