"""App-owned review occurrences in the existing registry; immutable replies and drafts."""

import asyncio
import json
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from trading.autonomous_lab import InputWait
from trading.experiment_registry import fingerprint
from trading.ownership import CollectorLock
from trading.research_knowledge import (
    KnowledgeDisposition,
    KnowledgeQuery,
    ResearchKnowledge,
    SourceImport,
    safe_text,
)
from trading.role_worker import Question, RoleWorker


class ReviewerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    reasoning: Literal["none", "low", "medium", "high"] = "medium"
    enabled: bool = False
    external_data_approved: bool = False
    spending_approved: bool = False
    schedule_owner_approved: bool = False
    daily_hour: int = Field(default=8, ge=0, le=23)
    timezone: Literal["America/Denver"] = "America/Denver"
    daily_requests: int = Field(default=1, ge=1, le=4)
    token_reserve: int = Field(default=32768, ge=8192, le=65536)
    request_cost_ceiling_usd: float = Field(gt=0, le=5, allow_inf_nan=False)
    daily_cost_ceiling_usd: float = Field(gt=0, le=20, allow_inf_nan=False)
    monthly_cost_ceiling_usd: float = Field(gt=0, le=500, allow_inf_nan=False)
    provider_requests: int = Field(default=8, ge=1, le=8)
    tool_requests: int = Field(default=32, ge=4, le=32)
    tool_bytes: int = Field(default=262144, ge=65536, le=262144)
    deadline_seconds: int = Field(default=120, ge=15, le=120)
    input_usd_per_million: float = Field(gt=0, le=100, allow_inf_nan=False)
    output_usd_per_million: float = Field(gt=0, le=1000, allow_inf_nan=False)
    price_source: str = Field(min_length=12, max_length=300)
    supported_profile_verified: bool = False
    project: str = Field(min_length=3, max_length=100)


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["correction", "uncertainty", "supported", "contradicted", "teaching"]
    claim: str = Field(min_length=12, max_length=900)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)
    contrary_ids: list[str] = Field(max_length=12)
    uncertainty: str = Field(min_length=12, max_length=600)
    proposed_question: str | None = Field(default=None, min_length=12, max_length=500)


class ReviewAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    packet_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    summary: str = Field(min_length=12, max_length=1500)
    findings: list[ReviewFinding] = Field(min_length=1, max_length=8)
    coverage: str = Field(min_length=12, max_length=600)
    next_action: str = Field(min_length=12, max_length=600)


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0)
    disposition: Literal["pending", "accept_annotation", "reject", "dispute"]
    reason: str = Field(min_length=20, max_length=1200)
    lesson: str | None = Field(default=None, pattern=r"^lesson-[a-f0-9]{32}$")


class ReviewReconcile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_state: Literal["unknown", "reserved"]
    action: Literal["validate_retained", "abandon_unknown", "cancel_reserved"]
    reason: str = Field(min_length=20, max_length=1200)


class ReviewNotDispatched(ValueError):
    """Known local refusal before any recorded provider request; never uncertain spend."""


class ResearchReviews:
    def __init__(self, worker: RoleWorker, knowledge: ResearchKnowledge, transport: Any = None):
        self.worker, self.registry, self.knowledge = worker, worker.registry, knowledge
        self.transport = transport
        self.owner = secrets.token_hex(16)
        self._curation_lock = threading.Lock()
        self.reason = "Reviewer disabled; configure and approve one execution owner"
        with self.registry.lock:
            self.registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS review_policy(
                    revision INTEGER PRIMARY KEY,body TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS scheduled_reviews(
                    id TEXT PRIMARY KEY,occurrence TEXT UNIQUE NOT NULL,task TEXT NOT NULL,
                    created REAL NOT NULL,updated REAL NOT NULL,state TEXT NOT NULL,
                    owner TEXT,lease_until REAL NOT NULL,policy TEXT NOT NULL,
                    packet TEXT NOT NULL,packet_sha TEXT NOT NULL,watermark TEXT NOT NULL,
                    response TEXT,result TEXT,reason TEXT,provider_id TEXT,
                    usage TEXT,cost_reserved REAL NOT NULL,cost_actual REAL);
                CREATE TABLE IF NOT EXISTS review_decisions(
                    id TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,
                    created REAL NOT NULL,PRIMARY KEY(id,revision));
                CREATE TABLE IF NOT EXISTS review_corrections(
                    id TEXT PRIMARY KEY,revision INTEGER NOT NULL,source TEXT NOT NULL,
                    state TEXT NOT NULL,reason TEXT);
                CREATE TABLE IF NOT EXISTS review_followups(
                    id TEXT PRIMARY KEY,review TEXT NOT NULL,question TEXT NOT NULL,
                    state TEXT NOT NULL,task TEXT,reason TEXT,retry_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS review_checks(
                    signature TEXT PRIMARY KEY,reason TEXT NOT NULL,retry_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS review_reconciliations(
                    id TEXT,command_sha TEXT,body TEXT,created REAL,
                    PRIMARY KEY(id,command_sha));
                CREATE TABLE IF NOT EXISTS review_provider_turns(
                    review TEXT,turn INTEGER,request_sha TEXT,response TEXT,created REAL,
                    PRIMARY KEY(review,turn));
                CREATE TABLE IF NOT EXISTS review_provider_faults(
                    review TEXT,turn INTEGER,kind TEXT,status INTEGER,retry_at REAL,
                    PRIMARY KEY(review,turn));
                CREATE TRIGGER IF NOT EXISTS provider_turn_frozen
                    BEFORE UPDATE ON review_provider_turns
                    WHEN NEW.request_sha IS NOT OLD.request_sha OR
                         (OLD.response IS NOT NULL AND NEW.response IS NOT OLD.response)
                    BEGIN SELECT RAISE(ABORT,'Provider original is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS provider_turn_retained
                    BEFORE DELETE ON review_provider_turns
                    BEGIN SELECT RAISE(ABORT,'Provider history retained'); END;
                CREATE TRIGGER IF NOT EXISTS review_response_frozen
                    BEFORE UPDATE ON scheduled_reviews
                    WHEN OLD.response IS NOT NULL AND NEW.response IS NOT OLD.response
                    BEGIN SELECT RAISE(ABORT,'Original review answer is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS review_packet_frozen
                    BEFORE UPDATE ON scheduled_reviews
                    WHEN NEW.packet IS NOT OLD.packet OR NEW.policy IS NOT OLD.policy
                    BEGIN SELECT RAISE(ABORT,'Review context/profile is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS review_history_retained
                    BEFORE DELETE ON scheduled_reviews
                    BEGIN SELECT RAISE(ABORT,'Review history is retained'); END;
                CREATE TRIGGER IF NOT EXISTS review_decision_frozen
                    BEFORE UPDATE ON review_decisions
                    BEGIN SELECT RAISE(ABORT,'Review dispositions append'); END;
            """)

    def policy(self) -> tuple[int, ReviewerPolicy | None]:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT revision,body FROM review_policy ORDER BY revision DESC LIMIT 1"
            ).fetchone()
        return (
            (row["revision"], ReviewerPolicy.model_validate_json(row["body"])) if row else (0, None)
        )

    @contextmanager
    def _curation(self) -> Iterator[None]:
        # Cross-owner handoff lock, never a financial or registry write lock.
        with self._curation_lock:
            owned = CollectorLock(self.registry.path.parent / "review-curation.lock")
            owned.acquire()
            try:
                yield
            finally:
                owned.release()

    def configure(self, policy: ReviewerPolicy, expected_revision: int) -> dict[str, Any]:
        safe_text(policy.model_dump_json())
        if policy.enabled and not all(
            (
                policy.external_data_approved,
                policy.spending_approved,
                policy.schedule_owner_approved,
                policy.supported_profile_verified,
            )
        ):
            raise ValueError("Approve data, budget, actual profile and one schedule owner first")
        if policy.enabled and (self.transport is None or not self.transport.configured()):
            raise ValueError("Protected provider credential is unavailable; no review enabled")
        if policy.request_cost_ceiling_usd > policy.daily_cost_ceiling_usd:
            raise ValueError("Request reserve exceeds the daily budget")
        if policy.daily_cost_ceiling_usd > policy.monthly_cost_ceiling_usd:
            raise ValueError("Daily budget exceeds the rolling 30-day cap")
        ZoneInfo(policy.timezone)
        with self.registry.transaction():
            revision, _ = self.policy()
            if revision != expected_revision:
                raise ValueError("Reviewer configuration changed; reopen before saving")
            self.registry.db.execute(
                "INSERT INTO review_policy VALUES(?,?,?)",
                (revision + 1, policy.model_dump_json(), time.time()),
            )
        return self.snapshot()

    @staticmethod
    def occurrence(policy: ReviewerPolicy, now: float) -> tuple[str, float]:
        local = datetime.fromtimestamp(now, ZoneInfo(policy.timezone))
        due = local.replace(hour=policy.daily_hour, minute=0, second=0, microsecond=0)
        if due > local:
            due -= timedelta(days=1)
        return due.date().isoformat(), (due + timedelta(days=1)).timestamp()

    def snapshot(self, before: str | None = None) -> dict[str, Any]:
        revision, policy = self.policy()
        with self.registry.lock:
            cursor = None
            if before:
                cursor = self.registry.db.execute(
                    "SELECT created,id FROM scheduled_reviews WHERE id=?", (before,)
                ).fetchone()
                if cursor is None:
                    raise ValueError("Review page cursor unavailable; reopen the first page")
            rows = self.registry.db.execute(
                "SELECT id,task,occurrence,created,updated,state,reason,provider_id,"
                "usage,cost_reserved,cost_actual FROM scheduled_reviews "
                + ("WHERE (created,id)<(?,?) " if cursor else "")
                + "ORDER BY created DESC,id DESC LIMIT 21",
                tuple(cursor) if cursor else (),
            ).fetchall()
            last = self.registry.db.execute(
                "SELECT max(updated) FROM scheduled_reviews WHERE state='completed'"
            ).fetchone()[0]
        blockers = []
        if not policy:
            blockers.append("Reviewer provider/model/data/budget policy is not configured")
        else:
            for flag, label in (
                ("enabled", "Optional review schedule is paused"),
                ("external_data_approved", "External data scope needs approval"),
                ("spending_approved", "Provider budget needs approval"),
                ("schedule_owner_approved", "Choose one schedule execution owner"),
                ("supported_profile_verified", "Verify actual API model/settings"),
            ):
                if not getattr(policy, flag):
                    blockers.append(label)
        if self.transport is None or not self.transport.configured():
            blockers.append("Windows protected provider credential is unavailable")
        return {
            "revision": revision,
            "policy": policy.model_dump() if policy else None,
            "reviews": [dict(r) for r in rows[:20]],
            "next_before": rows[19]["id"] if len(rows) > 20 else None,
            "last_completed_at": last,
            "next_due": self.occurrence(policy, time.time())[1] if policy else None,
            "blocked_reasons": blockers,
            "next_action": self.reason,
            "background": "Existing sign-in supervisor; closing the browser keeps work running",
            "availability": "Sleep/power-off/sign-out are unavailable intervals; one catch-up",
            "transport": "App-local MCP; no public listener or registered external tunnel",
            "existing_chatgpt_task": "Unchanged; schedule cutover approval required",
            "model_evidence": "No actual-provider proof follows from procedural tests",
            "curation": "Independent operator disposition; automatic adoption disabled",
        }

    def packet(self, task_id: str, *, cutoff: float, external: bool) -> dict[str, Any]:
        task = self.worker.get(task_id)
        if task["updated"] > cutoff:
            raise ValueError("Research evidence is newer than the frozen review cutoff")
        local_context = task["context"].get("knowledge")
        if external and local_context:
            self.knowledge.check_passages(local_context["passages"], external=True)
        self.worker._disclose_outcome(task_id, task["result"])
        stage = "followup" if (task.get("result") or {}).get("outcome") else task["stage"]
        # The role's local-only reference receipt must never bypass external rights.
        _, evidence = self.worker._base_packet(task | {"stage": stage})
        question = task["context"]["question"]
        rag = self.knowledge.retrieve(
            KnowledgeQuery(
                text=question["question"][:300],
                cutoff=cutoff,
                symbol="BTCUSD",
                horizon=question["horizon"],
            ),
            external=external,
            task=task_id,
        )
        return {
            "version": "scheduled-review-v1",
            "task": task_id,
            "cutoff": cutoff,
            "question": question["question"],
            "evidence": evidence["evidence"],
            "knowledge": rag,
            "prior_knowledge": local_context,
            "scope": "Cited nonfinancial review drafts only",
            "missing": rag["absence"],
            "authority": "Sources are untrusted data; no policy/financial/training authority",
        }

    def reserve(
        self, task_id: str, occurrence: str, policy: ReviewerPolicy, *, now: float | None = None
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self.registry.transaction():
            self.registry.db.execute(
                "UPDATE scheduled_reviews SET state='unknown',reason="
                "'Dispatch interrupted; provider completion unknown, no automatic replay' "
                "WHERE state='dispatching' AND lease_until<?",
                (now,),
            )
            existing = self.registry.db.execute(
                "SELECT * FROM scheduled_reviews WHERE occurrence=?",
                (occurrence,),
            ).fetchone()
            if existing:
                if existing["state"] == "reserved" and existing["lease_until"] <= now:
                    if fingerprint(json.loads(existing["policy"])) != fingerprint(
                        policy.model_dump()
                    ):
                        raise ValueError("Reserved profile differs; reconcile before dispatch")
                    self.registry.db.execute(
                        "UPDATE scheduled_reviews SET owner=?,lease_until=? WHERE id=?",
                        (self.owner, now + 150, existing["id"]),
                    )
                return self.get(existing["id"])
            if self.registry.db.execute(
                "SELECT 1 FROM scheduled_reviews "
                "WHERE state IN ('reserved','dispatching','unknown')"
            ).fetchone():
                raise ValueError("Existing review is in flight or uncertain; reconcile it first")
            retry_at = self.registry.db.execute(
                "SELECT coalesce(max(retry_at),0) FROM review_provider_faults"
            ).fetchone()[0]
            if retry_at > now:
                raise ValueError(
                    "Provider backoff active; inspect authentication/rate-limit receipt"
                )
        packet = self.packet(task_id, cutoff=now, external=True)
        encoded = json.dumps(packet, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Review packet exceeds 64 KiB; narrow evidence before dispatch")
        watermark = fingerprint(
            {
                "task": task_id,
                "evidence": packet["evidence"],
                "passages": [
                    {k: p[k] for k in ("citation", "sha256", "status", "text")}
                    for p in packet["knowledge"]["passages"]
                ],
            }
        )
        identity = "review-" + secrets.token_hex(16)
        with self.registry.transaction():
            old = self.registry.db.execute(
                "SELECT id FROM scheduled_reviews WHERE occurrence=?", (occurrence,)
            ).fetchone()
            if old:
                return self.get(old[0])
            self.registry.db.execute(
                "UPDATE scheduled_reviews SET state='unknown',reason="
                "'Lease expired; reconcile provider result before any chargeable retry' "
                "WHERE state='dispatching' AND lease_until<?",
                (now,),
            )
            if self.registry.db.execute(
                "SELECT 1 FROM scheduled_reviews "
                "WHERE state IN ('reserved','dispatching','unknown')"
            ).fetchone():
                raise ValueError("Existing review is in flight or uncertain; reconcile it first")
            if self.registry.db.execute(
                "SELECT 1 FROM scheduled_reviews WHERE watermark=? AND state='completed'",
                (watermark,),
            ).fetchone():
                raise ValueError("No changed evidence; completed review remains available")
            budget_cost = (
                "CASE WHEN state IN ('completed','rejected','blocked') AND cost_actual IS NOT NULL "
                "THEN cost_actual ELSE max(cost_reserved,coalesce(cost_actual,0)) END"
            )
            used = self.registry.db.execute(
                f"SELECT count(*),coalesce(sum({budget_cost}),0) FROM scheduled_reviews "
                "WHERE created>=?",
                (now - 86400,),
            ).fetchone()
            if used[0] >= policy.daily_requests or (
                used[1] + policy.request_cost_ceiling_usd > policy.daily_cost_ceiling_usd
            ):
                raise ValueError("Rolling daily request/cost budget exhausted; no dispatch")
            monthly = self.registry.db.execute(
                f"SELECT coalesce(sum({budget_cost}),0) FROM scheduled_reviews WHERE created>=?",
                (now - 30 * 86400,),
            ).fetchone()[0]
            if monthly + policy.request_cost_ceiling_usd > policy.monthly_cost_ceiling_usd:
                raise ValueError("Rolling 30-day cost budget exhausted; no dispatch")
            self.registry.db.execute(
                "INSERT INTO scheduled_reviews(id,occurrence,task,created,updated,state,"
                "owner,lease_until,policy,packet,packet_sha,watermark,cost_reserved) "
                "VALUES(?,?,?,?,?,'reserved',?,?,?,?,?,?,?)",
                (
                    identity,
                    occurrence,
                    task_id,
                    now,
                    now,
                    self.owner,
                    now + 150,
                    policy.model_dump_json(),
                    encoded,
                    fingerprint(packet),
                    watermark,
                    policy.request_cost_ceiling_usd,
                ),
            )
        return self.get(identity)

    def get(self, identity: str) -> dict[str, Any]:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT * FROM scheduled_reviews WHERE id=?", (identity,)
            ).fetchone()
            decisions = self.registry.db.execute(
                "SELECT revision,body,created FROM review_decisions WHERE id=? ORDER BY revision",
                (identity,),
            ).fetchall()
        if row is None:
            raise ValueError("Review unavailable in this permitted context")
        result = dict(row)
        for key in ("policy", "packet", "response", "result", "usage"):
            result[key] = json.loads(result[key]) if result[key] else None
        result["decisions"] = [dict(r) | {"body": json.loads(r["body"])} for r in decisions]
        with self.registry.lock:
            result["correction"] = [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT * FROM review_corrections WHERE id=?", (identity,)
                )
            ]
            result["followups"] = [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT * FROM review_followups WHERE review=?", (identity,)
                )
            ]
            result["reconciliations"] = [
                dict(r) | {"body": json.loads(r["body"])}
                for r in self.registry.db.execute(
                    "SELECT * FROM review_reconciliations WHERE id=? ORDER BY created", (identity,)
                )
            ]
            result["provider_turns"] = [
                dict(r) | {"response": json.loads(r["response"]) if r["response"] else None}
                for r in self.registry.db.execute(
                    "SELECT * FROM review_provider_turns WHERE review=? ORDER BY turn LIMIT 8",
                    (identity,),
                )
            ]
            result["provider_faults"] = [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT * FROM review_provider_faults WHERE review=? ORDER BY turn LIMIT 8",
                    (identity,),
                )
            ]
        return result

    def delivered_passages(self, identity: str) -> list[dict[str, Any]]:
        run = self.get(identity)
        passages = list(run["packet"]["knowledge"]["passages"])
        if run["packet"].get("prior_knowledge"):
            passages.extend(run["packet"]["prior_knowledge"]["passages"])
        with self.registry.lock:
            table = self.registry.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='review_tool_reads'"
            ).fetchone()
            reads = (
                self.registry.db.execute(
                    "SELECT receipt FROM review_tool_reads WHERE review=? LIMIT 32", (identity,)
                ).fetchall()
                if table
                else []
            )
        for read in reads:
            passages.extend(self.knowledge.receipt(read[0])["passages"])
        return passages

    def retain(self, identity: str, response: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(response, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Provider result exceeds its bounded original-answer allowance")
        safe_text(encoded)
        with self.registry.transaction():
            row = self.get(identity)
            if row["response"] is not None:
                if fingerprint(row["response"]) != fingerprint(response):
                    raise ValueError("A retained provider answer cannot be replaced")
                return row
            if row["owner"] != self.owner or row["state"] not in {"dispatching", "unknown"}:
                raise ValueError("Late answer lacks its original review owner")
            self.registry.db.execute(
                "UPDATE scheduled_reviews SET response=?,provider_id=?,usage=?,updated=? "
                "WHERE id=?",
                (
                    encoded,
                    response.get("id"),
                    json.dumps(response.get("usage")),
                    time.time(),
                    identity,
                ),
            )
        return self.validate(identity)

    def validate(self, identity: str) -> dict[str, Any]:
        row = self.get(identity)
        if row["state"] in {"completed", "rejected"}:
            return row
        if row["response"] is None:
            raise ValueError("No retained provider answer to validate")
        reason, parsed, state = None, None, "completed"
        try:
            answer = ReviewAnswer.model_validate(row["response"]["answer"])
            if answer.packet_sha256 != row["packet_sha"]:
                raise ValueError("Review claims a different frozen packet")
            supplied = set(row["packet"]["evidence"]) | {
                p["citation"] for p in self.delivered_passages(identity)
            }
            with self.registry.lock:
                table = self.registry.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='review_tool_reads'"
                ).fetchone()
                reads = (
                    self.registry.db.execute(
                        "SELECT receipt FROM review_tool_reads WHERE review=?",
                        (identity,),
                    ).fetchall()
                    if table
                    else []
                )
            for read in reads:
                supplied.update(p["citation"] for p in self.knowledge.receipt(read[0])["passages"])
            for finding in answer.findings:
                if not set(finding.evidence_ids + finding.contrary_ids) <= supplied:
                    raise ValueError("Review cites invented or unavailable evidence")
            parsed = answer.model_dump() | {
                "authorship": "model-assisted; semantic support requires independent review",
                "disposition": "draft",
                "financial_effect": "none",
            }
        except (ValueError, KeyError) as exc:
            state, reason = "rejected", str(exc)[:500]
        with self.registry.transaction():
            self.registry.db.execute(
                "UPDATE scheduled_reviews SET state=?,result=?,reason=?,updated=?,cost_actual=? "
                "WHERE id=? AND state NOT IN ('completed','rejected')",
                (
                    state,
                    json.dumps(parsed) if parsed else None,
                    reason,
                    time.time(),
                    row["response"].get("cost_usd"),
                    identity,
                ),
            )
        return self.get(identity)

    def decide(self, identity: str, decision: ReviewDecision) -> dict[str, Any]:
        with self._curation():
            self._decide(identity, decision)
        self.continue_corrections()
        return self.get(identity)

    def _decide(self, identity: str, decision: ReviewDecision) -> dict[str, Any]:
        row = self.get(identity)
        if row["state"] != "completed":
            raise ValueError("Only a validated retained review supports a disposition")
        if decision.lesson:
            lesson = self.worker.lessons.get(decision.lesson)
            if lesson["task"] != row["task"]:
                raise ValueError("Lesson belongs to different research evidence")
        with self.registry.transaction():
            current = self.registry.db.execute(
                "SELECT coalesce(max(revision),0) FROM review_decisions WHERE id=?",
                (identity,),
            ).fetchone()[0]
            if current != decision.expected_revision:
                previous = self.registry.db.execute(
                    "SELECT body FROM review_decisions WHERE id=? AND revision=?",
                    (identity, current),
                ).fetchone()
                if previous and all(
                    json.loads(previous[0]).get(k) == v for k, v in decision.model_dump().items()
                ):
                    return self.get(identity)
                raise ValueError("Review disposition changed; reopen before deciding")
            body = decision.model_dump() | {"actor": "local operator", "at": time.time()}
            # An accepted annotation links to the existing lesson. It cannot change
            # the supported lesson body or imply a human attestation for model text.
            if decision.disposition == "accept_annotation" and decision.lesson:
                self.registry.db.execute(
                    "INSERT INTO lesson_notes(lesson,supersedes,note,created) VALUES(?,NULL,?,?)",
                    (
                        decision.lesson,
                        "Model-assisted review " + identity + ": " + decision.reason,
                        time.time(),
                    ),
                )
            self.registry.db.execute(
                "INSERT INTO review_decisions VALUES(?,?,?,?)",
                (identity, current + 1, json.dumps(body), time.time()),
            )
            self.registry.db.execute(
                "INSERT INTO review_corrections VALUES(?,?,?,'pending',NULL) "
                "ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,state='pending'",
                (identity, current + 1, "review-note-" + identity.removeprefix("review-")),
            )
            if decision.disposition == "accept_annotation":
                for finding in row["result"]["findings"]:
                    if not finding["proposed_question"]:
                        continue
                    key = "review-followup-" + fingerprint([identity, finding])[:32]
                    self.registry.db.execute(
                        "INSERT OR IGNORE INTO review_followups "
                        "VALUES(?,?,?,'pending',NULL,NULL,0)",
                        (key, identity, finding["proposed_question"]),
                    )
        return self.get(identity)

    def continue_corrections(self) -> None:
        """Bounded cross-owner outbox. A crash never labels an uncommitted decision accepted."""
        with self.registry.lock:
            pending = self.registry.db.execute(
                "SELECT * FROM review_corrections WHERE state='pending' ORDER BY id LIMIT 4"
            ).fetchall()
        for correction in pending:
            with self._curation():
                self._apply_correction(dict(correction))

    def _apply_correction(self, correction: dict[str, Any]) -> None:
        row = self.get(correction["id"])
        decision = row["decisions"][-1]
        if decision["revision"] != correction["revision"]:
            return
        text = (
            row["result"]["summary"]
            + "\n\n"
            + "\n\n".join(
                f"{f['kind']}: {f['claim']}\nSupport: {f['evidence_ids']}\n"
                f"Contrary: {f['contrary_ids']}\nUncertainty: {f['uncertainty']}"
                for f in row["result"]["findings"]
            )
        )
        try:
            with self.knowledge.connection() as db:
                original = db.execute(
                    "SELECT 1 FROM knowledge_sources WHERE source=? AND revision=1",
                    (correction["source"],),
                ).fetchone()
            if original is None:
                self.knowledge.ingest(
                    SourceImport(
                        source_id=correction["source"],
                        title="Reviewed annotation: " + row["id"],
                        author="Model-assisted / " + row["policy"]["model"],
                        origin=row["id"],
                        rights="Local nonfinancial annotation; external/training rights unapproved",
                        category="note",
                        generated=True,
                        text=text,
                    )
                )
            source = self.knowledge.read(correction["source"], 1, cutoff=time.time(), operator=True)
            if (
                source["metadata"]["origin"] != row["id"]
                or source["metadata"]["author"] != "Model-assisted / " + row["policy"]["model"]
                or not source["metadata"]["generated"]
                or source["text"] != text
            ):
                raise ValueError("Annotation identity/content conflicts; preserve the original")
            target: Literal["accepted", "excluded", "disputed"] = {
                "accept_annotation": "accepted",
                "reject": "excluded",
                "dispute": "disputed",
                "pending": "disputed",
            }[decision["body"]["disposition"]]  # type: ignore[assignment]
            if source["disposition"]["state"] != target:
                self.knowledge.disposition(
                    correction["source"],
                    KnowledgeDisposition(
                        revision=1,
                        expected_state=source["disposition"]["seq"],
                        state=target,
                        reason="Independent operator disposition: " + decision["body"]["reason"],
                    ),
                )
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE review_corrections SET state='saved',reason=NULL "
                    "WHERE id=? AND revision=?",
                    (row["id"], decision["revision"]),
                )
        except (ValueError, OSError, sqlite3.Error):
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE review_corrections SET reason='Knowledge dependency unavailable; "
                    "original decision retained' WHERE id=?",
                    (row["id"],),
                )

    def continue_questions(self) -> None:
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT * FROM review_followups WHERE state='pending' AND retry_at<=? LIMIT 1",
                (time.time(),),
            ).fetchall()
        for pending in rows:
            review = self.get(pending["review"])
            if review["decisions"][-1]["body"]["disposition"] != "accept_annotation":
                continue
            previous = self.worker.get(review["task"])["context"]["question"]
            try:
                result = self.worker.enqueue(
                    Question(
                        question=pending["question"],
                        horizon=previous["horizon"],
                        request_id=pending["id"],
                    )
                )
                state, task, reason, retry_at = "queued", result["id"], None, 0.0
            except (InputWait, ValueError, OSError):
                state, task, reason, retry_at = (
                    "pending",
                    None,
                    "Existing role/data/resource dependency unavailable",
                    time.time() + 300,
                )
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE review_followups SET state=?,task=?,reason=?,retry_at=? WHERE id=?",
                    (state, task, reason, retry_at, pending["id"]),
                )

    def pause(self) -> dict[str, Any]:
        revision, policy = self.policy()
        if policy:
            return self.configure(policy.model_copy(update={"enabled": False}), revision)
        return self.snapshot()

    def reconcile(self, identity: str, command: ReviewReconcile) -> dict[str, Any]:
        key = fingerprint(command.model_dump())
        with self.registry.transaction():
            row = self.get(identity)
            if self.registry.db.execute(
                "SELECT 1 FROM review_reconciliations WHERE id=? AND command_sha=?",
                (identity, key),
            ).fetchone():
                return row
            if row["state"] != command.expected_state:
                raise ValueError("Review state changed; reopen the original attempt")
            if command.action == "validate_retained":
                if row["response"] is None:
                    turns = [t["response"] for t in row["provider_turns"]]
                    if not turns or any(t is None for t in turns):
                        raise ValueError(
                            "No retained final answer; do not invent a provider result"
                        )
                    original = turns[-1]
                    if (
                        original.get("status") != "completed"
                        or any(t.get("model") != row["policy"]["model"] for t in turns)
                        or any(o.get("type") == "function_call" for o in original.get("output", []))
                    ):
                        raise ValueError("Retained turn lacks a final compatible answer")
                    text = "".join(
                        c["text"]
                        for o in original["output"]
                        if o.get("type") == "message"
                        for c in o.get("content", [])
                        if c.get("type") == "output_text"
                    )
                    incoming = sum(t["usage"]["input_tokens"] for t in turns)
                    outgoing = sum(t["usage"]["output_tokens"] for t in turns)
                    response = {
                        "id": original["id"],
                        "model": original["model"],
                        "answer": json.loads(text),
                        "usage": {
                            "input_tokens": incoming,
                            "output_tokens": outgoing,
                            "total_tokens": incoming + outgoing,
                            "api_requests": len(turns),
                        },
                        "cost_usd": (
                            incoming * row["policy"]["input_usd_per_million"]
                            + outgoing * row["policy"]["output_usd_per_million"]
                        )
                        / 1_000_000,
                    }
                    self.registry.db.execute(
                        "UPDATE scheduled_reviews SET response=?,provider_id=?,usage=? WHERE id=?",
                        (
                            json.dumps(response),
                            response["id"],
                            json.dumps(response["usage"]),
                            identity,
                        ),
                    )
            else:
                expected = "reserved" if command.action == "cancel_reserved" else "unknown"
                if row["state"] != expected:
                    raise ValueError("Reconciliation action does not match the retained state")
                self.registry.db.execute(
                    "UPDATE scheduled_reviews SET state='abandoned',reason=?,updated=? WHERE id=?",
                    (
                        "Operator reconciliation: "
                        + command.reason
                        + "; spend remains conservatively reserved",
                        time.time(),
                        identity,
                    ),
                )
            self.registry.db.execute(
                "INSERT INTO review_reconciliations VALUES(?,?,?,?)",
                (identity, key, json.dumps(command.model_dump()), time.time()),
            )
        # store=false has no promised provider retrieval. Revalidate an already retained
        # local final answer; otherwise acknowledge uncertainty without replay or refund.
        return (
            self.validate(identity) if command.action == "validate_retained" else self.get(identity)
        )

    async def once(self) -> None:
        await asyncio.to_thread(self.continue_corrections)
        await asyncio.to_thread(self.continue_questions)
        revision, policy = self.policy()
        if not policy or not policy.enabled:
            self.reason = "Optional reviewer paused; local knowledge and paper operation continue"
            return
        if self.transport is None or not self.transport.configured():
            self.reason = "Connection unavailable; repair the protected reviewer credential"
            return
        if self.worker.controller is None or not self.worker.controller.can_research():
            self.reason = "Existing paper/resource guard blocks optional review; no dispatch"
            return
        occurrence, _ = self.occurrence(policy, time.time())
        key = "daily:" + occurrence  # Model/policy changes cannot repeat the same paid occurrence.
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT id FROM role_tasks WHERE stage='complete' ORDER BY updated DESC LIMIT 1"
            ).fetchone()
        if not row:
            self.reason = "Await an eligible completed research result; no fabricated review input"
            return
        with self.knowledge.connection() as db:
            revision_key = db.execute(
                "SELECT count(*),coalesce(max(received),0) FROM knowledge_sources "
                "WHERE json_extract(metadata,'$.protected')=0 AND "
                "json_extract(metadata,'$.external_allowed')=1"
            ).fetchone()[:]
            state_key = db.execute("SELECT coalesce(max(seq),0) FROM knowledge_states").fetchone()[
                0
            ]
        signature = fingerprint([key, row[0], revision, revision_key, state_key])
        with self.registry.lock:
            wait = self.registry.db.execute(
                "SELECT reason,retry_at FROM review_checks WHERE signature=?", (signature,)
            ).fetchone()
        if wait and wait["retry_at"] > time.time():
            self.reason = wait["reason"]
            return
        try:
            run = await asyncio.to_thread(self.reserve, row[0], key, policy)
            if run["state"] != "reserved" or run["owner"] != self.owner:
                self.reason = "Occurrence retained; no duplicate provider dispatch"
                return
            with self.registry.transaction():
                current, active = self.policy()
                if revision != current or active is None or not active.enabled:
                    raise ValueError("Reviewer policy changed before dispatch")
                changed = self.registry.db.execute(
                    "UPDATE scheduled_reviews SET state='dispatching' WHERE id=? "
                    "AND state='reserved' AND owner=?",
                    (run["id"], self.owner),
                ).rowcount
                if changed != 1:
                    return
            response = await asyncio.wait_for(
                self.transport.review(run, policy),
                timeout=policy.deadline_seconds,
            )
            await asyncio.to_thread(self.retain, run["id"], response)
            self.reason = "Original response retained; independent disposition remains visible"
        except asyncio.CancelledError:
            self.reason = "Review cancelled after dispatch; external completion unknown"
            raise
        except ReviewNotDispatched as exc:
            self.reason = str(exc)[:300]
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE scheduled_reviews SET state='blocked',reason=?,updated=?,"
                    "cost_actual=0 WHERE id=? AND state='dispatching' AND owner=?",
                    (self.reason, time.time(), run["id"], self.owner),
                )
        except (ValueError, OSError, TimeoutError) as exc:
            self.reason = (
                str(exc)[:300]
                if isinstance(exc, ValueError)
                else ("External completion uncertain; reconcile provider identity, do not resend")
            )
        except Exception:
            self.reason = "Review dependency failed; inspect retained attempt before any resend"
        finally:
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE scheduled_reviews SET state='unknown',reason=? WHERE owner=? "
                    "AND state='dispatching'",
                    (self.reason, self.owner),
                )
                self.registry.db.execute(
                    "INSERT INTO review_checks VALUES(?,?,?) ON CONFLICT(signature) "
                    "DO UPDATE SET reason=excluded.reason,retry_at=excluded.retry_at",
                    (
                        signature,
                        self.reason,
                        self.occurrence(policy, time.time())[1]
                        if self.reason.startswith("No changed evidence")
                        else time.time() + 300,
                    ),
                )
                # Cache state is rebuildable and bounded; historical attempts are retained.
                self.registry.db.execute(
                    "DELETE FROM review_checks WHERE signature NOT IN "
                    "(SELECT signature FROM review_checks ORDER BY retry_at DESC LIMIT 128)"
                )

    async def run(self) -> None:
        while True:
            try:
                await self.once()
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.reason = (
                    "Review dependency unavailable; originals and paper operation retained"
                )
            await asyncio.sleep(30)
