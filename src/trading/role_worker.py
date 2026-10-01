"""Optional sequential local roles in the existing registry, outside financial locks."""

import asyncio
import json
import math
import secrets
import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading import autonomous_finance as finance
from trading.autonomous_lab import AutonomousLab, InputWait
from trading.autonomous_spec import LabProposal, RuleSpec, rule_feature
from trading.evidence_runtime import plain
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.lab_role_contract import VERSION, Idea, Review, validate
from trading.research_storage import ResearchStorage, load_plan
from trading.role_history import HOT_TASKS, RoleHistory
from trading.scoped_tools import reader


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=12, max_length=500)
    horizon: Literal["short", "medium", "long"] = "short"
    parent: str | None = Field(default=None, max_length=100)
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")


class RoleWorker:
    def __init__(
        self, registry: ExperimentRegistry, controller: AutonomousLab | None, transport: Any = None
    ):
        self.registry, self.controller, self.transport = registry, controller, transport
        self.owner = secrets.token_hex(16)
        self.enabled = False  # Only separately authorized, qualified policy enables inference.
        self.activation: Callable[[], bool] | None = None
        self.reason = "Optional role policy is disabled; operating paper work continues"
        with registry.lock:
            registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS role_tasks(
                    id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
                    stage TEXT NOT NULL, status TEXT NOT NULL, context TEXT NOT NULL,
                    proposal TEXT, evaluation TEXT, result TEXT, reason TEXT,
                    owner TEXT, lease_until REAL, retry_at REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS role_attempts(
                    task TEXT NOT NULL, stage TEXT NOT NULL, attempt INTEGER NOT NULL,
                    started REAL NOT NULL, finished REAL, status TEXT NOT NULL,
                    profile TEXT NOT NULL, packet TEXT NOT NULL, response TEXT,
                    reason TEXT, wall_reserved REAL NOT NULL, tokens_reserved INTEGER NOT NULL,
                    PRIMARY KEY(task,stage,attempt));
                CREATE TABLE IF NOT EXISTS role_requests(
                    request_id TEXT PRIMARY KEY, question_sha256 TEXT NOT NULL, task TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS role_rejections(
                    request_id TEXT PRIMARY KEY,question_sha256 TEXT NOT NULL,
                    reason TEXT NOT NULL,created REAL NOT NULL);
                CREATE TRIGGER IF NOT EXISTS role_rejection_frozen BEFORE UPDATE ON role_rejections
                  BEGIN SELECT RAISE(ABORT,'Rejected request intent is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS role_rejection_retained
                  BEFORE DELETE ON role_rejections
                  BEGIN SELECT RAISE(ABORT,'Request recovery history is permanent'); END;
                CREATE TRIGGER IF NOT EXISTS role_answer_frozen BEFORE UPDATE ON role_attempts
                  WHEN OLD.response IS NOT NULL AND NEW.response IS NOT OLD.response
                  BEGIN SELECT RAISE(ABORT,'Completed model answer is immutable'); END;
            """)
        self.history = RoleHistory(registry)

    def _requested(self, question: Question) -> str | None:
        if not question.request_id:
            return None
        sha = fingerprint(question.model_dump(exclude={"request_id"}))
        existing = self.registry.db.execute(
            "SELECT * FROM role_requests WHERE request_id=?", (question.request_id,)
        ).fetchone()
        if existing:
            if existing["question_sha256"] != sha:
                raise ValueError("Question request identity cannot be rewritten")
            return str(existing["task"])
        rejection = self.registry.db.execute(
            "SELECT * FROM role_rejections WHERE request_id=?", (question.request_id,)
        ).fetchone()
        if rejection:
            if rejection["question_sha256"] != sha:
                raise ValueError("Rejected request identity cannot be rewritten")
            raise ValueError(str(rejection["reason"]))
        return None

    def reject(self, question: Question, reason: str) -> dict[str, Any]:
        """Fence a confirmed non-creation against every late copy of the same request."""
        intent = question.model_dump(exclude={"request_id"})
        sha = fingerprint(intent)
        receipt: dict[str, Any] = {
            "request_id": question.request_id,
            "intent": intent,
            "message": reason[:500],
            "outcome": "unknown",
        }
        if not question.request_id:
            return receipt
        with self.registry.transaction():
            existing = self.registry.db.execute(
                "SELECT * FROM role_requests WHERE request_id=?", (question.request_id,)
            ).fetchone()
            if existing:
                return receipt | {
                    "outcome": "created"
                    if existing["question_sha256"] == sha
                    else "intent_conflict",
                    "task": existing["task"],
                }
            self.registry.db.execute(
                "INSERT OR IGNORE INTO role_rejections VALUES(?,?,?,?)",
                (question.request_id, sha, reason[:500], time.time()),
            )
            rejection = self.registry.db.execute(
                "SELECT * FROM role_rejections WHERE request_id=?", (question.request_id,)
            ).fetchone()
            if rejection["question_sha256"] != sha:
                return receipt | {"outcome": "intent_conflict"}
            return receipt | {"outcome": "not_created", "message": rejection["reason"]}

    def enqueue(self, question: Question, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        question_body = question.model_dump(exclude={"request_id"})
        question_sha256 = fingerprint(question_body)
        with self.registry.lock:
            requested = self._requested(question)
        if requested:
            return self.get(requested)
        c = self.controller
        if c is None or not c.paper.state.get("autonomous_lab"):
            raise ValueError("Declare an ordinary paper lab policy before creating role research")
        policy = c.paper.state["autonomous_lab"]["policy"]
        if question.horizon not in policy["holding_horizons"]:
            raise ValueError("Question horizon is outside the active policy")
        base = RuleSpec(holding_horizon=question.horizon)
        catalog: dict[str, Any] = {}
        if question.parent:
            parent = c.paper.state["autonomous_lab"]["trials"].get(question.parent)
            if not parent or parent["status"] != "preserved":
                raise ValueError("A variation needs a preserved supported parent")
            base = RuleSpec.model_validate(parent["contract"]["proposal"]["strategy"])
            if base.holding_horizon != question.horizon:
                raise ValueError("Parent and child require the same frozen horizon")
            for lookback in (base.lookback - 1, base.lookback + 1):
                if 5 <= lookback <= 30:
                    catalog[f"r{len(catalog)}"] = {
                        "kind": "variation",
                        "strategy": base.model_copy(update={"lookback": lookback}).model_dump(),
                        "reference": base.model_dump(),
                        "parent_trial": question.parent,
                        "parent_strategy_sha256": fingerprint(base.model_dump()),
                    }
        else:
            catalog["r0"] = {
                "kind": "replication",
                "strategy": base.model_dump(),
                "reference": base.model_dump(),
                "replication_of": "reviewed-breakout-v1"
                if question.horizon == "short"
                else f"reviewed-breakout-{question.horizon}-v2",
            }
            catalog["r1"] = {
                "kind": "independent",
                "strategy": base.model_copy(update={"family": "range_reversion"}).model_dump(),
                "reference": base.model_dump(),
            }
        issued = c.bundle(now)
        bars = c.paper.lab_history(now, question.horizon)
        frame = c.paper.control_frames().get("BTCUSD")
        book = frame.get("book") if frame else None
        causal_inputs = {
            "tool": "reviewed_rule_inputs",
            "security": "BTCUSD",
            "holding_horizon": question.horizon,
            "source_basis": c.paper.state.get("evidence_kind", "observed_public_market"),
            "closed_bar_count": len(bars),
            "closed_bar_sha256": fingerprint([str(b) for b in bars]),
            "observed_at": now,
            "features": {
                key: rule_feature(
                    bars,
                    now,
                    RuleSpec.model_validate(value["strategy"]),
                    policy["execution_profile"],
                )
                for key, value in catalog.items()
            },
            "executable_book": plain({k: v for k, v in (frame or {}).items() if k != "book"})
            | {
                "bids": [[str(p), str(q)] for p, q in book.bids[:3]] if book else [],
                "asks": [[str(p), str(q)] for p, q in book.asks[:3]] if book else [],
                "update_id": book.update_id if book else None,
            },
            "scope": "Current causal features; no historical fills or profitable backtest inferred",
        }
        context = {
            "contract": VERSION,
            "question": question_body,
            "policy": policy,
            "policy_sha256": fingerprint(policy),
            "catalog": catalog,
            "issued": issued,
            "tool_evidence": causal_inputs,
        }
        identity = (
            "role-"
            + fingerprint(
                {
                    "question": question_body,
                    "policy": policy,
                    "catalog": catalog,
                    "evidence": issued["bundle"]["novelty_sha256"],
                    "source": causal_inputs["closed_bar_sha256"],
                }
            )[:32]
        )
        encoded = json.dumps(context, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Role evidence context exceeds 64 KiB")
        self.history.rollover()
        with self.registry.transaction():
            requested = self._requested(question)
            if requested:
                return self.get(requested)
            if not self.registry.db.execute(
                "SELECT 1 FROM role_tasks WHERE id=?", (identity,)
            ).fetchone():
                if (
                    self.registry.db.execute(
                        "SELECT count(*) FROM role_tasks WHERE archive_reference IS NULL"
                    ).fetchone()[0]
                    >= HOT_TASKS
                ):
                    raise ValueError("Role history continuation awaits verified storage")
                if (
                    self.registry.db.execute(
                        "SELECT count(*) FROM role_tasks WHERE status NOT IN ('done','failed')"
                    ).fetchone()[0]
                    >= 8
                ):
                    raise ValueError(
                        "Eight retained active role questions; wait for a dependency or completion"
                    )
                self.registry.db.execute(
                    "INSERT INTO role_tasks(id,created,updated,stage,status,context,question_text) "
                    "VALUES(?,?,?,'idea','queued',?,?)",
                    (identity, now, now, encoded, question.question),
                )
                self.registry.event(identity, "role_question", {"question": question.question})
            if question.request_id:
                self.registry.db.execute(
                    "INSERT INTO role_requests VALUES(?,?,?)",
                    (question.request_id, question_sha256, identity),
                )
        return self.get(identity)

    def get(self, identity: str) -> dict[str, Any]:
        with (
            self.registry.lock,
            nullcontext() if self.registry.db.in_transaction else self.registry.transaction(),
        ):
            row = self.registry.db.execute(
                "SELECT * FROM role_tasks WHERE id=?", (identity,)
            ).fetchone()
            if not row:
                raise ValueError("Unknown role task")
            attempts = (
                self.registry.db.execute(
                    "SELECT * FROM role_attempts WHERE task=? ORDER BY started,rowid", (identity,)
                ).fetchall()
                if not row["archive_reference"]
                else []
            )
        # A single registry snapshot sees either all hot attempts or the exact
        # cold reference, even when another process archives this task.
        result = self.history.read(row) if row["archive_reference"] else dict(row)
        for key in ("context", "proposal", "evaluation", "result"):
            result[key] = json.loads(result[key]) if result[key] else None
        result.pop("owner", None)
        if "attempts" not in result:
            result["attempts"] = [dict(a) for a in attempts]
        return result

    def page(self, before: float = 0, before_id: str = "", search: str = "") -> dict[str, Any]:
        if not math.isfinite(before) or len(search) > 100:
            raise ValueError("Use a finite history cursor and at most 100 search characters")
        query = (
            "SELECT t.id,t.created,t.updated,t.stage,t.status,t.reason,t.question_text AS question "
        )
        query += "FROM role_tasks t "
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            query += "JOIN role_task_search s ON s.rowid=t.rowid "
            clauses.append("role_task_search MATCH ?")
            params.append('"' + search.strip().replace('"', '""') + '"')
        if before:
            clauses.append("(t.created<? OR (t.created=? AND t.id<?))")
            params.extend([before, before, before_id])
        if clauses:
            query += "WHERE " + " AND ".join(clauses) + " "
        query += "ORDER BY t.created DESC,t.id DESC LIMIT 21"
        with self.registry.lock:
            rows = self.registry.db.execute(query, params).fetchall()
            counts = self.registry.db.execute(
                "SELECT count(*),count(archive_reference),"
                "sum(status NOT IN ('done','failed')) FROM role_tasks"
            ).fetchone()
        return {
            "enabled": self.enabled,
            "contract": VERSION,
            "reason": self.reason
            if not self.enabled
            else "Separate sequential role worker; task receipts show actual progress",
            "tasks": [dict(r) for r in rows[:20]],
            "next_before": rows[19]["created"] if len(rows) > 20 else None,
            "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
            "history": {
                "retained": counts[0],
                "archived": counts[1],
                "active": counts[2] or 0,
                "hot_limit": HOT_TASKS,
            },
            "readiness": self.transport.readiness()
            if self.transport
            else {"qualified": False, "reason": "No qualified local role profile configured"},
        }

    def view(self, identity: str) -> dict[str, Any]:
        task = self.get(identity)
        # Never repeat full candle inputs in a polling response. Exact saved
        # inputs reopen through their existing typed G: detail reference.
        if task["evaluation"] and "inputs" in task["evaluation"]:
            task["evaluation"] = {k: v for k, v in task["evaluation"].items() if k != "inputs"} | {
                "input_count": len(task["evaluation"]["inputs"]),
                "input_sha256": fingerprint(task["evaluation"]["inputs"]),
                "detail_status": "Pending verified archive finalization",
            }
        for attempt in task["attempts"]:
            for key in ("profile", "packet", "response"):
                attempt[key] = json.loads(attempt[key]) if attempt[key] else None
            attempt.pop("packet", None)  # The task exposes its immutable evidence handles.
        if task["result"] and task["result"].get("outcome"):
            outcome = task["result"]["outcome"]["body"]
            with self.registry.transaction():
                self.registry.db.execute(
                    "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,'role task disclosure')",
                    ("role-view:" + task["id"], outcome["window_start"], outcome["available_at"]),
                )
        if len(json.dumps(task).encode()) > 131072:
            raise ValueError(
                "Task detail exceeds its bounded response allowance; exact attempts retained"
            )
        return task

    def retry(self, identity: str) -> dict[str, Any]:
        """One explicit operational retry; never request a preferred verdict."""
        task = self.get(identity)
        if task["stage"] not in {"idea", "review", "followup"} or task["status"] != "failed":
            raise ValueError("Only a failed model transport attempt can be explicitly retried")
        self.history.restore(identity)
        with self.registry.transaction():
            if (
                self.registry.db.execute(
                    "SELECT count(*) FROM role_tasks WHERE status NOT IN ('done','failed')"
                ).fetchone()[0]
                >= 8
            ):
                raise ValueError("Eight active role questions; retry when a slot is available")
            attempt = self.registry.db.execute(
                "SELECT * FROM role_attempts WHERE task=? AND stage=? "
                "ORDER BY attempt DESC LIMIT 1",
                (identity, task["stage"]),
            ).fetchone()
            if not attempt or attempt["response"] is not None or attempt["attempt"] >= 2:
                raise ValueError(
                    "Completed verdicts are retained; no verdict retry or third attempt"
                )
            self.registry.db.execute(
                "UPDATE role_attempts SET status='retry_authorized' "
                "WHERE task=? AND stage=? AND attempt=?",
                (identity, task["stage"], attempt["attempt"]),
            )
            self.registry.db.execute(
                "UPDATE role_tasks SET status='queued',retry_at=0,owner=NULL,lease_until=NULL "
                "WHERE id=?",
                (identity,),
            )
            self.registry.event(
                identity,
                "role_retry_authorized",
                {
                    "stage": task["stage"],
                    "prior_attempt": attempt["attempt"],
                    "separate_allowance_required": True,
                },
            )
        return self.view(identity)

    def _update(
        self, task: dict[str, Any], stage: str, status: str = "queued", **values: Any
    ) -> None:
        with self.registry.transaction():
            assignments = ["stage=?", "status=?", "updated=?", "owner=NULL", "lease_until=NULL"]
            progressed = (
                stage != task["stage"]
                or status != task["status"]
                or any(value != task.get(key) for key, value in values.items() if key != "retry_at")
            )
            params: list[Any] = [stage, status, time.time() if progressed else task["updated"]]
            for key, value in values.items():
                if key not in {"proposal", "evaluation", "result", "reason", "retry_at"}:
                    raise ValueError("Unsupported task effect")
                assignments.append(key + "=?")
                params.append(
                    json.dumps(value, sort_keys=True, allow_nan=False)
                    if key in {"proposal", "evaluation", "result"}
                    else value
                )
            params.append(task["id"])
            self.registry.db.execute(
                "UPDATE role_tasks SET " + ",".join(assignments) + " WHERE id=?", params
            )

    def _current(self, task: dict[str, Any]) -> AutonomousLab:
        c = self.controller
        if c is None:
            raise InputWait("Paper controller unavailable; task retained")
        lab = c.paper.state.get("autonomous_lab")
        if task["stage"] in {"outcome", "followup", "complete"}:
            # Historical results remain researchable after policy/parent changes.
            return c
        if not lab or fingerprint(lab["policy"]) != task["context"]["policy_sha256"]:
            raise ValueError("Paper policy changed after dispatch; create a new scoped task")
        if task["proposal"]:
            finance.validate_parent(c.paper.state, LabProposal.model_validate(task["proposal"]))
        if task["context"]["contract"] != VERSION:
            raise ValueError("Frozen capability contract changed; replan this task")
        return c

    def _packet(self, task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        context = task["context"]
        if task["stage"] == "review":
            return "reviewer", {
                "question": context["question"]["question"],
                "capabilities": {},
                "evidence": {
                    "e0": {"method": task["proposal"], "cost_policy": context["policy"]},
                    "e1": {k: v for k, v in task["evaluation"].items() if k != "inputs"}
                    | {
                        "input_count": task["evaluation"]["input_count"],
                        "input_sha256": task["evaluation"]["input_sha256"],
                    },
                },
            }
        evidence: dict[str, Any] = {"e0": context["issued"]["bundle"]}
        evidence["e2"] = context["tool_evidence"]
        if task["stage"] == "followup":
            # The recorded result is the new information. Keep predecessor links
            # instead of repeating its entire earlier input packet/transcript.
            evidence = {
                "e0": {
                    "predecessor_bundle": context["issued"]["sha256"],
                    "input_sha256": context["tool_evidence"]["closed_bar_sha256"],
                    "basis": "Earlier causal inputs; the new score is training information",
                }
            }
            evidence["e1"] = task["result"]["outcome"]
        capabilities = {
            key: {
                "kind": value["kind"],
                "family": value["strategy"]["family"],
                "holding_horizon": value["strategy"]["holding_horizon"],
                "lookback": value["strategy"]["lookback"],
                "reference_family": value["reference"]["family"],
                "reference_lookback": value["reference"]["lookback"],
                "authority": "Reviewed rules; identical frozen costs/risk, prospective paper only",
            }
            for key, value in context["catalog"].items()
        }
        return "researcher", {
            "question": context["question"]["question"],
            "capabilities": capabilities,
            "evidence": evidence,
        }

    async def _answer(self, task: dict[str, Any]) -> Idea | Review:
        role, packet = self._packet(task)
        with self.registry.lock:
            previous = self.registry.db.execute(
                "SELECT * FROM role_attempts WHERE task=? AND stage=? ORDER BY attempt "
                "DESC LIMIT 1",
                (task["id"], task["stage"]),
            ).fetchone()
        if previous and previous["response"]:
            return validate(role, json.loads(previous["response"])["answer"], packet)
        if previous and previous["status"] != "retry_authorized":
            # An unknown completion is never an invisible retry for a preferred verdict.
            raise ValueError(
                "Previous inference completion unknown; review retained attempt before "
                "explicit retry"
            )
        if not self.enabled or self.transport is None:
            raise InputWait(
                "Role inference disabled; qualified policy and explicit activation required"
            )
        try:
            profile = await asyncio.to_thread(self.transport.admit, role)
        except Exception as exc:
            raise InputWait("Required role is unavailable: " + str(exc)[:300]) from exc
        started = time.time()
        timeout = profile["timeout_seconds"]
        attempt_number = previous["attempt"] + 1 if previous else 1
        with self.registry.transaction():
            used = self.registry.db.execute(
                "SELECT coalesce(sum(wall_reserved),0),coalesce(sum(tokens_reserved),0) "
                "FROM role_attempt_allowances WHERE started>=? AND actor IS NULL",
                (started - 3600,),
            ).fetchone()
            if (
                used[0] + timeout > profile["hourly_wall_seconds"]
                or used[1] + profile["token_allowance"] > profile["hourly_tokens"]
            ):
                raise InputWait(
                    "Separate role inference allowance exhausted; retry after the recorded hour"
                )
            self.registry.db.execute(
                "INSERT INTO "
                "role_attempts(task,stage,attempt,started,status,profile,packet,"
                "wall_reserved,tokens_reserved) VALUES(?,?,?,?,'running',?,?,?,?)",
                (
                    task["id"],
                    task["stage"],
                    attempt_number,
                    started,
                    json.dumps(profile),
                    json.dumps(packet),
                    timeout,
                    profile["token_allowance"],
                ),
            )
            self.registry.db.execute(
                "UPDATE role_tasks SET owner=?,lease_until=?,status='running' WHERE id=?",
                (self.owner, started + timeout + 30, task["id"]),
            )
        try:
            response = await asyncio.to_thread(self.transport.infer, role, packet, profile)
            body = json.dumps(response, sort_keys=True, allow_nan=False)
            if len(body.encode()) > 32768:
                raise ValueError("Model final output exceeds the recorded answer bound")
            # Persist before validation or dispatch. A restart reuses the completed answer.
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE role_attempts SET response=?,finished=?,status='answered', "
                    "wall_reserved=max(wall_reserved,?-started) "
                    "WHERE task=? AND stage=? AND attempt=?",
                    (body, time.time(), time.time(), task["id"], task["stage"], attempt_number),
                )
            return validate(role, response["answer"], packet)
        except Exception as exc:
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE role_attempts SET finished=?,status='failed',reason=?, "
                    "wall_reserved=max(wall_reserved,?-started) WHERE "
                    "task=? AND stage=? AND attempt=?",
                    (
                        time.time(),
                        str(exc)[:500],
                        time.time(),
                        task["id"],
                        task["stage"],
                        attempt_number,
                    ),
                )
            raise

    async def step(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.registry.transaction():
            row = self.registry.db.execute(
                "SELECT id FROM role_tasks WHERE status NOT IN ('done','failed') AND "
                "stage<>'data_wait' "
                "AND retry_at<=? AND (owner IS NULL OR lease_until<?) ORDER BY updated LIMIT 1",
                (now, now),
            ).fetchone()
            if row:
                self.registry.db.execute(
                    "UPDATE role_tasks SET owner=?,lease_until=? WHERE id=?",
                    (self.owner, time.time() + 630, row["id"]),
                )
        if not row:
            return False
        task = self.get(row["id"])
        try:
            c = self._current(task)
            if not c.can_research():
                raise InputWait("Optional role work yields to financial processing/resource guard")
            stage = task["stage"]
            if stage == "data_wait":
                return False  # Only a new eligible source/event resumes this dependency.
            if stage in {"idea", "review", "followup"}:
                answer = await self._answer(task)
                self._current(task)  # Revalidate after long inference against unchanged context.
                if isinstance(answer, Review):
                    if answer.action != "exploratory_paper_only":
                        self._update(
                            task,
                            "complete",
                            "done",
                            result={"review": answer.model_dump()},
                            reason=answer.rationale,
                        )
                    else:
                        self._update(task, "submit", result={"review": answer.model_dump()})
                elif stage == "followup":
                    self._update(
                        task,
                        "complete",
                        "done",
                        result={
                            **task["result"],
                            "followup": answer.model_dump(),
                            "support": "Recorded comparison; annotation grants no new P/L",
                        },
                    )
                elif answer.action != "propose_experiment":
                    self._update(
                        task,
                        "data_wait" if answer.action == "request_data" else "complete",
                        "waiting" if answer.action == "request_data" else "done",
                        result=answer.model_dump(),
                        reason=answer.dependency or answer.rationale,
                    )
                else:
                    capability = task["context"]["catalog"][answer.capability]
                    proposal = LabProposal(
                        request_id="role-proposal-" + task["id"][5:],
                        policy_id=task["context"]["policy"]["request_id"],
                        source="external",
                        mechanism=answer.mechanism,
                        question=answer.falsification,
                        evidence_bundle_sha256=task["context"]["issued"]["sha256"],
                        **capability,
                    )
                    finance.validate_parent(c.paper.state, proposal)
                    self._update(task, "evaluate", proposal=proposal.model_dump())
            elif stage == "evaluate":
                evaluation = await asyncio.to_thread(
                    c.evaluate, LabProposal.model_validate(task["proposal"]), now
                )
                self._update(task, "archive_evaluation", evaluation=evaluation)
            elif stage == "archive_evaluation":
                plan = load_plan(self.registry.path.parent)
                if plan is None:
                    raise InputWait(
                        "Configure existing G: research tiers before saving role input detail"
                    )
                store = ResearchStorage(plan)
                try:
                    packet = {
                        "kind": "role_evaluation",
                        "at": task["evaluation"]["evaluated_at"],
                        "task": task["id"],
                        "evaluation": task["evaluation"],
                        "protected_until": task["evaluation"]["evaluated_at"]
                        + max(
                            task["context"]["policy"]["horizon_seconds"],
                            RuleSpec.model_validate(task["proposal"]["strategy"]).timing["review"],
                        )
                        + 86400,
                    }
                    reference = store.append([packet], time.time())[0]
                    if store.reopen(reference) != packet:
                        raise InputWait("Saved role evidence detail verification failed")
                    compact = {k: v for k, v in task["evaluation"].items() if k != "inputs"}
                    compact.update(
                        input_count=len(task["evaluation"]["inputs"]),
                        input_sha256=fingerprint(task["evaluation"]["inputs"]),
                        detail_reference=reference,
                    )
                    self._update(task, "review", evaluation=compact)
                finally:
                    store.close()
            elif stage == "submit":
                try:
                    existing = c.inbox.get(task["proposal"]["request_id"])
                except ValueError:
                    existing = None
                if existing and fingerprint(existing["body"]) != fingerprint(task["proposal"]):
                    raise ValueError("Proposal acknowledgment identity differs")
                if not existing and not c.inbox.has_capacity():
                    raise InputWait("Ordinary paper inbox is full; retain the approved proposal")
                submitted = existing or c.submit(LabProposal.model_validate(task["proposal"]), now)
                self._update(
                    task,
                    "outcome",
                    result={**task["result"], "proposal_id": submitted["request_id"]},
                )
            elif stage == "outcome":
                submitted = c.inbox.get(task["result"]["proposal_id"])
                if submitted["status"] == "rejected":
                    self._update(task, "complete", "done", reason=submitted["reason"])
                elif submitted["trial_id"]:
                    with reader(c.paper) as view:
                        outcome = view.connection.execute(
                            "SELECT id,at,body FROM paper_events WHERE "
                            "kind='lab_trial_scored' AND body->>'trial_id'=%s AND at<=%s "
                            "ORDER BY id DESC LIMIT 1",
                            (submitted["trial_id"], now),
                        ).fetchone()
                    if outcome and outcome["body"]["available_at"] <= now:
                        with self.registry.transaction():
                            self.registry.db.execute(
                                "INSERT OR IGNORE INTO evidence_windows "
                                "VALUES(?,?,?,'role outcome disclosure')",
                                (
                                    "role-outcome:" + task["id"],
                                    outcome["body"]["window_start"],
                                    outcome["body"]["available_at"],
                                ),
                            )
                        self._update(
                            task,
                            "followup",
                            result={
                                **task["result"],
                                "trial_id": submitted["trial_id"],
                                "outcome": dict(outcome),
                            },
                        )
                    else:
                        self._update(
                            task,
                            "outcome",
                            "waiting",
                            reason="Comparison outcome has not matured",
                            result={**task["result"], "trial_id": submitted["trial_id"]},
                            retry_at=now + 30,
                        )
                else:
                    self._update(
                        task,
                        "outcome",
                        "waiting",
                        reason="Ordinary paper inbox awaits capacity or funding",
                        retry_at=now + 30,
                    )
            return True
        except InputWait as exc:
            self._update(task, task["stage"], "waiting", reason=str(exc), retry_at=now + 30)
            return False
        except Exception as exc:
            self._update(task, task["stage"], "failed", reason=str(exc)[:500])
            return False

    async def run(self) -> None:
        while True:
            if self.activation is not None:
                try:
                    self.enabled = await asyncio.to_thread(self.activation)
                except (ValueError, OSError, KeyError):
                    self.enabled = False
            if self.enabled:
                await self.step()
            await asyncio.sleep(1)
