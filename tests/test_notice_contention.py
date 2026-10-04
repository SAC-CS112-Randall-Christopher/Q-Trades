"""Disposable registry contention through the ordinary optional supervisor."""

import asyncio
import json
import sqlite3
import threading
import time

import pytest
from test_research_notices import condition

from trading.experiment_lab import ExperimentLab


def test_notice_registry_contention_does_not_hold_the_supervisor_indefinitely(tmp_path):
    lab = ExperimentLab(tmp_path / "registry.sqlite", None, lambda: False)
    held = threading.Event()
    release = threading.Event()
    checks = []
    progress = []
    original = lab.run_once

    def hold():
        with lab.registry.lock:
            held.set()
            release.wait(5)

    def source():
        checks.append(time.monotonic())
        return [condition(time.time(), severity="critical")]

    async def tick():
        progress.append(time.monotonic())
        return await original()

    lab.notice_source = source
    lab.run_once = tick
    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(2)

    async def scenario():
        worker = asyncio.create_task(lab.run())
        try:

            async def observed():
                while not progress:
                    await asyncio.sleep(0.02)

            await asyncio.wait_for(observed(), 2.5)
            assert checks and lab.running and lab.notice_error and lab.child is None
        finally:
            release.set()
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        holder.join(5)
        lab.registry.close()


def test_normally_paced_supervisor_persists_across_contention_storage_fault_and_recovery(tmp_path):
    """Six real ten-second checks; no accelerated clock, model or financial worker."""
    lab = ExperimentLab(tmp_path / "paced.sqlite", None, lambda: False)
    writable = lab.registry.db
    readonly = None
    holder = None
    release = threading.Event()
    progress = []
    attempts = []
    original_observe = lab.notices.observe
    original_run_once = lab.run_once

    def source():
        nonlocal readonly, holder
        index = len(attempts)
        if index == 2:
            release.clear()
            held = threading.Event()

            def contend():
                with lab.registry.lock:
                    held.set()
                    release.wait(3)

            holder = threading.Thread(target=contend)
            holder.start()
            assert held.wait(2)
        elif index == 3:
            readonly = sqlite3.connect(
                lab.registry.path.as_uri() + "?mode=ro",
                uri=True,
                check_same_thread=False,
                isolation_level=None,
            )
            readonly.row_factory = sqlite3.Row
            lab.registry.db = readonly
        elif index == 4:
            lab.registry.db = writable
            assert readonly
            readonly.close()
            readonly = None
        return [
            condition(
                time.time(),
                "clear" if index >= 4 else "active",
                severity="critical" if index == 3 else "warning",
            )
        ]

    def measured(conditions, now):
        start = time.monotonic()
        entry = {"started_mono": start, "error": None}
        try:
            return original_observe(conditions, now)
        except (OSError, sqlite3.Error) as error:
            entry["error"] = type(error).__name__
            raise
        finally:
            entry["seconds"] = time.monotonic() - start
            attempts.append(entry)
            release.set()

    async def tick():
        progress.append({"at": time.monotonic(), "persistence_unconfirmed": bool(lab.notice_error)})
        return await original_run_once()

    lab.notice_source = source
    lab.notices.observe = measured
    lab.run_once = tick

    async def scenario():
        worker = asyncio.create_task(lab.run())
        try:

            async def completed():
                while len(attempts) < 6:
                    await asyncio.sleep(0.05)

            await asyncio.wait_for(completed(), 70)
            assert worker.done() is False and lab.running and lab.child is None
            row = lab.notices.snapshot(time.time())["operational"][0]
            assert row["state"] == "recovered" and row["recoveries"] == 1
            assert [a["error"] for a in attempts] == [
                None,
                None,
                "OSError",
                "OperationalError",
                None,
                None,
            ]
            assert 50 <= attempts[-1]["started_mono"] - attempts[0]["started_mono"] <= 70
            assert attempts[2]["seconds"] < 2.5 and len(progress) >= 15
            assert any(p["persistence_unconfirmed"] for p in progress)
            assert lab.notice_error is None
            assert lab.registry.db.execute("SELECT count(*) FROM experiments").fetchone()[0] == 0
            assert len(lab.notices.detail(row["key"])["transitions"]) == 2
            (tmp_path / "paced-receipt.json").write_text(
                json.dumps(
                    {
                        "basis": (
                            "Normally paced disposable SQLite supervisor; "
                            "no installed-overhead claim"
                        ),
                        "attempts": attempts,
                        "supervisor_progress": progress,
                        "recovered": row,
                    }
                ),
                encoding="utf-8",
            )
        finally:
            release.set()
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        if holder:
            holder.join(5)
        lab.registry.db = writable
        if readonly:
            readonly.close()
        lab.registry.close()
