"""Bounded optional-query controls around the actual financial monitoring owners.

All databases and runtimes supplied here must be disposable QA resources. Failures,
query holds and the optional 61-second audit scheduling advance are synthetic;
the audit, successful queries, IPC, runtime publication and shutdown are real.
"""

import asyncio
import functools
import multiprocessing
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import psycopg

import trading.financial_readback_worker as worker_module
import trading.tiered_runtime as runtime_module
from trading.financial_readback import FinancialReadback
from trading.financial_readback_worker import ReadbackWorker, readback_child
from trading.paper_store import PaperStore
from trading.tiered_runtime import TieredPaperRuntime

QUERY_NAMES = ("recent", "storage_usage")
HOLD_SECONDS = 20.0  # The unchanged 15s operation deadline still owns continuation.


@dataclass
class OptionalQueryControl:
    failed: Any
    hold_requested: Any
    entered: Any
    released: Any
    calls: Any


def controlled_optional_child(pipe, dsn, *, controls):
    """Spawn-safe seam; retain the production producer, child and connection owner."""
    reader = FinancialReadback.from_dsn(dsn)
    reader._view = PaperStore(dsn)
    for name in QUERY_NAMES:
        original = getattr(reader._view, name)
        control = controls[name]

        def controlled_query(original=original, control=control):
            # Only the current owned child's query writes this diagnostic count.
            control.calls.value += 1
            if control.hold_requested.value:
                control.entered.value = 1
                deadline = time.monotonic() + HOLD_SECONDS
                while not control.released.value:
                    if time.monotonic() >= deadline:
                        raise psycopg.OperationalError("Synthetic optional-refresh hold expired")
                    time.sleep(0.01)
            if control.failed.value:
                raise psycopg.OperationalError("Synthetic optional-refresh query failure")
            return original()

        setattr(reader._view, name, controlled_query)
    FinancialReadback.from_dsn = classmethod(lambda cls, _: reader)
    readback_child(pipe, dsn)


class FinancialMonitoringFixture:
    """One isolated QA loop with bounded spawned-query controls and owned teardown."""

    def __init__(self, runtime: TieredPaperRuntime):
        self.runtime = runtime
        context = multiprocessing.get_context("spawn")
        # Parent-written controls and child-written diagnostics have one writer.
        # Lock-free bytes avoid Event.notify waiting for a killed child's wakeup.
        self.controls = {
            name: OptionalQueryControl(
                context.RawValue("b", 0), context.RawValue("b", 0),
                context.RawValue("b", 0), context.RawValue("b", 0),
                context.RawValue("i", 0),
            )
            for name in QUERY_NAMES
        }
        self.reader = ReadbackWorker(FinancialReadback(runtime.store))
        self.task: asyncio.Task[None] | None = None
        self._original_child = worker_module.readback_child
        self._original_worker = runtime_module.ReadbackWorker
        self._child_target = functools.partial(
            controlled_optional_child, controls=self.controls
        )
        self._worker_factory = lambda _: self.reader

    @property
    def completed_at(self) -> float | None:
        sample = self.runtime._readback_sample
        return sample["completed_at"] if sample else None

    @property
    def audit_at(self) -> float | None:
        return self.runtime.receipts.get("checked_at")

    async def start(self) -> None:
        if self.task is not None:
            raise RuntimeError("The QA monitoring loop already started")
        worker_module.readback_child = self._child_target
        runtime_module.ReadbackWorker = self._worker_factory
        self.task = asyncio.create_task(self.runtime._financial_readback_loop())

    def fail(self, *names: str) -> None:
        for name in names:
            self.controls[name].failed.value = 1

    def recover(self, *names: str) -> None:
        for name in names:
            self.controls[name].failed.value = 0

    def hold(self, name: str) -> None:
        control = self.controls[name]
        control.entered.value = 0
        control.released.value = 0
        control.hold_requested.value = 1

    def release(self, name: str) -> None:
        control = self.controls[name]
        control.hold_requested.value = 0
        control.released.value = 1

    def make_audit_due(self) -> None:
        # Synthetic scheduling only: retain the actual audit receipt/result and
        # remain inside the unchanged 120-second validity window.
        if self.runtime._readback_audit_mono is None:
            raise RuntimeError("A real completed audit is required before scheduling another")
        self.runtime._readback_audit_mono = time.monotonic() - 61

    async def _wait(self, predicate, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            while not predicate():
                if self.task is None or self.task.done():
                    if self.task is not None:
                        self.task.result()
                    raise RuntimeError("The QA monitoring loop stopped before its checkpoint")
                await asyncio.sleep(0.01)

    async def wait_sample(
        self, previous_completed_at: float | None = None, *, timeout: float = 8
    ) -> dict[str, Any]:
        await self._wait(
            lambda: self.completed_at is not None and self.completed_at != previous_completed_at,
            timeout,
        )
        return dict(self.runtime._readback_sample)

    async def wait_held(self, name: str, *, timeout: float = 8) -> None:
        await self._wait(lambda: bool(self.controls[name].entered.value), timeout)

    async def wait_audit(self, previous_checked_at: float, *, timeout: float = 8) -> None:
        await self._wait(
            lambda: self.audit_at is not None and self.audit_at > previous_checked_at,
            timeout,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "evidence_kind": "synthetic_optional_query_controls_actual_owners",
            "audit_at": self.audit_at,
            "completed_at": self.completed_at,
            "revision": self.runtime.receipts.get("revision"),
            "reader_alive": self.reader._process is not None and self.reader._process.is_alive(),
            "operation_error": self.runtime._readback_error,
            "shutdown": self.runtime._readback_shutdown,
            "queries": {
                name: {"calls": control.calls.value, "failed": bool(control.failed.value),
                       "held": bool(control.hold_requested.value and control.entered.value)}
                for name, control in self.controls.items()
            },
        }

    async def stop(self) -> None:
        try:
            for name in QUERY_NAMES:
                self.release(name)
            if self.task is not None:
                self.task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.task
            await self.reader.close()
        finally:
            if worker_module.readback_child is self._child_target:
                worker_module.readback_child = self._original_child
            if runtime_module.ReadbackWorker is self._worker_factory:
                runtime_module.ReadbackWorker = self._original_worker
