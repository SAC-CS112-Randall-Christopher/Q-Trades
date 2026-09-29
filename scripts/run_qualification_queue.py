"""One frozen, sequential local qualification batch; never enables an agent or trades."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from trading.ownership import CollectorLock
from trading.research_inference import CPU_RUNTIME, cpu_placement_valid
from trading.research_resources import ELASTIC_CPU_RUNTIME

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_research_roles import health, runtime_blocker, save  # noqa: E402
from scripts.qualify_research_role import qualification  # noqa: E402


def now() -> str:
    return datetime.now(UTC).isoformat()


def declared_screen_roles(freeze: dict[str, Any]) -> list[str] | None:
    """Allow a frozen subset without repeating a role's retained failed screen."""
    allowed = ["researcher", "trainer", "reviewer"]
    roles = freeze.get("screen_roles")
    if roles is None:
        return allowed if freeze.get("screen_all_roles") else None
    if (
        freeze.get("screen_all_roles")
        or not isinstance(roles, list)
        or not roles
        or any(not isinstance(role, str) or role not in allowed for role in roles)
        or len(set(roles)) != len(roles)
    ):
        raise ValueError("Declare unique known development roles without screen_all_roles")
    return roles


def verify_freeze(freeze: dict[str, Any], client: httpx.Client) -> None:
    for name, digest in freeze["files"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Frozen source changed; review before continuing: " + name)
    origin = freeze.get("ollama_origin", "http://127.0.0.1:11434")
    if origin not in {"http://127.0.0.1:11434", "http://127.0.0.1:11435"}:
        raise ValueError("Qualification may only use the declared loopback runtimes")
    if (
        freeze.get("ollama_version")
        and client.get(origin + "/api/version", timeout=8).json().get("version")
        != freeze["ollama_version"]
    ):
        raise ValueError("Model runtime version differs from the frozen environment")
    tags = client.get(origin + "/api/tags", timeout=8).json()["models"]
    installed = {item["name"]: item["digest"] for item in tags}
    if installed.get(freeze["model"]) != freeze["model_digest"]:
        raise ValueError("Installed model differs from the predeclared digest")


def screen_passed(report: dict[str, Any], model: str, role: str) -> bool:
    rows = [r for r in report["results"] if r["model"] == model and r["role"] == role]
    return bool(
        report.get("finished_at")
        and not report.get("stopped")
        and len(rows) == 4
        and len({r["case"] for r in rows}) == 4
        and all(
            r.get("complete")
            and r.get("passed")
            and not r.get("critical")
            and r["runtime_after"].get("running") is True
            and not r["runtime_after"].get("error")
            and r["runtime_after"].get("stale") is False
            and (
                report.get("runtime_profile") not in (CPU_RUNTIME, ELASTIC_CPU_RUNTIME)
                or cpu_placement_valid(
                    r, model, report["models"][model]["digest"], report["runtime_profile"]
                )
            )
            for r in rows
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("freeze", type=Path)
    args = parser.parse_args()
    source = args.freeze.resolve()
    if source.parent != ROOT / "docs/evidence" or source.stat().st_size > 65536:
        raise ValueError("Need a bounded freeze receipt in docs/evidence")
    freeze = json.loads(source.read_text(encoding="utf-8"))
    screening_roles = declared_screen_roles(freeze)
    batch = source.stem
    state_path = ROOT / "data" / (batch + ".state.json")
    if state_path.exists():
        raise FileExistsError("This batch already has a record; do not rerun or overwrite it")
    state: dict[str, Any] = {
        "started_at": now(),
        "state": "preparing",
        "pid": os.getpid(),
        "freeze": source.relative_to(ROOT).as_posix(),
        "freeze_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "model": freeze["model"],
        "ollama_origin": freeze.get("ollama_origin", "http://127.0.0.1:11434"),
        "runtime_profile": freeze.get("runtime_profile", "automatic-placement-v1"),
        "stages": [],
        "agents_enabled": False,
        "authority": "Installed local evaluation only; no account, risk or promotion writes",
    }

    def record(**fields: Any) -> None:
        state.update(fields, updated_at=now())
        save(state, state_path)

    # A separate lock permits the one child evaluator to hold its own inference lock.
    queue_lock = CollectorLock(ROOT / "data/research-qualification-queue.lock")
    queue_lock.acquire()
    try:
        with httpx.Client(trust_env=False, timeout=8) as client:
            idle_wait_used = 0.0

            def wait_for_idle() -> None:
                nonlocal idle_wait_used
                quiet_since = None
                while True:
                    began = time.monotonic()
                    verify_freeze(freeze, client)
                    sample = health(client)
                    reason = runtime_blocker(
                        client,
                        sample,
                        None,
                        freeze.get("ollama_origin", "http://127.0.0.1:11434"),
                        freeze.get("runtime_profile"),
                    )
                    at = time.monotonic()
                    if reason:
                        quiet_since = None
                    elif quiet_since is None:
                        quiet_since = at
                    if quiet_since is not None and at - quiet_since >= 30:
                        return
                    record(
                        state="waiting_for_runtime",
                        reason=reason or "Confirming idle runtime",
                        runtime=sample,
                        idle_wait_seconds=round(idle_wait_used, 1),
                    )
                    if idle_wait_used >= freeze["maximum_idle_wait_seconds"]:
                        raise RuntimeError(
                            "Idle wait budget reached; preserve this batch for review"
                        )
                    time.sleep(15)
                    idle_wait_used += time.monotonic() - began

            def run_stage(split: str, roles: list[str]) -> tuple[Path, dict[str, Any]]:
                wait_for_idle()
                label = split + "-" + "-".join(roles)
                log_path = ROOT / "data" / (batch + "." + label + ".log")
                seeds = freeze["holdout_seeds"] if split == "holdout" else freeze["dev_seeds"]
                command = [
                    sys.executable,
                    str(ROOT / "scripts/evaluate_research_roles.py"),
                    "--models",
                    freeze["model"],
                    "--roles",
                    *roles,
                    "--thinking",
                    "--split",
                    split,
                    "--seeds",
                    *map(str, seeds),
                    "--request-timeout-seconds",
                    str(freeze["request_timeout_seconds"]),
                    "--budget-seconds",
                    str(
                        len(roles)
                        * (12 if split == "holdout" else 4)
                        * len(seeds)
                        * freeze["request_timeout_seconds"]
                        + 120
                    ),
                    "--ollama-origin",
                    freeze.get("ollama_origin", "http://127.0.0.1:11434"),
                ]
                if freeze.get("cpu_only"):
                    command.append("--cpu-only")
                    command.extend(["--cpu-profile", freeze["runtime_profile"]])
                command.extend(
                    ["--resource-wait-seconds", str(freeze.get("resource_wait_seconds", 0))]
                )
                if split == "dev" and freeze.get("dev_resource_resume"):
                    prior = (ROOT / freeze["dev_resource_resume"]).resolve()
                    if (
                        prior.parent != ROOT / "docs/evidence"
                        or freeze["dev_resource_resume"] not in freeze["files"]
                    ):
                        raise ValueError(
                            "Continuation receipt must be included in the frozen manifest"
                        )
                    command.extend(["--resume-from", str(prior), "--resume-resource-yield"])
                if split == "holdout":
                    command.append("--stop-disqualified-role")
                stage: dict[str, Any] = {
                    "stage": label,
                    "started_at": now(),
                    "log": log_path.relative_to(ROOT).as_posix(),
                }
                state["stages"].append(stage)
                with log_path.open("x", encoding="utf-8") as log:
                    child = subprocess.Popen(
                        command,
                        cwd=ROOT,
                        stdout=log,
                        stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    stage["pid"] = child.pid
                    record(state="evaluating", active_stage=label, reason=None)
                    while child.poll() is None:
                        time.sleep(15)
                        # Only the bounded first log line locates the child's atomic receipt.
                        waiting = None
                        try:
                            with log_path.open(encoding="utf-8") as progress_log:
                                first = progress_log.readline(4096)
                            progress_path = Path(json.loads(first)["output"]).resolve()
                            if (
                                progress_path.parent == ROOT / "docs/evidence"
                                and progress_path.stat().st_size <= 2_000_000
                            ):
                                progress = json.loads(progress_path.read_text(encoding="utf-8"))
                                waiting = progress.get("waiting_for_resources")
                        except (OSError, ValueError, KeyError):
                            pass
                        record(
                            state="waiting_for_resources" if waiting else "evaluating",
                            active_stage=label,
                            resource_wait=waiting,
                            reason=waiting.get("reason") if waiting else None,
                        )
                stage.update(returncode=child.returncode, finished_at=now())
                outputs = []
                for line in log_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("{"):
                        outputs.append(json.loads(line))
                produced = next(
                    (Path(v["output"]).resolve() for v in outputs if "output" in v), None
                )
                if produced is not None:
                    stage["receipt"] = produced.relative_to(ROOT).as_posix()
                record()
                if child.returncode or produced is None:
                    raise RuntimeError(
                        "Evaluator interrupted; retain its receipt and request state"
                    )
                if produced.parent != ROOT / "docs/evidence" or produced.stat().st_size > 2_000_000:
                    raise ValueError("Unexpected evaluation receipt")
                report = json.loads(produced.read_text(encoding="utf-8"))
                if report.get("stopped"):
                    raise RuntimeError("Evaluation stopped: " + report["stopped"])
                return produced, report

            def accept(role: str) -> None:
                produced, report = run_stage("holdout", [role])
                verify_freeze(freeze, client)
                try:
                    certificate = qualification(produced, freeze["model"], role)
                except ValueError as exc:
                    certificate = {
                        "qualified": False,
                        "model": freeze["model"],
                        "role": role,
                        "status": "incomplete_or_disqualified",
                        "reason": str(exc),
                        "receipt": produced.relative_to(ROOT).as_posix(),
                        "receipt_sha256": hashlib.sha256(produced.read_bytes()).hexdigest(),
                        "summary": report.get("summary"),
                    }
                certificate["automatic_activation"] = False
                certificate["next_gate"] = "Rationale review, latency assessment and real workflow"
                destination = ROOT / "docs/evidence" / (batch + "." + role + ".qualification.json")
                with destination.open("x", encoding="utf-8") as output:
                    output.write(json.dumps(certificate, indent=2) + "\n")
                state["stages"][-1].update(
                    qualified=certificate["qualified"],
                    qualification=destination.relative_to(ROOT).as_posix(),
                )
                record()

            verify_freeze(freeze, client)
            if screening_roles is not None:
                _, screened = run_stage("dev", screening_roles)
                candidates = tuple(screening_roles)
            else:
                baseline = json.loads(
                    (ROOT / freeze["researcher_dev_receipt"]).read_text(encoding="utf-8")
                )
                if not screen_passed(baseline, freeze["model"], "researcher"):
                    raise ValueError(
                        "Researcher development prerequisite is not complete and passing"
                    )
                accept("researcher")
                _, screened = run_stage("dev", ["trainer", "reviewer"])
                candidates = ("trainer", "reviewer")
            for role in candidates:
                if screen_passed(screened, freeze["model"], role):
                    accept(role)
                else:
                    state["stages"].append(
                        {
                            "stage": "holdout-" + role,
                            "state": "not_eligible",
                            "reason": "Development screen incomplete or below gate",
                        }
                    )
                    record()
            record(state="completed", active_stage=None, finished_at=now())
    except Exception as exc:
        record(state="needs_review", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        queue_lock.release()


if __name__ == "__main__":
    main()
