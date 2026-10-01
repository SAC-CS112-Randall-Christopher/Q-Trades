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
from trading.autonomous_spec import LabProposal, MemoryFilter, RuleSpec
from trading.evidence_runtime import plain
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.lab_role_contract import VERSION, Idea, Review, validate
from trading.research_lessons import ResearchLessons
from trading.research_storage import ResearchStorage, load_plan
from trading.role_evidence import (
    artifact_summary,
    bundle_summary,
    feature_set,
    feature_summary,
    method_summary,
    outcome_summary,
)
from trading.role_history import HOT_TASKS, RoleHistory
from trading.rule_components import reviewed_feature
from trading.scoped_tools import reader


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=12, max_length=500)
    horizon: Literal["short", "medium", "long"] = "short"
    parent: str | None = Field(default=None, max_length=100)
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")
    lesson: str | None = Field(default=None, pattern=r"^lesson-[a-f0-9]{32}$")


class RoleWorker:
    def __init__(
        self, registry: ExperimentRegistry, controller: AutonomousLab | None, transport: Any = None
    ):
        self.registry, self.controller, self.transport = registry, controller, transport
        self.lessons = ResearchLessons(registry)
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
                CREATE TABLE IF NOT EXISTS role_components(
                    sha256 TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS role_component_frozen BEFORE UPDATE ON role_components
                  BEGIN SELECT RAISE(ABORT,'Role component is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS role_component_retained
                  BEFORE DELETE ON role_components
                  BEGIN SELECT RAISE(ABORT,'Role component is permanent'); END;
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

    def enqueue(
        self,
        question: Question,
        now: float | None = None,
        *,
        _resume_from: dict[str, Any] | None = None,
        _dependency_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
        if question.parent and question.horizon == "short" and base.entry_filter is None:
            with self.registry.lock:
                fitted = self.registry.db.execute(
                    "SELECT result,plan FROM experiments WHERE status='completed' AND "
                    "json_extract(plan,'$.experiment_mode')='memory_entry' "
                    "ORDER BY seq DESC LIMIT 4"
                ).fetchall()
            for fitted_row in fitted:
                for arm in json.loads(fitted_row["result"])["candidate_group"]:
                    artifact = arm.get("artifact")
                    if (
                        not artifact
                        or max(artifact["train_end"], artifact["calibration_end"]) >= now
                    ):
                        continue
                    synthetic = "synthetic" in c.paper.state.get("evidence_kind", "")
                    if (artifact["evidence_kind"] == "synthetic_qa") != synthetic:
                        continue
                    # Require explicit component pricing in the frozen experiment plan.
                    fitted_plan = json.loads(fitted_row["plan"])
                    numerical_cost = fitted_plan.get("numerical_daily_usd")
                    context_cost = fitted_plan.get("contextual_daily_usd")
                    if numerical_cost is None or arm["arm"] == "C" and context_cost is None:
                        continue
                    from decimal import Decimal

                    cost = str(
                        Decimal(numerical_cost)
                        + (Decimal(context_cost) if arm["arm"] == "C" else Decimal(0))
                    )
                    component = MemoryFilter(artifact=artifact, marginal_daily_usd=cost)
                    strategy = RuleSpec.model_validate(
                        base.model_dump()
                        | {
                            "version": "reviewed-lab-rules-v3",
                            "entry_filter": component.model_dump(),
                        }
                    )
                    catalog["r2"] = {
                        "kind": "variation",
                        "strategy": strategy.model_dump(),
                        "reference": base.model_dump(),
                        "parent_trial": question.parent,
                        "parent_strategy_sha256": fingerprint(base.model_dump()),
                    }
                    break
                if "r2" in catalog:
                    break
        issued = c.bundle(now)
        prior = self.lessons.get(question.lesson) if question.lesson else None
        if prior:
            if prior["context"]["horizon"] != question.horizon:
                raise ValueError("Lesson and new comparison require the same declared horizon")
            catalog = {
                k: v
                for k, v in catalog.items()
                if fingerprint(v["strategy"])
                != prior["context"].get(
                    "strategy_sha256", fingerprint(prior["context"]["strategy"])
                )
            }
            if not catalog:
                raise ValueError("No supported different capability; wait for new evidence")
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
                key: reviewed_feature(
                    bars,
                    now,
                    RuleSpec.model_validate(value["strategy"]),
                    policy["execution_profile"],
                    c.paper.memory_book("BTCUSD"),
                )
                for key, value in catalog.items()
            },
            "executable_book": plain({k: v for k, v in (frame or {}).items() if k != "book"})
            | {
                "bids": [[str(p), str(q)] for p, q in book.bids[:3]] if book else [],
                "asks": [[str(p), str(q)] for p, q in book.asks[:3]] if book else [],
                "update_id": book.update_id if book else None,
            },
            "scope": "Current causal features; historical fills/returns unavailable",
        }
        waits: dict[str, Any] = {
            "new_closed_bars": {
                "kind": "closed_bars",
                "horizon": question.horizon,
                "source_sha256": causal_inputs["closed_bar_sha256"],
                "last_closed_at": max((b.close_ms / 1000 for b in bars), default=0),
            }
        }
        pending = sorted(
            (
                t
                for t in c.paper.state["autonomous_lab"]["trials"].values()
                if t["status"] in {"active", "draining"}
                and t["contract"]["proposal"]["strategy"]["holding_horizon"] == question.horizon
            ),
            key=lambda t: (t["started_at"], t["id"]),
        )
        if pending:
            waits["mature_outcome"] = {
                "kind": "mature_outcome",
                "trial_id": pending[0]["id"],
                "eligible_at": pending[0]["review_at"],
                "other_pending_comparisons": len(pending) - 1,
            }
        artifacts: dict[str, Any] = {}
        for value in catalog.values():
            for key in ("strategy", "reference"):
                value[key + "_sha256"] = fingerprint(value[key])
                component = value[key].get("entry_filter")
                if component:
                    artifact = component["artifact"]
                    artifacts[artifact["sha256"]] = artifact
                    value[key] = value[key] | {
                        "entry_filter": component
                        | {"artifact": artifact_summary(artifact) | {"retained": True}}
                    }
        context = {
            "contract": VERSION,
            "question": question_body,
            "policy": policy,
            "policy_sha256": fingerprint(policy),
            "catalog": catalog,
            "issued": issued,
            "tool_evidence": causal_inputs,
            "lesson": prior,
            "wait_requirements": waits,
            "predecessor_task": _resume_from["id"] if _resume_from else None,
            "dependency_evidence": _dependency_evidence,
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
                    "waits": waits,
                    "dependency_evidence": _dependency_evidence,
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
            for sha256, artifact in artifacts.items():
                self.registry.db.execute(
                    "INSERT OR IGNORE INTO role_components VALUES(?,?)",
                    (sha256, json.dumps(artifact, sort_keys=True, allow_nan=False)),
                )
            if _resume_from:
                if identity == _resume_from["id"]:
                    raise ValueError("Unchanged evidence cannot resume the same question")
                changed = self.registry.db.execute(
                    "UPDATE role_tasks SET stage='complete',status='done',updated=?,reason=? "
                    "WHERE id=? AND stage='data_wait' AND status='waiting' AND owner IS NULL "
                    "AND context=?",
                    (
                        now,
                        "Eligible dependency resumes as " + identity,
                        _resume_from["id"],
                        json.dumps(_resume_from["context"], sort_keys=True, allow_nan=False),
                    ),
                ).rowcount
                if not changed:
                    raise ValueError("Waiting predecessor already resumed or ownership changed")
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
            if _resume_from:
                self.registry.event(
                    _resume_from["id"],
                    "role_dependency_resumed",
                    {
                        "successor": identity,
                        "requirement": (_resume_from["result"] or {}).get("wait_requirement"),
                    },
                )
            if _dependency_evidence:
                outcome = _dependency_evidence["body"]
                self.registry.db.execute(
                    "INSERT OR IGNORE INTO evidence_windows "
                    "VALUES(?,?,?,'role dependency disclosure')",
                    (
                        "role-dependency:" + identity,
                        outcome["window_start"],
                        outcome["available_at"],
                    ),
                )
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
                    "e0": {
                        "method": method_summary(task["proposal"]),
                        "cost_policy": context["policy"],
                    },
                    "e1": {k: v for k, v in task["evaluation"].items() if k != "inputs"}
                    | {
                        "input_count": task["evaluation"]["input_count"],
                        "input_sha256": task["evaluation"]["input_sha256"],
                        "feature": feature_summary(task["evaluation"]["feature"]),
                    },
                },
            }
        evidence: dict[str, Any] = {"e0": bundle_summary(context["issued"]["bundle"])}
        evidence["e2"] = context["tool_evidence"] | {
            "features": feature_set(context["tool_evidence"]["features"]),
            "executable_book": {
                k: context["tool_evidence"]["executable_book"][k]
                for k in ("observed_at", "at", "bids", "asks", "update_id")
                if k in context["tool_evidence"]["executable_book"]
            },
        }
        evidence["e2"] = evidence["e2"] | {
            "request_data_conditions": {
                key: {
                    "kind": value["kind"],
                    "condition": (
                        "A later closed bar from the same horizon"
                        if value["kind"] == "closed_bars"
                        else "The sole writer records this mature outcome"
                    ),
                }
                for key, value in context.get("wait_requirements", {}).items()
            },
            "wait_selection": (
                "For automatic resumption, dependency must equal one offered condition key"
            ),
        }
        if context.get("dependency_evidence"):
            evidence["e4"] = outcome_summary(context["dependency_evidence"])
        if context.get("lesson"):
            prior = context["lesson"]
            evidence["e3"] = {
                k: prior[k]
                for k in (
                    "id",
                    "claim",
                    "source_sha256",
                    "supporting_facts",
                    "unknowns",
                    "next_test",
                )
            }
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
            evidence["e1"] = outcome_summary(task["result"]["outcome"])
        capabilities = {
            key: {
                "kind": value["kind"],
                "family": value["strategy"]["family"],
                "lookback": value["strategy"]["lookback"],
                "reference_family": value["reference"]["family"],
                "reference_lookback": value["reference"]["lookback"],
            }
            | (
                {"component": value["strategy"]["entry_filter"]}
                if value["strategy"].get("entry_filter")
                else {}
            )
            for key, value in context["catalog"].items()
        }
        return "researcher", {
            "question": context["question"]["question"],
            "capabilities": capabilities,
            "scope": "Prospective paper; same declared horizon, frozen costs/risk",
            "evidence": evidence,
        }

    def _capability(self, value: dict[str, Any]) -> dict[str, Any]:
        """Resolve the frozen full numerical method; model summaries grant no authority."""
        result = {
            k: v for k, v in value.items() if k not in {"strategy_sha256", "reference_sha256"}
        }
        for key in ("strategy", "reference"):
            strategy = result[key]
            component = strategy.get("entry_filter")
            if component and component["artifact"].get("retained"):
                with self.registry.lock:
                    row = self.registry.db.execute(
                        "SELECT body FROM role_components WHERE sha256=?",
                        (component["artifact"]["sha256"],),
                    ).fetchone()
                if not row:
                    raise InputWait("Retained component unavailable; frozen method not substituted")
                strategy = strategy | {"entry_filter": component | {"artifact": json.loads(row[0])}}
            if key + "_sha256" in value and fingerprint(strategy) != value[key + "_sha256"]:
                raise ValueError("Frozen numerical method reference mismatch")
            result[key] = RuleSpec.model_validate(strategy).model_dump()
        return result

    def component_detail(self, identity: str, capability: str, offset: int = 0) -> dict[str, Any]:
        task = self.get(identity)
        value = task["context"]["catalog"].get(capability)
        if not value or not value["strategy"].get("entry_filter") or not 0 <= offset <= 128:
            raise ValueError("No such frozen component page in the selected task")
        artifact = self._capability(value)["strategy"]["entry_filter"]["artifact"]
        result = {
            "capability": capability,
            "artifact_sha256": artifact["sha256"],
            "artifact_metadata": {k: v for k, v in artifact.items() if k != "library"},
            "library_count": len(artifact["library"]),
            "offset": offset,
            "library": artifact["library"][offset : offset + 8],
            "next_offset": offset + 8 if offset + 8 < len(artifact["library"]) else None,
            "scope": "Eight retained training rows per page; no prospective result inferred",
        }
        if len(json.dumps(result).encode()) > 131072:
            raise ValueError("Component page exceeds response allowance; exact artifact retained")
        with self.registry.transaction():
            self.registry.db.execute(
                "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,'role component disclosure')",
                (
                    "role-component:" + artifact["sha256"],
                    min(row["at"] for row in artifact["library"]) - 600,
                    max(artifact["train_end"], artifact["calibration_end"]),
                ),
            )
        return result

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
                    self.lessons.record(self.get(task["id"]))
                elif answer.action != "propose_experiment":
                    self._update(
                        task,
                        "data_wait" if answer.action == "request_data" else "complete",
                        "waiting" if answer.action == "request_data" else "done",
                        result=answer.model_dump()
                        | {
                            "wait_requirement": task["context"]
                            .get("wait_requirements", {})
                            .get(answer.dependency)
                            if answer.action == "request_data"
                            else None,
                        },
                        reason=answer.dependency or answer.rationale,
                    )
                else:
                    capability = self._capability(task["context"]["catalog"][answer.capability])
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
        except OSError as exc:
            if task["stage"] == "archive_evaluation":
                self._update(
                    task, task["stage"], "waiting", reason=str(exc)[:500], retry_at=now + 30
                )
            else:
                self._update(task, task["stage"], "failed", reason=str(exc)[:500])
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
                await asyncio.to_thread(self.resume_sources)
                await asyncio.to_thread(self.select_followups)
                await self.step()
            await asyncio.sleep(1)

    def select_followups(self) -> dict[str, int]:
        """Bounded completed-comparison trigger; unchanged/replayed results coalesce.

        Required qualification gates remain at dispatch. This selector never
        changes the numerical learner, financial allocation or family quotas.
        """
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT id FROM role_tasks WHERE stage='complete' AND "
                "json_extract(result,'$.outcome') IS NOT NULL AND NOT EXISTS "
                "(SELECT 1 FROM research_selection s JOIN research_lessons l ON l.id=s.lesson "
                "WHERE l.task=role_tasks.id AND (s.state IN ('selected','waiting') "
                "OR s.retry_at>?)) ORDER BY updated,id LIMIT 20",
                (time.time(),),
            ).fetchall()
        selected = waiting = 0
        for row in rows:
            task = self.get(row["id"])
            identity = self.lessons.record(task)
            followup = task["result"].get("followup", {})
            choice = task["context"]["catalog"].get(followup.get("capability"))
            if (
                followup.get("action") != "propose_experiment"
                or not choice
                or choice["strategy"] == task["proposal"]["strategy"]
            ):
                self.lessons.selected(
                    identity,
                    "waiting",
                    followup.get("dependency")
                    or "No supported different test; wait for new mature/source evidence",
                )
                waiting += 1
                continue
            try:
                next_task = self.enqueue(
                    Question(
                        question=followup["falsification"],
                        horizon=task["context"]["question"]["horizon"],
                        parent=task["context"]["question"]["parent"],
                        request_id="next-" + identity[7:],
                        lesson=identity,
                    )
                )
                # Reconciliation after a lost acknowledgment returns the exact same task.
                self.lessons.selected(
                    identity,
                    "selected",
                    "New mature comparison and supported different capability",
                    next_task["id"],
                )
                selected += 1
            except (ValueError, OSError) as exc:
                self.lessons.selected(identity, "deferred", str(exc)[:500])
        return {"selected": selected, "waiting": waiting}

    def resume_sources(self, now: float | None = None) -> int:
        """Exchange one waiting slot atomically, using its frozen typed dependency."""
        if self.controller is None:
            return 0
        now = time.time() if now is None else now
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT id FROM role_tasks WHERE stage='data_wait' AND status='waiting' "
                "ORDER BY updated,id LIMIT 20"
            ).fetchall()
        resumed = 0
        for row in rows:
            task = self.get(row["id"])
            question = Question.model_validate(task["context"]["question"])
            requirement = (task["result"] or {}).get("wait_requirement")
            if not requirement:
                continue  # Historical free text is retained; no guessed dependency/maturity.
            outcome = None
            if requirement["kind"] == "closed_bars":
                bars = self.controller.paper.lab_history(now, requirement["horizon"])
                if (
                    fingerprint([str(b) for b in bars]) == requirement["source_sha256"]
                    or max((b.close_ms / 1000 for b in bars), default=0)
                    <= requirement["last_closed_at"]
                ):
                    continue
            elif requirement["kind"] == "mature_outcome":
                with reader(self.controller.paper) as view:
                    outcome = view.connection.execute(
                        "SELECT id,at,body FROM paper_events WHERE kind='lab_trial_scored' "
                        "AND body->>'trial_id'=%s AND at<=%s ORDER BY id DESC LIMIT 1",
                        (requirement["trial_id"], now),
                    ).fetchone()
                if not outcome or outcome["body"]["available_at"] > now:
                    continue
            else:
                continue
            try:
                self.enqueue(
                    question.model_copy(update={"request_id": None}),
                    now,
                    _resume_from=task,
                    _dependency_evidence=dict(outcome) if outcome else None,
                )
            except ValueError:
                continue
            resumed += 1
        return resumed

    def selection_metrics(self) -> dict[str, Any]:
        with self.registry.lock:
            selections = {
                r["state"]: r["n"]
                for r in self.registry.db.execute(
                    "SELECT state,count(*) AS n FROM research_selection GROUP BY state"
                )
            }
            totals = self.registry.db.execute(
                "SELECT count(*),coalesce(sum(wall_reserved),0),coalesce(sum(tokens_reserved),0) "
                "FROM role_attempts"
            ).fetchone()
            completed = self.registry.db.execute(
                "SELECT count(*) FROM role_tasks WHERE status='done'"
            ).fetchone()[0]
        return {
            "selection": selections,
            "completed_questions": completed,
            "attempts": totals[0],
            "reserved_wall_seconds": totals[1],
            "reserved_token_allowance": totals[2],
            "paid_usd": "0",
            "actual_model_tokens": None,
            "limits": "Allowance is conservative reservation, not measured model tokens or benefit",
        }
