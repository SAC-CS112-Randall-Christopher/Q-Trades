"""Bounded infrastructure measurement, not model role qualification."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scripts.evaluate_research_roles import health, runtime_blocker, save
from trading.ownership import CollectorLock
from trading.research_resources import (
    ELASTIC_CPU_RUNTIME,
    capture_resources,
    elastic_resources_valid,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / f"docs/evidence/elastic-runtime-probe-{stamp}.json"
    if output.exists():
        raise FileExistsError("Refusing to replace an infrastructure receipt")
    origin = "http://127.0.0.1:11435"
    model = "qwen3:14b"
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "purpose": "CPU capacity and priority observation; not role or trading evidence",
        "model": model,
        "origin": origin,
        "profile": ELASTIC_CPU_RUNTIME,
        "options": {
            "num_ctx": 8192,
            "num_thread": 6,
            "num_gpu": 0,
            "num_predict": 128,
            "temperature": 0,
            "seed": 9281,
        },
        "request_timeout_seconds": 300,
        "maximum_health_wait_seconds": 600,
        "state": "waiting",
        "prompt": "List the integers from 1 through 100, separated by spaces.",
    }
    lock = CollectorLock(ROOT / "data/research-inference.lock")
    lock.acquire()
    requested = False
    try:
        with httpx.Client(trust_env=False, timeout=300) as client:
            try:
                deadline = time.monotonic() + 600
                while True:
                    sample = health(client)
                    reason = runtime_blocker(client, sample, None, origin)
                    report.update(paper_before=sample, waiting_reason=reason)
                    save(report, output)
                    if reason is None:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Paper/runtime admission gate did not clear in 600 seconds"
                        )
                    time.sleep(15)
                state = json.loads((ROOT / "data/research-runtime.json").read_text())
                if state["profile"] != ELASTIC_CPU_RUNTIME or state["priority"] != "Idle":
                    raise ValueError("Elastic runtime profile is not active")
                report["runtime_before"] = state
                tags = client.get(origin + "/api/tags", timeout=8).json()["models"]
                report["model_digest"] = next(m["digest"] for m in tags if m["name"] == model)
                report["state"] = "evaluating"
                save(report, output)
                started = time.monotonic()
                requested = True
                response = client.post(
                    origin + "/api/generate",
                    json={
                        "model": model,
                        "prompt": report["prompt"],
                        "stream": False,
                        "think": False,
                        "keep_alive": "60s",
                        "options": report["options"],
                    },
                )
                response.raise_for_status()
                result = response.json()
                report["seconds"] = round(time.monotonic() - started, 3)
                report["result"] = {
                    k: result.get(k)
                    for k in (
                        "response",
                        "done",
                        "done_reason",
                        "eval_count",
                        "eval_duration",
                        "prompt_eval_count",
                        "prompt_eval_duration",
                        "load_duration",
                    )
                }
                report["tokens_per_second"] = result["eval_count"] / (result["eval_duration"] / 1e9)
                report["resources"] = capture_resources(ROOT / "data/research-runtime.json")
                if not elastic_resources_valid(report["resources"]):
                    raise ValueError("Actual CPU priority or affinity differs from the profile")
                report["resident_after"] = client.get(origin + "/api/ps", timeout=8).json()
                resident = report["resident_after"]["models"]
                if (
                    len(resident) != 1
                    or resident[0]["name"] != model
                    or resident[0]["digest"] != report["model_digest"]
                    or resident[0]["size_vram"] != 0
                ):
                    raise ValueError("CPU model placement could not be verified")
                report["state"] = "completed"
            except Exception as exc:
                report.update(state="failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                if requested:
                    try:
                        client.post(
                            origin + "/api/generate",
                            json={
                                "model": model,
                                "keep_alive": 0,
                            },
                            timeout=30,
                        ).raise_for_status()
                        report["unloaded"] = not client.get(origin + "/api/ps", timeout=8).json()[
                            "models"
                        ]
                    except (httpx.HTTPError, ValueError, KeyError) as exc:
                        report["unload_error"] = type(exc).__name__
                report["paper_after"] = health(client)
                report["finished_at"] = datetime.now(UTC).isoformat()
                save(report, output)
    finally:
        lock.release()
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in (
                    "state",
                    "seconds",
                    "tokens_per_second",
                    "error",
                    "unloaded",
                )
            }
        )
    )
    print(output)


if __name__ == "__main__":
    main()
