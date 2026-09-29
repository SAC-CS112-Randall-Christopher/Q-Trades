"""Bounded local-only model smoke comparison; never gives models tools or account access."""

import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ORIGIN = "http://127.0.0.1:11434"
OUTPUT = Path("docs/evidence/local-research-model-smoke-2026-09-27.json")
MODELS = ("qwen3.5:2b", "qwen3.5:4b", "qwen3:8b")
CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "extract_evidence",
        "task": (
            "Extract these facts, preserving money strings exactly. Evidence: equity USD "
            "99.7593799833; completed trades 2; source binance.us-rest-fallback; received "
            "WebSocket books 0; account target 1000; successful attempts 0. Return equity, "
            "closed_trades, successful_attempts, and streaming_confirmed (a boolean)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "equity": {"type": "string"},
                "closed_trades": {"type": "integer"},
                "successful_attempts": {"type": "integer"},
                "streaming_confirmed": {"type": "boolean"},
            },
            "required": ["equity", "closed_trades", "successful_attempts", "streaming_confirmed"],
            "additionalProperties": False,
        },
        "expected": {
            "equity": "99.7593799833",
            "closed_trades": 2,
            "successful_attempts": 0,
            "streaming_confirmed": False,
        },
    },
    {
        "id": "contaminated_research",
        "task": (
            "Review an experiment's evidence. At decision time t, feature future_move is "
            "close[t+5]/close[t]-1. A scaler was fit on all dates before dividing them "
            "into train and test. Researchers tried 800 versions and tuned each version "
            "using the same final test month. Twelve shadow accounts traded identical "
            "signals on identical timestamps; they count these as 12 independent replications. "
            "The winner has high profit after realistic costs. Decide reject, "
            "forward_paper_only, or promote_primary. List applicable issue codes from "
            "future_feature, preprocessing_leakage, test_reuse, correlated_samples. "
            "Give one concise reason."
        ),
        "expected": {
            "decision": "reject",
            "issues": [
                "future_feature",
                "preprocessing_leakage",
                "test_reuse",
                "correlated_samples",
            ],
        },
    },
    {
        "id": "eligible_forward_experiment",
        "task": (
            "Review an experiment's evidence. Every feature was available at its decision "
            "time. Preprocessing was fitted only on training dates. Chronological splits "
            "purged overlapping outcomes. Researchers logged all attempted versions, "
            "selected using training/validation data, then evaluated their one frozen "
            "candidate once on a previously untouched later period. A separately computed "
            "report includes realistic costs, uncertainty and all losses; it supports a "
            "small forward paper comparison. There has been no prospective paper run yet. "
            "Decide reject, forward_paper_only, or promote_primary. List applicable issue "
            "codes from future_feature, preprocessing_leakage, test_reuse, correlated_samples. "
            "Give one concise reason."
        ),
        "expected": {"decision": "forward_paper_only", "issues": []},
    },
)
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["reject", "forward_paper_only", "promote_primary"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["decision", "issues", "reason"],
    "additionalProperties": False,
}


def request(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=70 if payload is not None else 5) as response:
        return json.load(response)  # type: ignore[no-any-return]


def runtime_sample() -> dict[str, Any]:
    try:
        paper = request("http://127.0.0.1:8780/api/status")["paper"]
        return {key: paper.get(key) for key in ("running", "error", "stale", "performance")}
    except Exception as error:
        return {"sampling_error": str(error)}


def matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if isinstance(value, list):
            if sorted(actual.get(key, [])) != sorted(value):
                return False
        elif actual.get(key) != value:
            return False
    return True


def main() -> None:
    installed = {row["name"]: row for row in request(ORIGIN + "/api/tags")["models"]}
    if any(model not in installed for model in MODELS):
        raise RuntimeError("A requested model is missing; this probe never downloads models")
    initial = runtime_sample()
    if initial.get("running") is not True or initial.get("error") or initial.get("stale"):
        raise RuntimeError("Paper worker must be healthy before optional local inference")
    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Three short synthetic tasks; not a trading, tool-use or reasoning certification"
        ),
        "settings": {"thinking": False, "context": 4096, "output_tokens": 240, "threads": 2},
        "cases": CASES,
        "models": {model: installed[model] for model in MODELS},
        "runtime_before": initial,
        "results": [],
    }
    started = time.monotonic()
    for model in MODELS:
        for index, case in enumerate(CASES):
            if time.monotonic() - started > 240:
                report["stopped"] = "Four-minute optional-work budget reached"
                break
            row: dict[str, Any] = {"model": model, "case": case["id"]}
            request_started = time.monotonic()
            try:
                result = request(
                    ORIGIN + "/api/chat",
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Use supplied evidence only. Return the requested JSON. "
                                    "You have no tools or trading authority."
                                ),
                            },
                            {"role": "user", "content": case["task"]},
                        ],
                        "format": case.get("schema", REVIEW_SCHEMA),
                        "stream": False,
                        "think": False,
                        "keep_alive": 0 if index == len(CASES) - 1 else "60s",
                        "options": {
                            "temperature": 0,
                            "num_ctx": 4096,
                            "num_predict": 240,
                            "num_thread": 2,
                        },
                    },
                )
                row["response"] = result.get("message", {}).get("content", "")
                row["done_reason"] = result.get("done_reason")
                row["eval_count"] = result.get("eval_count")
                row["generation_seconds"] = result.get("eval_duration", 0) / 1e9
                row["load_seconds"] = result.get("load_duration", 0) / 1e9
                actual = json.loads(row["response"])
                row["passed_expected_fields"] = matches(actual, case["expected"])
            except Exception as error:
                row["error"] = str(error)
                row["passed_expected_fields"] = False
            row["wall_seconds"] = round(time.monotonic() - request_started, 2)
            row["runtime_after"] = runtime_sample()
            report["results"].append(row)
            OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(
                json.dumps(
                    {
                        key: row.get(key)
                        for key in [
                            "model",
                            "case",
                            "passed_expected_fields",
                            "wall_seconds",
                            "error",
                        ]
                    }
                ),
                flush=True,
            )
            health = row["runtime_after"]
            if health.get("running") is not True or health.get("error") or health.get("stale"):
                report["stopped"] = "Paper-worker health check failed; ending optional probe"
                break
        if report.get("stopped"):
            break
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["runtime_after"] = runtime_sample()
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
