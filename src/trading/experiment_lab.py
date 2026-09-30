"""Bounded research supervisor; collection and financial management retain priority."""

import asyncio
import os
import subprocess
import sys
import sysconfig
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trading.compact_memory import compact_snapshot
from trading.experiment_registry import ExperimentPlan, ExperimentRegistry
from trading.experiment_worker import code_fingerprint
from trading.memory_dataset import corpus_snapshot
from trading.numerical_resources import child_rss, constrain_child
from trading.research_campaigns import ResearchCampaigns
from trading.research_data import quote_snapshot

WALL_SECONDS = 25


class ExperimentLab:
    def __init__(self, path: Path, dsn: str | None, can_research: Callable[[], bool]):
        self.registry = ExperimentRegistry(path)
        self.dsn = dsn
        self.can_research = can_research
        self.market_snapshot: Callable[[], dict[str, Any]] | None = None
        self.running = False
        self.blocked_reason: str | None = None
        self.child: subprocess.Popen[bytes] | None = None
        self.campaigns = ResearchCampaigns(self.registry, self.enqueue, code_fingerprint)
        from trading.prospective_review import ProspectiveReview

        self.prospective = ProspectiveReview(self.registry)

    def enqueue(self, plan: ExperimentPlan) -> dict[str, Any]:
        if plan.evidence_kind != "observed_public_quotes":
            raise ValueError("Synthetic evidence is only accepted by disposable QA fixtures")
        receipt = self.registry.reserve(plan, code_fingerprint())
        if receipt["retry"]:
            return receipt
        try:
            if plan.experiment_mode in {
                "memory_entry",
                "context_regime",
                "order_flow",
                "growing_memory",
                "component_exit",
                "component_size",
                "observation_priority",
            }:
                compact_path = self.registry.path.parent / "memory-episodes.sqlite"
                if compact_path.exists() and plan.experiment_mode not in {
                    "component_exit",
                    "component_size",
                    "observation_priority",
                    "order_flow",
                }:
                    snapshot = compact_snapshot(compact_path, plan.as_of)
                    from trading.execution_replay import source_hashes

                    snapshot["source_files"] = source_hashes()
                else:
                    snapshot = corpus_snapshot(
                        self.registry.path.parent / "research-evidence.sqlite", plan.as_of
                    )
            elif not self.dsn:
                raise ValueError("Public quote journal is not enabled")
            else:
                snapshot = quote_snapshot(self.dsn, plan.as_of)
            if plan.experiment_mode == "observation_priority" and self.market_snapshot:
                snapshot["point_in_time_universe"] = self.market_snapshot()
            self.registry.inputs(plan.request_id, snapshot)
        except Exception:
            self.registry.fail_inputs(
                plan.request_id, "Declared research inputs unavailable; no financial state changed"
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
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(Path(__file__).resolve().parents[1]),
                str(Path(sysconfig.get_paths()["purelib"]).resolve()),
            ]
        )
        env["PYTHONNOUSERSITE"] = "1"
        flags = (
            (subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS) if os.name == "nt" else 0
        )
        started = time.monotonic()
        peak_rss = 0
        try:
            self.child = subprocess.Popen(
                [
                    str(Path(getattr(sys, "_base_executable", sys.executable)).resolve()),
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
                elif time.monotonic() - started > WALL_SECONDS:
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
            supervised_pid = self.child.pid if self.child else None
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
                        "supervised_pid": supervised_pid,
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
