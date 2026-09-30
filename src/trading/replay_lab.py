"""Durable finite replay requests and an isolated, resource-limited optional worker."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import sysconfig
import tempfile
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading.execution_replay import (
    CONTRACT,
    MAX_INPUT_BYTES,
    MAX_RECORDS,
    MAX_RESULT_BYTES,
    source_hashes,
)
from trading.numerical_resources import child_rss, constrain_child
from trading.research_acquisition import replay_records
from trading.research_evidence import EvidenceArchive, canonical, digest
from trading.research_storage import ResearchStorage


class ReplayPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,48}$")
    record_id: int | str
    records: int = Field(default=16, ge=1, le=MAX_RECORDS)

    @model_validator(mode="after")
    def exact_reference(self) -> "ReplayPlan":
        if isinstance(self.record_id, int):
            if not 1 <= self.record_id <= 2**63 - 1:
                raise ValueError("Invalid legacy decision identity")
        else:
            ResearchStorage.parse_reference(self.record_id)
        return self


class ReplayRegistry:
    def __init__(self, path: Path):
        self.path, self.lock = path, Lock()
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=1)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA max_page_count=16384")
            self.connection.execute("PRAGMA journal_size_limit=8388608")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS replay_runs (
                id INTEGER PRIMARY KEY, request TEXT UNIQUE NOT NULL,
                at REAL NOT NULL, status TEXT NOT NULL, plan TEXT NOT NULL,
                plan_hash TEXT NOT NULL, inputs TEXT, inputs_hash TEXT,
                result TEXT, result_hash TEXT, error TEXT, resources TEXT
            )""")
            with self.connection:
                self.connection.execute(
                    "UPDATE replay_runs SET status='interrupted',error=? "
                    "WHERE status IN ('running','capturing')",
                    ("Service restarted before completion; original attempt retained",),
                )
        except Exception:
            self.connection.close()
            raise

    def reserve(self, plan: ReplayPlan) -> dict[str, Any]:
        frozen = {
            "request": plan.model_dump(),
            "contract": CONTRACT,
            "source_files": source_hashes(),
        }
        body, sha = canonical(frozen), digest(frozen)
        with self.lock, self.connection:
            old = self.connection.execute(
                "SELECT * FROM replay_runs WHERE request=?", (plan.request_id,)
            ).fetchone()
            if old:
                if old["plan_hash"] != sha:
                    raise ValueError("Existing replay request cannot change its frozen plan/source")
                return {"request_id": plan.request_id, "status": old["status"], "retry": True}
            if self.connection.execute("SELECT count(*) FROM replay_runs").fetchone()[0] >= 128:
                raise ValueError("Replay receipt capacity reached; no old attempts were evicted")
            if (
                self.connection.execute(
                    "SELECT count(*) FROM replay_runs "
                    "WHERE status IN ('queued','capturing','running')"
                ).fetchone()[0]
                >= 8
            ):
                raise ValueError("Replay queue is full; paper management continues")
            self.connection.execute(
                "INSERT INTO replay_runs(request,at,status,plan,plan_hash) "
                "VALUES (?,?,'capturing',?,?)",
                (plan.request_id, time.time(), body, sha),
            )
        return {"request_id": plan.request_id, "status": "capturing", "retry": False}

    def inputs(self, request: str, inputs: list[dict[str, Any]]) -> None:
        body = canonical(inputs)
        if len(body.encode()) > MAX_INPUT_BYTES:
            raise ValueError("Input slice exceeds its frozen sixteen-MiB budget")
        with self.lock, self.connection:
            size = self.connection.execute(
                "SELECT coalesce(sum(length(inputs)),0)+coalesce(sum(length(result)),0) "
                "FROM replay_runs"
            ).fetchone()[0]
            if size + len(body.encode()) + MAX_RESULT_BYTES > 56 * 1024**2:
                raise ValueError("Protected replay inputs reached capacity; no evidence was pruned")
            self.connection.execute(
                "UPDATE replay_runs SET inputs=?,inputs_hash=?,status='queued' "
                "WHERE request=? AND status='capturing'",
                (body, digest(inputs), request),
            )

    def claim(self) -> dict[str, Any] | None:
        with self.lock, self.connection:
            row = self.connection.execute(
                "SELECT request FROM replay_runs WHERE status='queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            self.connection.execute(
                "UPDATE replay_runs SET status='running' WHERE request=? AND status='queued'",
                (row["request"],),
            )
        return self.get(row["request"], inputs=True)

    def finish(
        self,
        request: str,
        result: dict[str, Any] | None,
        error: str | None,
        resources: dict[str, Any] | None = None,
    ) -> None:
        body = canonical(result) if result is not None else None
        if body and len(body.encode()) > MAX_RESULT_BYTES:
            body, error = None, "Replay result exceeded its frozen evidence budget"
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE replay_runs SET status=?,result=?,result_hash=?,error=?,resources=? "
                "WHERE request=? AND status IN ('running','capturing','queued')",
                (
                    "failed" if error else "completed",
                    body,
                    digest(result) if body else None,
                    error,
                    canonical(resources) if resources else None,
                    request,
                ),
            )

    def get(self, request: str, *, inputs: bool = False) -> dict[str, Any] | None:
        with self.lock:
            fields = (
                "*"
                if inputs
                else "id,request,at,status,plan,plan_hash,result,result_hash,error,resources"
            )
            row = self.connection.execute(
                f"SELECT {fields} FROM replay_runs WHERE request=?", (request,)
            ).fetchone()
        if not row:
            return None
        out = dict(row)
        for field in ("plan", "inputs", "result", "resources"):
            if field in out and out[field]:
                value = json.loads(out[field])
                sha = out.get(
                    {"plan": "plan_hash", "inputs": "inputs_hash", "result": "result_hash"}.get(
                        field, ""
                    )
                )
                if sha and digest(value) != sha:
                    raise ValueError("Replay receipt is corrupt; no substitute was inferred")
                out[field] = value
        return out

    def snapshot(self, before: int = 0) -> dict[str, Any]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT id,request,at,status,error FROM replay_runs "
                "WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT 21",
                (before, before),
            ).fetchall()
            count = self.connection.execute("SELECT count(*) FROM replay_runs").fetchone()[0]
        return {
            "runs": [dict(r) for r in rows[:20]],
            "has_more": len(rows) > 20,
            "next_before": rows[19]["id"] if len(rows) > 20 else None,
            "total": count,
            "capacity": 128,
            "contract": CONTRACT,
        }

    def resources(self, request: str, resources: dict[str, Any]) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE replay_runs SET resources=? WHERE request=? AND resources IS NULL",
                (canonical(resources), request),
            )

    def close(self) -> None:
        self.connection.close()


class ReplayLab:
    def __init__(self, path: Path, evidence: Path, can_research: Callable[[], bool]):
        self.registry, self.evidence = ReplayRegistry(path), evidence
        self.can_research = can_research
        self.child: subprocess.Popen[bytes] | None = None
        self.blocked_reason: str | None = None
        self.busy = False

    def enqueue(self, plan: ReplayPlan) -> dict[str, Any]:
        receipt = self.registry.reserve(plan)
        if receipt["retry"]:
            return receipt
        try:
            records = replay_records(self.evidence, plan.record_id, plan.records, time.time())
            for record in records:
                if digest(record["payload"]) != record["sha256"]:
                    raise ValueError("Selected input is corrupt")
            if any(record["archive"] == "full" for record in records):
                with closing(EvidenceArchive(self.evidence)) as archive:
                    for record in records:
                        if record["archive"] != "full":
                            continue
                        archive.pin(
                            f"replay:{plan.request_id}:{record['id']}",
                            record["id"],
                            record["sha256"],
                        )
            self.registry.inputs(plan.request_id, records)
        except (sqlite3.Error, OSError, ValueError, KeyError, json.JSONDecodeError):
            self.registry.finish(
                plan.request_id,
                None,
                "Recorded inputs unavailable, corrupt or at capacity; original attempt retained",
            )
        job = self.registry.get(plan.request_id)
        return {**receipt, "status": job["status"] if job else "failed"}

    async def run_once(self) -> bool:
        if self.busy or not self.can_research():
            self.blocked_reason = "Replay yielding to paper health or other numerical research"
            return False
        self.busy = True
        job = None
        started, peak = time.perf_counter(), 0
        try:
            job = self.registry.claim()
            if not job:
                return False
            self.blocked_reason = None
            with tempfile.TemporaryDirectory(prefix="qtrades-replay-") as directory:
                path = Path(directory)
                input_file, output_file = path / "input.json", path / "result.json"
                input_file.write_text(
                    canonical(
                        {"records": job["inputs"], "source_files": job["plan"]["source_files"]}
                    ),
                    encoding="utf-8",
                )
                env = {
                    k: v
                    for k, v in os.environ.items()
                    if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
                }
                env["PYTHONPATH"] = os.pathsep.join(
                    [str(Path(__file__).resolve().parents[1]), sysconfig.get_paths()["purelib"]]
                )
                env["PYTHONNOUSERSITE"] = "1"
                flags = (
                    subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS
                    if os.name == "nt"
                    else 0
                )
                self.child = subprocess.Popen(
                    [
                        str(Path(getattr(sys, "_base_executable", sys.executable)).resolve()),
                        "-m",
                        "trading.replay_worker",
                        str(input_file),
                        str(output_file),
                    ],
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
                constrain_child(self.child.pid)
                reason = None
                while self.child.poll() is None:
                    peak = max(peak, child_rss(self.child.pid))
                    if time.perf_counter() - started > 25:
                        reason = "Replay exceeded its twenty-five-second limit"
                    elif peak > 256 * 1024**2:
                        reason = "Replay exceeded its 256-MiB memory limit"
                    elif not self.can_research():
                        reason = "Protected resource pressure interrupted replay"
                    if reason:
                        self.child.terminate()
                        await asyncio.to_thread(self.child.wait, 3)
                        break
                    await asyncio.sleep(0.1)
                if reason:
                    self.registry.finish(job["request"], None, reason)
                elif (
                    self.child.returncode != 0
                    or not output_file.is_file()
                    or output_file.stat().st_size > MAX_RESULT_BYTES
                ):
                    self.registry.finish(
                        job["request"],
                        None,
                        "Replay child exited without a bounded retained result",
                    )
                else:
                    output = json.loads(output_file.read_text(encoding="utf-8"))
                    self.registry.finish(
                        job["request"],
                        output.get("result"),
                        output.get("error"),
                        {
                            "wall_seconds": time.perf_counter() - started,
                            "peak_rss_bytes": peak,
                            "processors_max": 2,
                            "gpu": False,
                            "paid_usd": "0",
                        },
                    )
            return True
        except asyncio.CancelledError:
            if self.child and self.child.poll() is None:
                self.child.terminate()
                await asyncio.to_thread(self.child.wait, 3)
            if job:
                self.registry.finish(
                    job["request"],
                    None,
                    "Replay interrupted by shutdown; original attempt retained",
                )
            raise
        except (OSError, subprocess.SubprocessError, ValueError, sqlite3.Error):
            if self.child and self.child.poll() is None:
                self.child.terminate()
                await asyncio.to_thread(self.child.wait, 3)
            if job:
                self.registry.finish(
                    job["request"], None, "Replay could not complete; original attempt retained"
                )
            return False
        finally:
            self.child, self.busy = None, False
            if job:
                self.registry.resources(
                    job["request"],
                    {
                        "wall_seconds": time.perf_counter() - started,
                        "peak_rss_bytes": peak,
                        "processors_max": 2,
                        "gpu": False,
                        "paid_usd": "0",
                    },
                )

    async def run(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(2)

    def snapshot(self, before: int = 0) -> dict[str, Any]:
        return {
            **self.registry.snapshot(before),
            "active_child": self.child is not None,
            "blocked_reason": self.blocked_reason,
            "financial_authority": False,
        }
