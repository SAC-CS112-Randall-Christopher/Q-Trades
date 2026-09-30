"""Durable, bounded research evidence; no financial connection or executable proposals."""

import hashlib
import json
import math
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PREFLIGHT_END = 1790595239.9180105
MAX_JOBS = 512
MAX_QUEUE = 8
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 256 * 1024
# Complete CP13 shadow cohorts have per-prefix classification/match receipts.
# This extension keeps old modes' limits and the 512-MiB physical registry ceiling.
SHADOW_RESULT_BYTES = 2 * 1024 * 1024
TERMINAL = {"completed", "failed", "cancelled", "rejected"}


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class ExperimentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{8,64}$")
    name: str = Field(min_length=3, max_length=100)
    mechanism: str = Field(min_length=12, max_length=1000)
    falsification: str = Field(min_length=12, max_length=1000)
    feature: Literal["momentum_1", "momentum_5", "volatility_5", "spread_bps"] = "momentum_5"
    experiment_mode: Literal[
        "quote_ridge",
        "distinct_families",
        "memory_entry",
        "context_regime",
        "order_flow",
        "growing_memory",
        "component_exit",
        "component_size",
        "observation_priority",
    ] = "quote_ridge"
    horizon_minutes: Literal[5, 15, 45, 60] = 5
    as_of: float
    test_start: float
    test_end: float
    evidence_kind: Literal["observed_public_quotes", "synthetic_qa"] = "observed_public_quotes"

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        if (
            self.experiment_mode
            in {
                "memory_entry",
                "context_regime",
                "order_flow",
                "growing_memory",
                "component_exit",
                "component_size",
                "observation_priority",
            }
        ) != (self.horizon_minutes == 45):
            raise ValueError("Memory uses the original 45-minute horizon; other modes keep theirs")
        if self.experiment_mode == "distinct_families" and self.horizon_minutes != 60:
            raise ValueError("The common family group reserves the longest 60-minute horizon")
        if not all(math.isfinite(v) for v in (self.as_of, self.test_start, self.test_end)):
            raise ValueError("Evaluation timestamps must be finite")
        if not 0 < self.test_start < self.test_end <= self.as_of:
            raise ValueError("Declare chronological evaluation and observation boundaries")
        if self.as_of > time.time() + 5:
            raise ValueError("Future observations cannot be frozen")
        return self


class ExperimentRegistry:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=2, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "PRAGMA max_page_count=131072"
        )  # 512 MiB; stop instead of pruning evidence.
        self.db.execute("PRAGMA journal_size_limit=8388608")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS experiments (
                seq INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                plan TEXT NOT NULL, plan_sha256 TEXT NOT NULL, code_sha256 TEXT NOT NULL,
                created REAL NOT NULL, finished REAL, status TEXT NOT NULL,
                snapshot TEXT, snapshot_sha256 TEXT, result TEXT, result_sha256 TEXT,
                reason TEXT, attempt INTEGER NOT NULL DEFAULT 0,
                lease TEXT, lease_until REAL, progress TEXT NOT NULL DEFAULT 'Waiting for inputs'
            );
            CREATE TABLE IF NOT EXISTS evidence_windows (
                request_id TEXT PRIMARY KEY, start REAL NOT NULL, end REAL NOT NULL,
                origin TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS evidence_overlap ON evidence_windows(start,end);
            CREATE TABLE IF NOT EXISTS experiment_events (
                seq INTEGER PRIMARY KEY, request_id TEXT NOT NULL, at REAL NOT NULL,
                kind TEXT NOT NULL, body TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS immutable_windows_update BEFORE UPDATE ON evidence_windows
                BEGIN SELECT RAISE(ABORT, 'Consumed evidence is permanent'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_windows_delete BEFORE DELETE ON evidence_windows
                BEGIN SELECT RAISE(ABORT, 'Consumed evidence is permanent'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_experiment_plan BEFORE UPDATE ON experiments
                WHEN NEW.plan != OLD.plan OR NEW.plan_sha256 != OLD.plan_sha256
                OR NEW.code_sha256 != OLD.code_sha256 OR NEW.request_id != OLD.request_id
                BEGIN SELECT RAISE(ABORT, 'Evaluation plans are frozen'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_experiment_delete BEFORE DELETE ON experiments
                BEGIN SELECT RAISE(ABORT, 'Experiment history is permanent'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_frozen_payload BEFORE UPDATE ON experiments
                WHEN (OLD.snapshot IS NOT NULL AND NEW.snapshot IS NOT OLD.snapshot)
                OR (OLD.result IS NOT NULL AND NEW.result IS NOT OLD.result)
                BEGIN SELECT RAISE(ABORT, 'Frozen inputs and results are permanent'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_event_update BEFORE UPDATE ON experiment_events
                BEGIN SELECT RAISE(ABORT, 'Experiment events are permanent'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_event_delete BEFORE DELETE ON experiment_events
                BEGIN SELECT RAISE(ABORT, 'Experiment events are permanent'); END;
        """)
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(experiments)")}
        if "manifest" not in columns:
            # One-time projection of immutable inputs; never reserialize their payload.
            with self.transaction():
                self.db.execute("ALTER TABLE experiments ADD COLUMN manifest TEXT")
                self.db.execute(
                    "UPDATE experiments SET manifest=json_extract(snapshot,'$.manifest') "
                    "WHERE snapshot IS NOT NULL"
                )
        self.db.executescript("""
            CREATE TRIGGER IF NOT EXISTS immutable_input_manifest BEFORE UPDATE ON experiments
                WHEN OLD.manifest IS NOT NULL AND NEW.manifest IS NOT OLD.manifest
                BEGIN SELECT RAISE(ABORT, 'Frozen input manifest is permanent'); END;
        """)
        with self.transaction():
            self.db.execute(
                "INSERT OR IGNORE INTO evidence_windows VALUES ('retained-preflight',0,?,?)",
                (
                    PREFLIGHT_END,
                    "Verified retained quote-ridge-v1 rejection; all features protected",
                ),
            )
            row = self.db.execute(
                "SELECT end FROM evidence_windows WHERE request_id='retained-preflight'"
            ).fetchone()
            if row[0] != PREFLIGHT_END:
                raise ValueError("Retained preflight boundary differs; research stopped")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def event(self, request_id: str, kind: str, body: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO experiment_events(request_id,at,kind,body) VALUES (?,?,?,?)",
            (request_id, time.time(), kind, json.dumps(body, sort_keys=True, allow_nan=False)),
        )

    def reserve(self, plan: ExperimentPlan, code_hash: str) -> dict[str, Any]:
        digest = fingerprint(plan.model_dump())
        with self.transaction():
            old = self.db.execute(
                "SELECT * FROM experiments WHERE request_id=?", (plan.request_id,)
            ).fetchone()
            if old:
                if old["plan_sha256"] != digest or old["code_sha256"] != code_hash:
                    raise ValueError("Retry must preserve the frozen plan and code")
                return {"request_id": plan.request_id, "status": old["status"], "retry": True}
            if self.db.execute("SELECT count(*) FROM experiments").fetchone()[0] >= MAX_JOBS:
                raise ValueError(
                    "Registry capacity reached; preserve/export history before extending"
                )
            if (
                self.db.execute(
                    "SELECT count(*) FROM experiments "
                    "WHERE status IN ('acquiring','queued','running')"
                ).fetchone()[0]
                >= MAX_QUEUE
            ):
                raise ValueError("Research queue is full; position management retains priority")
            # Conservative information-domain protection spans features, hashes and instruments.
            # Labels may overlap a prior period even when their feature timestamps do not.
            protected_start = plan.test_start - plan.horizon_minutes * 60
            overlap = self.db.execute(
                "SELECT request_id FROM evidence_windows WHERE start <= ? AND end >= ? LIMIT 1",
                (plan.test_end, protected_start),
            ).fetchone()
            if overlap:
                raise ValueError(
                    "Evaluation overlaps consumed information; choose a later untouched window"
                )
            self.db.execute(
                "INSERT INTO experiments(request_id,plan,plan_sha256,code_sha256,created,status) "
                "VALUES (?,?,?,?,?,'acquiring')",
                (plan.request_id, plan.model_dump_json(), digest, code_hash, time.time()),
            )
            self.db.execute(
                "INSERT INTO evidence_windows VALUES (?,?,?,'predeclared evaluation')",
                (plan.request_id, protected_start, plan.test_end),
            )
            self.event(
                plan.request_id, "plan_frozen", {"plan_sha256": digest, "code_sha256": code_hash}
            )
        return {"request_id": plan.request_id, "status": "acquiring", "retry": False}

    def inputs(self, request_id: str, snapshot: dict[str, Any]) -> None:
        encoded = json.dumps(snapshot, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > MAX_SNAPSHOT_BYTES:
            self.fail_inputs(request_id, "Snapshot exceeds the frozen input-size budget")
            return
        with self.transaction():
            changed = self.db.execute(
                "UPDATE experiments SET snapshot=?,snapshot_sha256=?,"
                "manifest=json_extract(?,'$.manifest'),status='queued',"
                "progress='Inputs frozen; waiting for worker' "
                "WHERE request_id=? AND status='acquiring'",
                (encoded, fingerprint(snapshot), encoded, request_id),
            ).rowcount
            if changed:
                self.event(request_id, "inputs_frozen", {"snapshot_sha256": fingerprint(snapshot)})

    def fail_inputs(self, request_id: str, reason: str) -> None:
        with self.transaction():
            changed = self.db.execute(
                "UPDATE experiments SET status='failed',finished=?,reason=?,"
                "progress='Input failure' "
                "WHERE request_id=? AND status='acquiring'",
                (time.time(), reason, request_id),
            ).rowcount
            if changed:
                self.event(request_id, "input_failure", {"reason": reason})

    def claim(self, now: float | None = None) -> dict[str, Any] | None:
        now = time.time() if now is None else now
        with self.transaction():
            for row in self.db.execute(
                "SELECT request_id FROM experiments WHERE status='acquiring' AND created < ?",
                (now - 30,),
            ).fetchall():
                self.db.execute(
                    "UPDATE experiments SET status='failed',finished=?,"
                    "reason='Input acquisition interrupted',progress='Failure retained' "
                    "WHERE request_id=?",
                    (now, row["request_id"]),
                )
                self.event(
                    row["request_id"],
                    "input_failure",
                    {
                        "reason": "Acquisition interrupted; consumed window cannot be retried",
                    },
                )
            for row in self.db.execute(
                "SELECT request_id,attempt FROM experiments "
                "WHERE status='running' AND lease_until < ?",
                (now,),
            ).fetchall():
                status = "queued" if row["attempt"] < 2 else "failed"
                self.db.execute(
                    "UPDATE experiments SET status=?,lease=NULL,reason='Worker lease expired',"
                    "progress='Interrupted attempt retained' WHERE request_id=?",
                    (status, row["request_id"]),
                )
                self.event(row["request_id"], "lease_expired", {"attempt": row["attempt"]})
            if self.db.execute(
                "SELECT 1 FROM experiments WHERE status='running' LIMIT 1"
            ).fetchone():
                return None
            row = self.db.execute(
                "SELECT request_id,attempt FROM experiments "
                "WHERE status='queued' ORDER BY seq LIMIT 1"
            ).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            self.db.execute(
                "UPDATE experiments SET status='running',attempt=attempt+1,lease=?,lease_until=?,"
                "reason=NULL,progress='Evaluating frozen inputs' WHERE request_id=?",
                (token, now + 30, row["request_id"]),
            )
            self.event(row["request_id"], "attempt_started", {"attempt": row["attempt"] + 1})
            return dict(row, lease=token, attempt=row["attempt"] + 1)

    def finish(
        self, request_id: str, token: str, result: dict[str, Any] | None, reason: str | None
    ) -> bool:
        body = json.dumps(result, sort_keys=True, allow_nan=False) if result is not None else None
        row = self.db.execute(
            "SELECT json_extract(plan,'$.experiment_mode') FROM experiments WHERE request_id=?",
            (request_id,),
        ).fetchone()
        limit = (
            SHADOW_RESULT_BYTES
            if row
            and row[0]
            in {
                "context_regime",
                "order_flow",
                "growing_memory",
                "component_exit",
                "component_size",
                "observation_priority",
            }
            else MAX_RESULT_BYTES
        )
        if body and len(body.encode()) > limit:
            body, reason = None, "Result exceeds the evidence-size budget"
        status = "failed" if reason else "completed"
        with self.transaction():
            changed = self.db.execute(
                "UPDATE experiments SET status=?,finished=?,result=?,result_sha256=?,reason=?,"
                "progress='Finished',lease=NULL WHERE request_id=? AND status='running' "
                "AND lease=? AND lease_until >= ?",
                (
                    status,
                    time.time(),
                    body,
                    fingerprint(result) if body else None,
                    reason,
                    request_id,
                    token,
                    time.time(),
                ),
            ).rowcount
            if changed:
                self.event(request_id, "result_retained", {"status": status, "reason": reason})
        return bool(changed)

    def cancel(self, request_id: str) -> None:
        with self.transaction():
            changed = self.db.execute(
                "UPDATE experiments SET status='cancelled',finished=?,lease=NULL,"
                "reason='Operator cancelled; evidence remains consumed' WHERE request_id=? "
                "AND status IN ('acquiring','queued','running')",
                (time.time(), request_id),
            ).rowcount
            if changed:
                self.event(request_id, "cancelled", {"consumption_preserved": True})

    def status(self, request_id: str) -> str | None:
        with self.lock:
            row = self.db.execute(
                "SELECT status FROM experiments WHERE request_id=?", (request_id,)
            ).fetchone()
            return str(row[0]) if row else None

    def get(self, request_id: str, *, inputs: bool = False) -> dict[str, Any] | None:
        with self.lock:
            fields = (
                "*"
                if inputs
                else (
                    "seq,request_id,plan,plan_sha256,code_sha256,created,finished,status,"
                    "snapshot_sha256,result,result_sha256,reason,attempt,lease_until,progress,manifest"
                )
            )
            row = self.db.execute(
                f"SELECT {fields} FROM experiments WHERE request_id=?", (request_id,)
            ).fetchone()
            if not row:
                return None
            value = dict(row)
            for field in ("plan", "result", "manifest", *(["snapshot"] if inputs else [])):
                value[field] = json.loads(value[field]) if value[field] else None
            value["events"] = [
                dict(r)
                for r in self.db.execute(
                    "SELECT at,kind,body FROM experiment_events WHERE request_id=? ORDER BY seq",
                    (request_id,),
                )
            ]
            return value

    def snapshot(self, before: int = 0) -> dict[str, Any]:
        with self.lock:
            rows = self.db.execute(
                "SELECT seq,request_id,plan,status,created,finished,reason,progress,attempt "
                "FROM experiments WHERE (?=0 OR seq<?) ORDER BY seq DESC LIMIT 21",
                (before, before),
            ).fetchall()
            counts = {
                r["status"]: r["n"]
                for r in self.db.execute(
                    "SELECT status,count(*) AS n FROM experiments GROUP BY status"
                )
            }
            protected_end = self.db.execute("SELECT max(end) FROM evidence_windows").fetchone()[0]
        return {
            "runs": [dict(r, plan=json.loads(r["plan"])) for r in rows[:20]],
            "next_cursor": rows[19]["seq"] if len(rows) > 20 else None,
            "counts": counts,
            "capacity": MAX_JOBS,
            "queue_capacity": MAX_QUEUE,
            "protected_through": protected_end,
            "preflight_boundary": PREFLIGHT_END,
            "preflight_result": "Rejected: zero positive-after-cost predictions",
            "paid_budget_usd": "0",
            "financial_authority": False,
        }

    def close(self) -> None:
        self.db.close()
