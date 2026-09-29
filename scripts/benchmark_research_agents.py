"""Compare installed local models on a fixed crypto-research fixture set.

No downloads, provider keys, financial mutations, arbitrary tool calls or web access
are available to the models. Output is evidence, not a model-promotion decision.
"""

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ORIGIN = "http://127.0.0.1:11434"
ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/research/crypto-agent-eval-v1.json"
PROFILES = (
    {"model": "qwen3.5:2b", "think": False},
    {"model": "qwen3.5:4b", "think": True},
    {"model": "qwen3:8b", "think": True},
)


def sampling(profile: dict[str, Any]) -> dict[str, Any]:
    # Vendor-recommended sampling, not greedy decoding for reasoning models.
    qwen35 = profile["model"].startswith("qwen3.5")
    return {
        "temperature": (1.0 if qwen35 else 0.6) if profile["think"] else 0.7,
        "top_p": 0.95 if profile["think"] else 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5 if qwen35 else 0.0,
        "repeat_penalty": 1.0,
        "seed": 20260927,
    }


def http(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=100 if data else 5) as response:
        parsed: dict[str, Any] = json.load(response)
        return parsed


def health() -> dict[str, Any]:
    try:
        paper = http("http://127.0.0.1:8780/api/status")["paper"]
        return {key: paper.get(key) for key in ("running", "error", "stale", "performance")}
    except Exception as exc:
        return {"sampling_error": str(exc)}


def healthy(sample: dict[str, Any]) -> bool:
    return sample.get("running") is True and not sample.get("error") and not sample.get("stale")


def schema(case: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name, kind in case["fields"].items():
        properties[name] = (
            {"type": "array", "items": {"type": "string"}} if kind == "strings" else {"type": kind}
        )
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def grade(actual: Any, case: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(actual, dict):
        return {"passed": False, "errors": ["Response is not an object"]}
    if set(actual) != set(case["fields"]):
        errors.append("Response fields differ from schema")
    for key, kind in case["fields"].items():
        value = actual.get(key)
        good_type = {
            "string": isinstance(value, str),
            "integer": type(value) is int,
            "boolean": type(value) is bool,
            "strings": isinstance(value, list) and all(isinstance(v, str) for v in value),
        }[kind]
        if not good_type:
            errors.append(f"{key}: wrong type")
    for key, expected in case["checks"].items():
        value = actual.get(key)
        if isinstance(expected, list):
            match = isinstance(value, list) and sorted(value) == sorted(expected)
        else:
            match = type(value) is type(expected) and value == expected
        if not match:
            errors.append(f"{key}: expected {expected!r}, got {value!r}")
    for key in case.get("nonempty", []):
        if not isinstance(actual.get(key), str) or not actual[key].strip():
            errors.append(f"{key}: missing proposal text")
    return {"passed": not errors, "errors": errors}


def save(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=[p["model"] for p in PROFILES])
    parser.add_argument("--thinking", choices=("profile", "on", "off"), default="profile")
    parser.add_argument("--cases", nargs="+", help="Optional named case subset")
    parser.add_argument("--budget-seconds", type=int, default=480)
    args = parser.parse_args()
    corpus_text = CORPUS.read_text(encoding="utf-8")
    corpus = json.loads(corpus_text)
    cases = [c for c in corpus["cases"] if not args.cases or c["id"] in args.cases]
    if not cases or (args.cases and set(args.cases) != {c["id"] for c in cases}):
        raise ValueError("Unknown or empty case selection")
    profiles = [p for p in PROFILES if not args.profile or p["model"] == args.profile]
    if args.thinking != "profile":
        profiles = [dict(p, think=args.thinking == "on") for p in profiles]
    installed = {row["name"]: row for row in http(ORIGIN + "/api/tags")["models"]}
    if any(p["model"] not in installed for p in profiles):
        raise RuntimeError("Model not installed; this benchmark never downloads models")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / f"docs/evidence/crypto-agent-eval-{stamp}.json"
    report: dict[str, Any] = {
        "started_at": stamp,
        "corpus": corpus["version"],
        "corpus_sha256": hashlib.sha256(corpus_text.encode()).hexdigest(),
        "limitations": corpus["limitations"],
        "ollama_version": http(ORIGIN + "/api/version"),
        "profiles": profiles,
        "case_ids": [c["id"] for c in cases],
        "installed_models": {p["model"]: installed[p["model"]] for p in profiles},
        "runtime_before": health(),
        "results": [],
        "harness_version": "1.1-recommended-sampling",
        "generation_settings": {"num_ctx": 4096, "num_thread": 2},
        "sampling_by_profile": {p["model"]: sampling(p) for p in profiles},
        "sampling_sources": [
            "https://huggingface.co/Qwen/Qwen3.5-4B",
            "https://huggingface.co/Qwen/Qwen3-8B",
        ],
        "max_generation_tokens": {"nonthinking": 384, "thinking": 2048},
        "budget_seconds": args.budget_seconds,
    }
    if not healthy(report["runtime_before"]):
        raise RuntimeError("Paper worker is not healthy; optional benchmark not started")
    print(
        json.dumps({"output": str(output), "planned_requests": len(cases) * len(profiles)}),
        flush=True,
    )
    started = time.monotonic()
    for profile in profiles:
        incomplete_streak = 0
        for index, case in enumerate(cases):
            if time.monotonic() - started >= args.budget_seconds:
                report["stopped"] = "Wall-clock budget reached before next request"
                break
            row: dict[str, Any] = {**profile, "case": case["id"], "role": case["role"]}
            requested_at = time.monotonic()
            try:
                result = http(
                    ORIGIN + "/api/chat",
                    {
                        **profile,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a bounded crypto-research assistant. "
                                    "Use only supplied facts. Return the requested JSON fields. "
                                    "Include all and only supported issues; an empty array is "
                                    "valid. Do not invent evidence or findings. "
                                    "Money strings must contain only the supplied decimal number. "
                                    "Keep reasons and hypotheses concise. "
                                    "You have no tools or account permissions. Issue codes: "
                                    + ", ".join(corpus["issue_codes"])
                                ),
                            },
                            {"role": "user", "content": case["task"]},
                        ],
                        "format": schema(case),
                        "stream": False,
                        "keep_alive": 0 if index == len(cases) - 1 else "60s",
                        "options": {
                            **report["generation_settings"],
                            **sampling(profile),
                            "num_predict": 2048 if profile["think"] else 384,
                        },
                    },
                )
                row["response"] = result.get("message", {}).get("content", "")
                row["reasoning_emitted"] = bool(result.get("message", {}).get("thinking"))
                row["done_reason"] = result.get("done_reason")
                row["complete"] = result.get("done") is True and row["done_reason"] == "stop"
                for key in (
                    "total_duration",
                    "load_duration",
                    "prompt_eval_count",
                    "prompt_eval_duration",
                    "eval_count",
                    "eval_duration",
                ):
                    row[key] = result.get(key)
                if row["complete"]:
                    row["grading"] = grade(json.loads(row["response"]), case)
                else:
                    row["grading"] = {"passed": False, "errors": ["Incomplete within token budget"]}
            except Exception as exc:
                row["error"] = str(exc)
                row["complete"] = False
                row["grading"] = {"passed": False, "errors": ["Request or response failed"]}
            row["wall_seconds"] = round(time.monotonic() - requested_at, 3)
            row["runtime_after"] = health()
            report["results"].append(row)
            save(report, output)
            print(
                json.dumps(
                    {
                        "model": row["model"],
                        "think": row["think"],
                        "case": row["case"],
                        "complete": row["complete"],
                        "passed": row["grading"]["passed"],
                        "wall_seconds": row["wall_seconds"],
                        "error": row.get("error"),
                    }
                ),
                flush=True,
            )
            if row.get("error") or not healthy(row["runtime_after"]):
                report["stopped"] = (
                    "Request failure or paper-worker health issue; no more inference"
                )
                break
            incomplete_streak = 0 if row["complete"] else incomplete_streak + 1
            if incomplete_streak >= 2:
                report.setdefault("profile_skips", []).append(
                    {
                        "model": profile["model"],
                        "reason": "Two consecutive incomplete outputs within generation budget",
                    }
                )
                break
        if report.get("stopped"):
            break
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["runtime_after"] = health()
    report["wall_seconds"] = round(time.monotonic() - started, 3)
    save(report, output)
    print(
        json.dumps(
            {
                "output": str(output),
                "completed_requests": len(report["results"]),
                "stopped": report.get("stopped"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
