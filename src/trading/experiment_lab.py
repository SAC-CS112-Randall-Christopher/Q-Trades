"""Bounded research supervisor; collection and financial management retain priority."""

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trading.experiment_registry import ExperimentPlan, ExperimentRegistry
from trading.experiment_worker import code_fingerprint
from trading.numerical_resources import child_rss, constrain_child
from trading.research_campaigns import ResearchCampaigns
from trading.research_data import quote_snapshot


class ExperimentLab:
    def __init__(self, path: Path, dsn: str | None, can_research: Callable[[], bool]):
        self.registry = ExperimentRegistry(path)
        self.dsn = dsn
        self.can_research = can_research
        self.running = False
        self.blocked_reason: str | None = None
        self.child: subprocess.Popen[bytes] | None = None
        self.campaigns = ResearchCampaigns(self.registry, self.enqueue, code_fingerprint)

    def enqueue(self, plan: ExperimentPlan) -> dict[str, Any]:
        if plan.evidence_kind != "observed_public_quotes":
            raise ValueError("Synthetic evidence is only accepted by disposable QA fixtures")
        receipt = self.registry.reserve(plan, code_fingerprint())
        if receipt["retry"]:
            return receipt
        try:
            if not self.dsn:
                raise ValueError("Public quote journal is not enabled")
            snapshot = quote_snapshot(self.dsn, plan.as_of)
            self.registry.inputs(plan.request_id, snapshot)
        except Exception:
            self.registry.fail_inputs(
                plan.request_id, "Quote snapshot unavailable; no financial state changed"
            )
        job = self.registry.get(plan.request_id)
        return {**receipt, "status": job["status"] if job else "failed"}

    async def run_once(self) -> bool:
        if not self.can_research():
            self.blocked_reason = "Research yielding to paper health or protected resource pressure"
            return False
        self.blocked_reason = None
        job = self.registry.claim()
        if job is None:
            return False
        request_id, lease = job["request_id"], job["lease"]
        # No credentials, provider configuration, user code, shell, venue or financial DSN.
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PYTHONPATH"}
        }
        # Works in both an installed application and a clean source checkout.
        # Do not inherit an arbitrary caller-controlled module search path.
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        env["PYTHONNOUSERSITE"] = "1"
        flags = (
            (subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS) if os.name == "nt" else 0
        )
        started = time.monotonic()
        peak_rss = 0
        try:
            self.child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "trading.experiment_worker",
                    "--registry",
                    str(self.registry.path),
                    "--request",
                    request_id,
                    "--lease",
                    lease,
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            constrain_child(self.child.pid)
            while self.child.poll() is None:
                peak_rss = max(peak_rss, child_rss(self.child.pid))
                current_status = self.registry.status(request_id)
                reason = None
                if current_status is None or current_status == "cancelled":
                    reason = "Operator cancelled"
                elif time.monotonic() - started > 25:
                    reason = "Numerical worker exceeded its 25-second wall-clock limit"
                elif peak_rss > 256 * 1024**2:
                    reason = "Numerical worker exceeded its 256 MiB memory limit"
                elif not self.can_research():
                    reason = "Protected resource pressure interrupted this attempt"
                if reason:
                    self.child.terminate()
                    await asyncio.to_thread(self.child.wait, 3)
                    self.registry.finish(request_id, lease, None, reason)
                    break
                await asyncio.sleep(0.2)
            if self.registry.status(request_id) == "running":
                self.registry.finish(
                    request_id, lease, None, "Worker exited without a retained result"
                )
        except asyncio.CancelledError:
            if self.child and self.child.poll() is None:
                self.child.terminate()
                await asyncio.to_thread(self.child.wait, 3)
            # The expired lease preserves the interrupted attempt and permits one retry.
            raise
        except (OSError, subprocess.SubprocessError):
            if self.child and self.child.poll() is None:
                self.child.terminate()
                await asyncio.to_thread(self.child.wait, 3)
            self.registry.finish(request_id, lease, None, "Numerical child could not complete")
        finally:
            self.child = None
            with self.registry.transaction():
                self.registry.event(
                    request_id,
                    "worker_resources",
                    {
                        "wall_seconds": time.monotonic() - started,
                        "peak_rss_bytes": peak_rss,
                        "logical_processors_max": 2,
                        "gpu": False,
                        "paid_usd": "0",
                    },
                )
        return True

    async def run(self) -> None:
        self.running = True
        try:
            while True:
                if self.can_research():
                    await asyncio.to_thread(self.campaigns.step, time.time())
                await self.run_once()
                await asyncio.sleep(2)
        finally:
            self.running = False

    def snapshot(self, before: int = 0) -> dict[str, Any]:
        return {
            **self.registry.snapshot(before),
            "worker_running": self.running,
            "blocked_reason": self.blocked_reason,
            "active_child": self.child is not None,
            "worker_wall_seconds": 25,
            "parallel_jobs": 1,
            "llm_required": False,
            "research_campaigns": self.campaigns.snapshot(),
            "limits": {
                "accounts": 20,
                "fits_at_once": 1,
                "queue": 8,
                "logical_processors": 2,
                "child_rss_mib": 256,
                "gpu": 0,
                "wall_seconds_per_attempt": 25,
                "paid_usd": "0",
                "inference_calls": 0,
                "registry_mib": 512,
                "snapshot_mib": 8,
            },
        }
