"""Optional sequential local roles in the existing registry, outside financial locks."""

import asyncio
import copy
import json
import math
import secrets
import sqlite3
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from trading import autonomous_finance as finance
from trading.autonomous_lab import AutonomousLab, InputWait
from trading.autonomous_spec import LabPolicy, LabProposal, MemoryFilter, RuleSpec, contract
from trading.evidence_runtime import plain
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.finite_role_test import AUTHORITY_FIELDS, FiniteRoleTest, active, finite_scope
from trading.lab_role_contract import (
    CAPABILITY_VERSION,
    PATTERN_METHOD_QUESTION_POLICY,
    PATTERN_METHODS,
    PATTERN_VERSION,
    TOOL_REQUEST_VERSION,
    VERSION,
    Idea,
    IdeaV6,
    Review,
    pattern_method_policy_sha,
    validate,
)
from trading.local_role_model import LocalRoles
from trading.paper_engine import fresh_frame
from trading.pattern_comparisons import (
    TRAINING_ORIGINS,
    PatternComparisonCommand,
    PatternComparisons,
    PatternFindingSelection,
)
from trading.peft_role_model import PATTERN_LEARNING_QUESTION_POLICY, DevelopmentTransportFailure
from trading.research_knowledge import KnowledgeQuery, ResearchKnowledge

if TYPE_CHECKING:
    from trading.research_reviews import ResearchReviews
from trading.research_evidence import digest
from trading.research_lessons import ResearchLessons
from trading.research_storage import ResearchStorage, StoragePlan
from trading.role_evidence import (
    artifact_summary,
    bundle_summary,
    feature_set,
    feature_summary,
    method_summary,
    outcome_summary,
    pattern_controls,
    pattern_feature,
    pattern_followup_controls,
    pattern_followup_outcome,
    pattern_packet,
    pattern_summary,
)
from trading.role_history import HOT_TASKS, HistoryUnavailable, RoleHistory
from trading.rule_components import reviewed_feature
from trading.scoped_tools import reader

RETRIEVAL_CONTRACT = "source-rag-v1"
PAPER_RESEARCH_PILOT = "paper_research_pilot"
QUESTION_POLICY = "evidence-question-selection-v1"
PATTERN_QUESTION_POLICY = "pattern-question-selection-v1"


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=12, max_length=500)
    horizon: Literal["short", "medium", "long"] = "short"
    parent: str | None = Field(default=None, max_length=100)
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")
    lesson: str | None = Field(default=None, pattern=r"^lesson-[a-f0-9]{32}$")


class RoleWorker:
    def __init__(
        self,
        registry: ExperimentRegistry,
        controller: AutonomousLab | None,
        transport: Any = None,
        storage_owner: Callable[[StoragePlan], AbstractContextManager[ResearchStorage]]
        | None = None,
        *,
        pattern_comparisons: PatternComparisons | None = None,
    ):
        self.registry, self.controller, self.transport = registry, controller, transport
        if pattern_comparisons is not None and pattern_comparisons.registry is not registry:
            raise ValueError("Pattern research must use the existing shared registry")
        self.pattern_comparisons = pattern_comparisons
        self.lessons = ResearchLessons(registry)
        self.knowledge: ResearchKnowledge | None = None
        self.reviews: ResearchReviews | None = None
        self.owner = secrets.token_hex(16)
        self.enabled = False  # Explicit activation belongs to the selected transport policy.
        self.activation: Callable[[], bool] | None = None
        self.paper_admission: Callable[[], bool] | None = None
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
                CREATE INDEX IF NOT EXISTS role_pending_work ON role_tasks(stage,status)
                  WHERE status NOT IN ('done','failed');
                CREATE TABLE IF NOT EXISTS role_question_selections(
                    selection_sha TEXT PRIMARY KEY,scope_sha TEXT NOT NULL,horizon TEXT NOT NULL,
                    source_end REAL NOT NULL,created REAL NOT NULL,task TEXT UNIQUE NOT NULL,
                    body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS role_question_scope
                  ON role_question_selections(scope_sha,horizon,source_end DESC);
                CREATE INDEX IF NOT EXISTS role_question_rate ON role_question_selections(created);
                CREATE TRIGGER IF NOT EXISTS role_question_selection_frozen
                  BEFORE UPDATE ON role_question_selections
                  BEGIN SELECT RAISE(ABORT,'Question selection is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS role_question_selection_retained
                  BEFORE DELETE ON role_question_selections
                  BEGIN SELECT RAISE(ABORT,'Question selection is permanent'); END;
            """)
        self.history = RoleHistory(registry, storage_owner)
        self.finite = FiniteRoleTest(registry)
        if callable(getattr(transport, "finite_test", None)):
            transport.finite_request_verifier = self.validate_finite_request
            if controller is not None:
                controller.finite_transport = transport
                controller.inbox.finite_validator = self.validate_finite_proposal
        self._maintenance_due: dict[str, float] = {}
        with registry.transaction():
            registry.db.execute(
                "CREATE TABLE IF NOT EXISTS role_supervision(phase TEXT PRIMARY KEY,"
                "status TEXT NOT NULL,reason TEXT,retry_at REAL NOT NULL,updated REAL NOT NULL)"
            )
            columns = {r[1] for r in registry.db.execute("PRAGMA table_info(role_supervision)")}
            if "scope_sha" not in columns:
                registry.db.execute("ALTER TABLE role_supervision ADD COLUMN scope_sha TEXT")

    @property
    def paper_pilot(self) -> bool:
        return getattr(self.transport, "paper_pilot", False) is True

    @property
    def execution_mode(self) -> str:
        return PAPER_RESEARCH_PILOT if self.paper_pilot else "qualified_roles"

    def _contract_version(self) -> str:
        version = getattr(self.transport, "role_contract", VERSION)
        if version not in (VERSION, TOOL_REQUEST_VERSION, CAPABILITY_VERSION, PATTERN_VERSION):
            raise ValueError("Role contract needs an explicitly reviewed supported profile")
        return str(version)

    def _same_mode(self, task: dict[str, Any]) -> bool:
        try:
            finite = self._finite_scope()
            if finite is not None or "finite_test" in task["context"]:
                if finite is None:
                    return False
                with self.registry.lock:
                    saved = self.finite.binding(task)
                if saved != {**finite, "root_task": saved["root_task"]}:
                    return False
                active(finite, time.time())
        except (ValueError, OSError, KeyError):
            return False
        if task["context"].get("execution_mode", "qualified_roles") != self.execution_mode:
            return False
        if task["context"].get("contract", VERSION) != self._contract_version():
            return False
        if "selection_authority" in task["context"]:
            try:
                if (
                    not isinstance(task["context"]["selection_authority"], dict)
                    or task["context"]["selection_authority"] != self._selection_authority()
                ):
                    return False
            except (ValueError, OSError, KeyError):
                return False
        if self.paper_pilot:
            try:
                return bool(task["context"].get("pilot_grant_id") == self._pilot_grant_id())
            except (ValueError, OSError, KeyError):
                return False
        return True

    def _pilot_grant_id(self) -> str | None:
        if not self.paper_pilot:
            return None
        try:
            identity = self.transport.policy()["grant_id"]
            if not isinstance(identity, str) or not 8 <= len(identity) <= 64:
                raise ValueError("Pilot task needs the current explicit grant identity")
        except (ValueError, OSError, KeyError) as exc:
            raise InputWait(
                "Current pilot grant unavailable; retained tasks are unchanged"
            ) from exc
        return identity

    def _admitted(self) -> bool:
        if self.paper_pilot:
            return bool(self.paper_admission and self.paper_admission())
        return bool(self.controller and self.controller.can_research())

    def _activation_enabled(self) -> bool:
        if self.paper_pilot and self.activation is not None:
            try:
                return bool(self.activation())
            except (ValueError, OSError, KeyError):
                return False
        return self.enabled

    def _finite_scope(self) -> dict[str, Any] | None:
        getter = getattr(self.transport, "finite_test", None)
        value = getter() if self.paper_pilot and callable(getter) else None
        return finite_scope(value) if value is not None else None

    def _finite_current(self, task: dict[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            scope = self._finite_scope()
            if scope is None:
                if task is not None and "finite_test" in task["context"]:
                    raise InputWait("Original finite grant is unavailable; no new effect")
                return None
            active(scope, time.time())
            if task is not None:
                with self.registry.lock:
                    saved = self.finite.binding(task)
                if saved != {**scope, "root_task": saved["root_task"]}:
                    raise ValueError("Current finite grant differs from the original task scope")
            return scope
        except ValueError as exc:
            raise InputWait(str(exc)) from exc

    def _finite_admission(self, scope: dict[str, Any]) -> Callable[[], dict[str, Any]]:
        """Bind out-of-lock preparation to the captured full finite authority."""

        def admitted() -> dict[str, Any]:
            current = self._finite_current()
            if current is None or current != scope:
                raise InputWait("Finite preparation authority changed after capture")
            return current

        return admitted

    def finite_proposal(self, task: dict[str, Any], proposal: LabProposal) -> dict[str, Any] | None:
        scope = self._finite_current(task)
        if scope is None:
            return None
        if self.controller is not None:
            self.controller.finite_transport = self.transport
            self.controller.inbox.finite_validator = self.validate_finite_proposal
        return self._finite_proposal_fence(task, proposal)

    def _finite_proposal_fence(self, task: dict[str, Any], proposal: LabProposal) -> dict[str, Any]:
        with self.registry.lock:
            saved = self.finite.binding(task)
        if task["proposal"] != proposal.model_dump() or set(task["context"]["catalog"]) != {"p0"}:
            raise ValueError("Finite proposal must be the original fixed comparison")
        return {
            **{key: saved[key] for key in AUTHORITY_FIELDS},
            "finite_test_sha": fingerprint(saved["finite_test"]),
            "not_before": saved["finite_test"]["not_before"],
            "expires_at": saved["finite_test"]["expires_at"],
            "root_task": saved["root_task"],
            "task": task["id"],
            "proposal_id": proposal.request_id,
            "proposal_sha": fingerprint(proposal.model_dump()),
        }

    def _finite_accepted(self, task: dict[str, Any]) -> bool:
        if "finite_test" not in task["context"] or not task.get("proposal"):
            return False
        c = self.controller
        if c is None:
            return False
        proposal = LabProposal.model_validate(task["proposal"])
        fence = c.inbox.finite_scope(proposal)
        if fence is None:
            return False
        if fence != self._finite_proposal_fence(task, proposal):
            raise ValueError("Accepted finite proposal differs from its original root/task fence")
        return True

    def validate_finite_request(
        self,
        role: str,
        packet: dict[str, Any],
        profile: dict[str, Any],
        reservation: dict[str, Any],
        *,
        claim: bool = False,
    ) -> None:
        """Verify/claim the existing attempt once; no transport-side request counter."""
        if (
            set(reservation)
            != {
                "grant_id",
                "grant_sha",
                "root_task",
                "task",
                "stage",
                "attempt",
                "packet_sha256",
                "expires_at",
                "finite_test_sha",
            }
            or type(reservation["attempt"]) is not int
        ):
            raise ValueError("Finite dispatch requires its exact reserved attempt")
        scope = self._finite_current()
        if scope is None:
            raise ValueError("Finite dispatch requires the current finite grant")
        with self.registry.transaction():
            row = self.registry.db.execute(
                "SELECT * FROM role_tasks WHERE id=? AND owner=? AND lease_until>=?",
                (reservation["task"], self.owner, time.time()),
            ).fetchone()
            if row is None:
                raise ValueError("Finite dispatch ownership expired or changed")
            task = {"id": row["id"], "context": json.loads(row["context"])}
            saved = self.finite.binding(task)
            expected = self._finite_reservation(
                saved, row["id"], row["stage"], reservation["attempt"], packet
            )
            attempt = self.registry.db.execute(
                "SELECT * FROM role_attempts WHERE task=? AND stage=? AND attempt=?",
                (row["id"], row["stage"], reservation["attempt"]),
            ).fetchone()
            if (
                scope != {k: saved[k] for k in scope}
                or expected != reservation
                or role != ("reviewer" if row["stage"] == "review" else "researcher")
                or attempt is None
                or attempt["status"] != "running"
                or attempt["finished"] is not None
                or attempt["response"] is not None
                or fingerprint(json.loads(attempt["packet"])) != fingerprint(packet)
                or fingerprint(json.loads(attempt["profile"])) != fingerprint(profile)
                or self.finite.count(saved) > saved["finite_test"]["max_requests"]
            ):
                raise ValueError("Finite dispatch differs from its charged immutable reservation")
            active(scope, time.time())
            if (
                claim
                and self.registry.db.execute(
                    "UPDATE role_attempts SET dispatch_started=? WHERE task=? AND stage=? "
                    "AND attempt=? AND dispatch_started IS NULL",
                    (time.time(), row["id"], row["stage"], reservation["attempt"]),
                ).rowcount
                != 1
            ):
                raise ValueError("Finite attempt was already dispatched; no repeat")

    def validate_finite_proposal(self, fence: dict[str, Any], proposal: LabProposal) -> None:
        """Called in the inbox publication transaction; never acquires financial ownership."""
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT context,proposal FROM role_tasks WHERE id=?", (fence.get("task"),)
            ).fetchone()
            if row is None:
                raise ValueError("Finite proposal has no original scoped role task")
            expected = self.finite_proposal(
                {
                    "id": fence["task"],
                    "context": json.loads(row["context"]),
                    "proposal": json.loads(row["proposal"]) if row["proposal"] else None,
                },
                proposal,
            )
            if expected is None or expected != fence:
                raise ValueError("Finite proposal differs from its original task/root authority")

    @staticmethod
    def _finite_reservation(
        saved: dict[str, Any], task: str, stage: str, attempt: int, packet: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "grant_id": saved["grant_id"],
            "grant_sha": saved["grant_sha"],
            "root_task": saved["root_task"],
            "task": task,
            "stage": stage,
            "attempt": attempt,
            "packet_sha256": fingerprint(packet),
            "expires_at": saved["finite_test"]["expires_at"],
            "finite_test_sha": fingerprint(saved["finite_test"]),
        }

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

    def _pattern_original(
        self, source: dict[str, str], *, research_only: bool = False, method_id: str = "p0"
    ) -> dict[str, Any]:
        bridge = self.pattern_comparisons
        if bridge is None:
            raise InputWait("Saved pattern comparison owner is unavailable")
        if set(source) != {"request_id", "finding_sha256", "issued_bundle_sha256"}:
            raise ValueError("Pattern source requires its exact immutable preparation identities")
        original = bridge.get(source["request_id"])
        if original is None:
            raise InputWait("Original pattern preparation is unavailable; no replacement inferred")
        if any(original[key] != source[key] for key in ("finding_sha256", "issued_bundle_sha256")):
            raise ValueError("Pattern preparation identity differs")
        if (
            original["status"]
            not in {
                "waiting",
                "research_only" if research_only else "supported",
            }
            or bool(original.get("research_only")) != research_only
        ):
            raise InputWait("Original pattern preparation has a different research mode")
        described = bridge.describe(
            PatternFindingSelection.model_validate(original["finding"]["selection"]),
            research_only=research_only,
            method_id=method_id,
        )
        if described["finding_sha256"] != original["finding_sha256"] or (
            described["mapping"] != original["mapping"]
        ):
            raise ValueError("Original native proof or fixed comparison implementation changed")
        return original

    @staticmethod
    def _pattern_method_identity(method_id: Any) -> dict[str, Any]:
        if not isinstance(method_id, str) or method_id not in PATTERN_METHODS:
            raise InputWait("Captured pattern method is unavailable")
        candidate, reference = PATTERN_METHODS[method_id]
        return {
            "method_id": method_id,
            "method_policy_sha256": pattern_method_policy_sha(),
            "candidate": candidate,
            "reference": reference,
            "strategy_sha256": fingerprint(
                RuleSpec.model_validate(
                    {
                        "version": "reviewed-lab-rules-v4",
                        "family": candidate,
                        "holding_horizon": "medium",
                    }
                ).model_dump()
            ),
            "reference_sha256": fingerprint(
                RuleSpec.model_validate(
                    {
                        "version": "reviewed-lab-rules-v4",
                        "family": reference,
                        "holding_horizon": "medium",
                    }
                ).model_dump()
            ),
        }

    def _pattern_task_method(self, task: dict[str, Any]) -> str:
        context = task["context"]
        if context.get("selection_authority", {}).get("question_policy") != (
            PATTERN_METHOD_QUESTION_POLICY
        ):
            return "p0"
        method = context.get("pattern_method")
        if not isinstance(method, dict) or method != self._pattern_method_identity(
            method.get("method_id")
        ):
            raise InputWait("Captured pattern method policy changed")
        return str(method["method_id"])

    def _pattern_method_used(self) -> dict[str, bool]:
        if self.controller is None:
            raise InputWait("Pattern method inbox is unavailable")
        return {
            key: self.controller.inbox.used(self._pattern_method_identity(key)["strategy_sha256"])
            for key in PATTERN_METHODS
        }

    def _pattern_method_claims(self, authority: dict[str, Any], policy_sha: str) -> dict[str, str]:
        """Existing immutable selections own a method before inbox publication."""
        scope = fingerprint({"authority": authority, "policy_sha": policy_sha})
        claims: dict[str, str] = {}
        with self.registry.lock:
            for method in PATTERN_METHODS:
                rows = self.registry.db.execute(
                    "SELECT body FROM role_question_selections WHERE scope_sha=? "
                    "AND json_extract(body,'$.method')=? "
                    "AND coalesce(json_extract(body,'$.dispatch_available'),1)=1 "
                    "ORDER BY (json_type(body,'$.learning.method_claims') IS NOT NULL) DESC, "
                    "created,selection_sha LIMIT 2",
                    (scope, method),
                ).fetchall()
                if not rows:
                    continue
                value = json.loads(rows[0]["body"])
                if len(rows) > 1 and "method_claims" in value.get("learning", {}):
                    raise InputWait("Fixed method has conflicting original question ownership")
                # Older policies could revisit an unfunded method after no_change.
                # Those permanent questions consume that method too. Use their
                # first identity; never reinterpret them as fresh availability.
                claims[method] = value["comparison"]["request_id"]
        return claims

    def _pattern_method_admission(
        self, binding: dict[str, Any], task_proposal: dict[str, Any] | None = None
    ) -> None:
        method = binding.get("next_method")
        if not isinstance(method, dict) or method != self._pattern_method_identity(
            method.get("method_id")
        ):
            raise InputWait("Captured pattern method policy changed")
        expected = binding.get("used_methods")
        if (
            not isinstance(expected, dict)
            or set(expected) != set(PATTERN_METHODS)
            or any(not isinstance(value, bool) for value in expected.values())
        ):
            raise InputWait("Captured method availability is unavailable")
        current = self._pattern_method_used()
        if task_proposal is not None and current != expected:
            assert self.controller is not None
            try:
                saved = self.controller.inbox.get(task_proposal["request_id"])
            except ValueError:
                saved = None
            proposal = LabProposal.model_validate(task_proposal)
            if (
                saved
                and saved["body"] == task_proposal
                and fingerprint(proposal.strategy.model_dump()) == method["strategy_sha256"]
                and fingerprint(proposal.reference.model_dump()) == method["reference_sha256"]
            ):
                current[method["method_id"]] = expected[method["method_id"]]
        claims = binding.get("method_claims")
        if claims is not None:
            current_claims = self._pattern_method_claims(
                binding["authority"], binding["policy_sha256"]
            )
            own = current_claims.get(method["method_id"])
            if any(current_claims.get(key) != value for key, value in claims.items()) or (
                binding["dispatch_available"]
                and own is not None
                and own != binding.get("claim_preparation")
            ):
                raise InputWait("Fixed method already belongs to another original question")
        # An independent method can finish while this task waits, including for
        # older bindings that predate method claims. Its monotonic publication
        # cannot invalidate the frozen packet or change its own method authority.
        for key in PATTERN_METHODS:
            if key != method["method_id"] and not expected[key]:
                current[key] = False
        if current != expected:
            raise InputWait("Captured fixed-method availability changed")
        unused = next(
            (key for key in PATTERN_METHODS if not expected[key] and key not in (claims or {})),
            None,
        )
        if binding["dispatch_available"]:
            if unused != method["method_id"]:
                raise InputWait("Captured method is not the first unused fixed candidate")
        elif unused is not None or binding["state"] != "mature_outcome":
            raise InputWait("Read-only method observation requires its exact mature predecessor")

    @staticmethod
    def _pattern_method(original: dict[str, Any], *, research_only: bool = False) -> LabProposal:
        if not research_only:
            if original["proposal"] is None:
                raise InputWait("Original preparation has no frozen comparison proposal")
            return LabProposal.model_validate(original["proposal"])
        if (
            original["status"] not in {"research_only", "waiting"}
            or original["proposal"] is not None
            or original.get("dispatch_available") is not False
        ):
            raise InputWait("Read-only comparison must not expose proposal dispatch authority")
        return LabProposal.model_validate(
            original["readonly_comparison_template"]
            | {"evidence_bundle_sha256": original["issued_bundle_sha256"]}
        )

    def _pattern_ready(self, policy: dict[str, Any], now: float) -> dict[str, Any]:
        c = self.controller
        if c is None or self._contract_version() != PATTERN_VERSION:
            raise InputWait("Pattern comparison needs its explicit successor owner and contract")
        authority = self._selection_authority()
        if authority is None or authority["question_policy"] not in {
            PATTERN_QUESTION_POLICY,
            PATTERN_LEARNING_QUESTION_POLICY,
            PATTERN_METHOD_QUESTION_POLICY,
        }:
            raise InputWait("Pattern comparison requires its explicit selection authority")
        paper = c.paper
        if not self._activation_enabled() or not self._admitted():
            raise InputWait("Pattern comparison waits for protected paper admission")
        last_tick = paper.state.get("last_tick", 0)
        observed = time.time()
        frame = paper.control_frames().get("BTCUSD")
        frame_observed = time.time()
        book = frame.get("book") if frame else None
        bars = paper.history.get("BTCUSD", [])[-600:]
        if (
            not paper.running
            or paper.error
            or paper.state.get("paused")
            or not 0 <= observed - last_tick <= 10
            or not paper.state.get("autonomous_lab")
            or paper.state["autonomous_lab"].get("proposals_paused")
            or fingerprint(paper.state["autonomous_lab"]["policy"]) != fingerprint(policy)
            or not fresh_frame(frame, frame_observed)
            or not frame
            or frame.get("diagnostic_risk_input_valid") is not True
            or frame.get("entry_allowed") is not True
            or not book
            or not book.bids
            or not book.asks
            or any(
                not p.is_finite() or not q.is_finite() or p <= 0 or q <= 0
                for p, q in (*book.bids, *book.asks)
            )
            or book.bids[0][0] >= book.asks[0][0]
            or len(bars) < 305
            or bars[-1].close_ms >= now * 1000
            or bars[-1].open_ms + 60000 < getattr(paper, "ready_at", math.inf) * 1000
            or getattr(paper, "_candle_errors", {}).get("BTCUSD")
            or any(b.open_ms - a.open_ms != 60000 for a, b in zip(bars, bars[1:], strict=False))
        ):
            raise InputWait("Pattern comparison waits for protected current executable BTC inputs")
        return frame

    def _pattern_inputs(
        self,
        source: dict[str, str],
        question: Question,
        policy: dict[str, Any],
        now: float,
        *,
        finite_authority: dict[str, Any] | None = None,
        learning_binding: dict[str, Any] | None = None,
        method_id: str = "p0",
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        admission: Callable[[], Any] | None = (
            self._finite_admission(finite_authority) if finite_authority is not None else None
        )
        if learning_binding is not None:
            admission = self._pattern_learning_admission(
                learning_binding, learning_binding["authority"], policy
            )
        if admission is not None:
            admission()
        learning = self._selection_authority()
        if (
            question.horizon != "medium"
            or question.parent
            or (
                question.lesson
                and (
                    not learning
                    or learning["question_policy"]
                    not in {PATTERN_LEARNING_QUESTION_POLICY, PATTERN_METHOD_QUESTION_POLICY}
                )
            )
        ):
            raise ValueError("Pattern comparison is one fixed independent medium hypothesis")
        research_only = bool(
            learning_binding
            and learning_binding["state"] == "mature_outcome"
            and learning_binding["dispatch_available"] is False
        )
        original = self._pattern_original(source, research_only=research_only, method_id=method_id)
        self._pattern_ready(policy, now)
        if original["current_policy_sha256"] != digest(policy):
            raise ValueError("Saved comparison belongs to a different frozen Lab policy")
        c, bridge = self.controller, self.pattern_comparisons
        assert c is not None and bridge is not None
        proposal = self._pattern_method(original, research_only=research_only)
        if (
            proposal.kind != "independent"
            or proposal.strategy.version != "reviewed-lab-rules-v4"
            or proposal.strategy.family != PATTERN_METHODS[method_id][0]
            or proposal.reference.family != PATTERN_METHODS[method_id][1]
            or proposal.reference.version != "reviewed-lab-rules-v4"
            or proposal.strategy.holding_horizon != "medium"
        ):
            raise ValueError("Prepared proposal differs from the fixed supported pattern mapping")
        used = self._pattern_admission(proposal, now, research_only=research_only)
        if learning_binding is not None and used == learning_binding["dispatch_available"]:
            raise InputWait("Fixed comparison dispatch availability changed")
        reversed_proposal = LabProposal.model_validate(
            {
                **proposal.model_dump(),
                "strategy": proposal.reference.model_dump(),
                "reference": proposal.strategy.model_dump(),
            }
        )
        candidate = c.evaluate(proposal, now)
        if admission is not None:
            admission()
        reference = c.evaluate(reversed_proposal, now)
        if admission is not None:
            admission()
        inputs = candidate.pop("inputs")
        if reference.pop("inputs") != inputs or not 305 <= len(inputs) <= 600:
            raise ValueError("Current matched pattern inputs differ")
        proof = original["evaluation"].get("matched_inputs")
        if proof is not None:
            bridge.execution_inputs(proof, original["request_id"])
        if original["status"] == "waiting" or proof is None or digest(inputs) != proof["sha256"]:
            observation_sha = digest(inputs)
            if learning and learning["question_policy"] == PATTERN_METHOD_QUESTION_POLICY:
                observation_sha = digest(
                    {"inputs": observation_sha, "method": self._pattern_method_identity(method_id)}
                )
            observation_id = "role-input-" + observation_sha[:32]
            observation = bridge.current_observation(
                observation_id,
                now,
                admission=admission,
                research_only=research_only,
                method_id=method_id,
            )
            evaluation = observation["evaluation"]
            expected = (
                "supported_research_observation"
                if research_only
                else "supported_exploratory_configuration"
            )
            if evaluation["status"] != expected:
                raise InputWait(evaluation["reason"])
            proof = evaluation["matched_inputs"]
            if proof["sha256"] != digest(inputs):
                raise InputWait("Current causal input changed during archive observation")
            if bridge.execution_inputs(proof, observation_id) != inputs:
                raise ValueError("Current retained execution inputs differ")
        catalog = {
            method_id: {
                "kind": proposal.kind,
                "strategy": proposal.strategy.model_dump(),
                "reference": proposal.reference.model_dump(),
            }
        }
        if research_only:
            catalog = {}
        frame = self._pattern_ready(policy, now)
        book = frame["book"]
        causal = {
            "tool": "reviewed_rule_inputs",
            "security": "BTCUSD",
            "holding_horizon": "medium",
            "source_basis": c.paper.state.get("evidence_kind", "observed_public_market"),
            "closed_bar_count": len(inputs),
            "closed_bar_sha256": digest(inputs),
            "source_start": inputs[0]["open_ms"] / 1000,
            "source_end": inputs[-1]["close_ms"] / 1000,
            "observed_at": now,
            "features": {method_id: candidate["feature"]},
            "reference_features": {method_id: reference["feature"]},
            "matched_inputs": proof,
            "executable_book": plain({k: v for k, v in (frame or {}).items() if k != "book"})
            | {
                "bids": [[str(p), str(q)] for p, q in book.bids[:3]] if book else [],
                "asks": [[str(p), str(q)] for p, q in book.asks[:3]] if book else [],
                "update_id": book.update_id if book else None,
            },
            "scope": (
                "Current separate v4 minute inputs; native recognition is hypothesis motivation"
            ),
        }
        summary = pattern_summary(original)
        old_evaluation = original["evaluation"]
        summary["original_evaluation"] = {
            "status": original["status"],
            "evaluated_at": old_evaluation.get("candidate", {}).get("evaluated_at"),
            "expires_at": old_evaluation.get("candidate", {}).get("expires_at"),
            "matched_inputs": (
                {
                    key: old_evaluation["matched_inputs"][key]
                    for key in ("count", "sha256", "cutoff", "archive_verified")
                }
                if old_evaluation.get("matched_inputs") is not None
                else None
            ),
        }
        if original["status"] == "waiting":
            summary["original_evaluation"]["reason"] = old_evaluation["reason"]
        fixed = {
            method_id: {
                "candidate": contract(proposal, LabPolicy.model_validate(policy)),
                "reference": contract(reversed_proposal, LabPolicy.model_validate(policy)),
                "source_sha256": original["mapping"]["source_sha256"],
                "current_inputs": {
                    key: proof[key]
                    for key in (
                        "count",
                        "sha256",
                        "cutoff",
                        "start_ms",
                        "end_ms",
                        "archive_verified",
                    )
                }
                | {"retained_at": proof["cutoff"]},
            }
        }
        if learning_binding is not None:
            fixed[method_id]["dispatch_available"] = learning_binding["dispatch_available"]
            fixed[method_id]["dispatch_reason"] = learning_binding["dispatch_reason"]
            if research_only:
                for label in ("candidate", "reference"):
                    template = fixed[method_id][label].pop("proposal")
                    template.pop("evidence_bundle_sha256")
                    fixed[method_id][label]["proposal_without_bundle_digest"] = template
        issued = {"sha256": original["issued_bundle_sha256"], "kind": "saved-pattern-preparation"}
        return catalog, issued, causal, summary, fixed

    def _pattern_admission(
        self,
        proposal: LabProposal,
        now: float,
        task_proposal: dict[str, Any] | None = None,
        *,
        research_only: bool = False,
    ) -> bool:
        bridge, c = self.pattern_comparisons, self.controller
        assert bridge is not None and c is not None
        roster = bridge.scanner.roster(now, full=True)
        if roster["available"] is not True or not any(
            item["symbol"] == "BTCUSD" and item["eligible"] is True for item in roster["rows"]
        ):
            raise InputWait("Current BTC market eligibility is unavailable")
        existing = None
        if task_proposal is not None:
            try:
                existing = c.inbox.get(task_proposal["request_id"])
            except ValueError:
                pass
            if existing and fingerprint(existing["body"]) != fingerprint(task_proposal):
                raise ValueError("Original proposal acknowledgment identity differs")
        used = c.inbox.used(fingerprint(proposal.strategy.model_dump()))
        if not existing and (not c.inbox.has_capacity() or used and not research_only):
            raise InputWait(
                "Existing proposal capacity or equivalent used-rule gate blocks this test"
            )
        return used

    def _pattern_permitted(
        self,
        original: dict[str, Any],
        start: float,
        end: float,
        *,
        research_only: bool = False,
        method_id: str = "p0",
    ) -> None:
        assert self.pattern_comparisons is not None
        with self.registry.lock:
            self.pattern_comparisons._permitted(
                [tuple(pair) for pair in original["finding"]["native_proof"]["disclosed_intervals"]]
                + [(start, end)],
                research_only=research_only,
                method_id=method_id,
            )

    def enqueue(
        self,
        question: Question,
        now: float | None = None,
        *,
        _resume_from: dict[str, Any] | None = None,
        _dependency_evidence: dict[str, Any] | None = None,
        _selection: dict[str, Any] | None = None,
        _selection_authority: dict[str, Any] | None = None,
        _pattern_comparison: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        question_body = question.model_dump(exclude={"request_id"})
        question_sha256 = fingerprint(question_body)
        with self.registry.lock:
            requested = self._requested(question)
        if requested:
            return self.get(requested) | (
                {"_selection_created": False} if _selection is not None else {}
            )
        finite = self._finite_current()
        if finite is not None:
            if _resume_from is None and _selection is None:
                raise InputWait("Finite test refuses an independent or unmarked manual question")
            with self.registry.lock:
                prior_finite = self.finite.prior(finite)
                if _resume_from is None and prior_finite is not None:
                    raise InputWait("Finite test already claimed its one original research chain")
                if _resume_from is not None:
                    self.finite.binding(_resume_from)
                    if self.finite.count(self.finite.binding(_resume_from)) >= 3:
                        raise InputWait("Finite lifetime request allowance is exhausted")
        pilot_grant_id = self._pilot_grant_id()
        c = self.controller
        if c is None or not c.paper.state.get("autonomous_lab"):
            raise ValueError("Declare an ordinary paper lab policy before creating role research")
        policy = c.paper.state["autonomous_lab"]["policy"]
        if question.horizon not in policy["holding_horizons"]:
            raise ValueError("Question horizon is outside the active policy")
        if self._contract_version() == PATTERN_VERSION and _pattern_comparison is None:
            if _resume_from and "pattern_comparison" in _resume_from["context"]:
                saved = _resume_from["context"]["pattern_comparison"]
                _pattern_comparison = {
                    "request_id": saved["preparation_request_id"],
                    "finding_sha256": saved["finding_sha256"],
                    "issued_bundle_sha256": saved["issued_bundle_sha256"],
                }
            else:
                raise ValueError("Pattern research requires its exact verified saved preparation")
        pattern = None
        fixed_comparison = None
        learning = None
        method_id = "p0"
        catalog: dict[str, Any]
        waits: dict[str, Any]
        if _pattern_comparison is not None:
            prior = None
            authority = self._selection_authority()
            if authority and authority["question_policy"] in {
                PATTERN_LEARNING_QUESTION_POLICY,
                PATTERN_METHOD_QUESTION_POLICY,
            }:
                learning = (
                    _selection.get("learning")
                    if _selection is not None
                    else (_resume_from or {}).get("context", {}).get("pattern_learning")
                )
                if not isinstance(learning, dict):
                    raise InputWait(
                        "Pattern learning requires its exact frozen predecessor binding"
                    )
                prior = self._pattern_learning_body(learning)
                if question.lesson != (prior["id"] if prior else None):
                    raise ValueError("Pattern question and original supported lesson differ")
                if authority["question_policy"] == PATTERN_METHOD_QUESTION_POLICY:
                    method_id = learning["next_method"]["method_id"]
                    self._pattern_method_admission(learning)
            catalog, issued, causal_inputs, pattern, fixed_comparison = self._pattern_inputs(
                _pattern_comparison,
                question,
                policy,
                now,
                finite_authority=finite,
                learning_binding=learning,
                method_id=method_id,
            )
            waits = {
                "new_closed_bars": {
                    "kind": "closed_bars",
                    "horizon": question.horizon,
                    "source_sha256": causal_inputs["closed_bar_sha256"],
                    "last_closed_at": causal_inputs["source_end"],
                }
            }
        else:
            base = RuleSpec(holding_horizon=question.horizon)
            catalog = {}
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
            waits = {
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
            "contract": self._contract_version(),
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
        if pattern is not None:
            context["pattern_comparison"] = pattern
            context["fixed_comparison"] = fixed_comparison
        if learning is not None:
            context["pattern_learning"] = learning
            if learning["authority"]["question_policy"] == PATTERN_METHOD_QUESTION_POLICY:
                context["pattern_method"] = self._pattern_method_identity(method_id)
        if _selection is not None:
            _selection_authority = _selection["authority"]
            context["question_selection"] = _selection
            self._check_selection(_selection, question, policy, causal_inputs, catalog, now)
        if _selection_authority is not None:
            if _selection_authority != self._selection_authority():
                raise InputWait("Question selection authority changed; original scope retained")
            context["selection_authority"] = _selection_authority
        if self.paper_pilot:
            context["execution_mode"] = PAPER_RESEARCH_PILOT
            context["pilot_grant_id"] = pilot_grant_id
            context["experimental"] = True
            context["qualified"] = False
        identity = (
            "role-"
            + fingerprint(
                {
                    "question": question_body,
                    "policy": policy,
                    "catalog": catalog,
                    "evidence": issued["sha256"]
                    if pattern is not None
                    else issued["bundle"]["novelty_sha256"],
                    "source": causal_inputs["closed_bar_sha256"],
                    "waits": waits,
                    "dependency_evidence": _dependency_evidence,
                    **(
                        {"selection_authority": _selection_authority}
                        if _selection_authority is not None
                        else {}
                    ),
                    **({"question_selection": _selection} if _selection is not None else {}),
                    **({"contract": context["contract"]} if context["contract"] != VERSION else {}),
                    **(
                        {
                            "execution_mode": PAPER_RESEARCH_PILOT,
                            "pilot_grant_id": pilot_grant_id,
                        }
                        if self.paper_pilot
                        else {}
                    ),
                }
            )[:32]
        )
        if finite is not None:
            root = (
                self.finite.binding(_resume_from)["root_task"]
                if _resume_from is not None
                else identity
            )
            context["finite_test"] = {**finite, "root_task": root}
        if self.knowledge is not None and not self.paper_pilot:
            context["knowledge"] = self.knowledge.retrieve(
                KnowledgeQuery(
                    text=question.question[:300],
                    cutoff=time.time(),
                    symbol="BTCUSD",
                    horizon=question.horizon,
                ),
                task=identity,
            )
        encoded = json.dumps(context, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Role evidence context exceeds 64 KiB")
        self.history.rollover()
        with self.registry.transaction():
            requested = self._requested(question)
            if requested:
                return self.get(requested) | (
                    {"_selection_created": False} if _selection is not None else {}
                )
            if _selection_authority is not None:
                if _selection_authority != self._selection_authority():
                    raise InputWait("Question selection grant changed before publication")
            if finite is not None:
                if self._finite_current() != finite:
                    raise InputWait("Finite grant changed before atomic task publication")
                self.finite.claim(finite, identity, context, time.time(), _resume_from)
            if _selection is not None:
                self._check_selection(_selection, question, policy, causal_inputs, catalog, now)
                self._selection_room(_selection["authority"], policy, now)
                latest = self.registry.db.execute(
                    "SELECT selection_sha FROM role_question_selections WHERE scope_sha=? "
                    "AND horizon=? ORDER BY source_end DESC LIMIT 1",
                    (_selection["scope_sha"], question.horizon),
                ).fetchone()
                if (latest["selection_sha"] if latest else None) != _selection["prior_selection"]:
                    raise InputWait("Selection predecessor changed before atomic publication")
            if learning is not None:
                self._pattern_learning_admission(learning, learning["authority"], policy)()
            if learning is not None and learning["lesson"] is not None:
                # The existing lesson owner joins this transaction: exposure,
                # question and selection become visible together or roll back.
                disclosed = self.lessons.get(learning["lesson"]["id"])
                if disclosed["sha256"] != learning["lesson"]["sha256"]:
                    raise InputWait("Supported lesson changed before atomic disclosure")
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
                self.registry.event(
                    identity,
                    "role_question",
                    {"question": question.question}
                    | ({"question_selection": _selection} if _selection is not None else {})
                    | ({"execution_mode": PAPER_RESEARCH_PILOT} if self.paper_pilot else {}),
                )
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
            if _selection is not None:
                self.registry.db.execute(
                    "INSERT INTO role_question_selections VALUES(?,?,?,?,?,?,?)",
                    (
                        _selection["selection_sha"],
                        _selection["scope_sha"],
                        question.horizon,
                        _selection["source_end"],
                        now,
                        identity,
                        json.dumps(_selection, sort_keys=True, allow_nan=False),
                    ),
                )
                if learning is not None and learning["lesson"] is not None:
                    self.lessons.selected(
                        learning["lesson"]["id"],
                        "selected",
                        (
                            "Distinct later native question uses the exact mature outcome; "
                            f"independent next fixed method {method_id}, no parent-trial authority."
                            if "pattern_method" in context
                            else "Distinct later native question uses the mature outcome; "
                            "the fixed p0 method is unchanged, not a strategy refinement."
                        ),
                        identity,
                    )
        return self.get(identity) | ({"_selection_created": True} if _selection is not None else {})

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
        result["execution"] = {
            "kind": "external"
            if str(row["owner"]).startswith("actor:")
            else "local"
            if row["owner"]
            else "unclaimed",
            "lease_until": row["lease_until"],
        }
        if row["owner"] and result["attempts"]:
            last_profile = json.loads(result["attempts"][-1]["profile"])
            result["execution"]["actor"] = last_profile.get("actor", "Local worker")
        return result

    def readiness(self) -> dict[str, Any]:
        result: dict[str, Any] = (
            self.transport.readiness()
            if self.transport
            else {"qualified": False, "reason": "No qualified local role profile configured"}
        )
        if self.paper_pilot:
            result.update(
                paper_pilot=True,
                experimental=True,
                qualified=False,
                qualification_valid=False,
            )
            result.setdefault("stages", {})["retrieval"] = {
                "state": "not_enabled",
                "next_action": (
                    "Paper pilot uses frozen numerical/market evidence; RAG is not enabled"
                ),
            }
        elif self.knowledge is not None:
            # New investigations use this library even when retrieval has no match.
            # Keep valid declared-profile receipts independent of current packet compatibility.
            stage = {
                "state": "compatible",
                "next_action": (
                    "Declared source-rag-v1 matches the current retrieval contract; "
                    "dispatch still verifies the exact packet and qualification"
                ),
            }
            try:
                LocalRoles.check_retrieval_contract(RETRIEVAL_CONTRACT, result.get("profile") or {})
            except ValueError as exc:
                stage = {"state": "incompatible", "next_action": str(exc)}
                result["ready"] = False
            result.setdefault("stages", {})["retrieval"] = stage
        paper = self.controller.paper if self.controller else None
        state = "unavailable"
        if paper is not None and paper.running:
            if paper.error:
                state = "unhealthy"
            elif not 0 <= time.time() - paper.state.get("last_tick", 0) <= 10:
                state = "stale"
            else:
                if self.paper_pilot:
                    state = "available" if self._admitted() else "refused"
                else:
                    guard = getattr(paper, "constrained", None)
                    state = (
                        ("refused" if guard() else "available") if callable(guard) else "unverified"
                    )
        result["operating_admission"] = {
            "state": state,
            "checked_at": time.time(),
            "next_action": (
                (
                    "Dispatch rechecks the experimental pilot profile, protected admission "
                    "and activation"
                    if self.paper_pilot
                    else "Dispatch still rechecks the unchanged guard, qualified profile "
                    "and activation"
                )
                if state == "available"
                else (
                    "Resolve protected paper health/resource coverage in its existing owner; "
                    "do not bypass admission"
                )
            ),
            "meaning": "Current prerequisite observation, not a model call or quality score",
        }
        result["ready"] = bool(result.get("ready") and state == "available")
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
        try:
            pilot_grant_id = self._pilot_grant_id()
            current_contract = self._contract_version()
            selection_json = self._selection_json()
            current_authority = True
        except (ValueError, OSError, KeyError):
            pilot_grant_id = None
            current_contract = None
            selection_json = "null"
            current_authority = False
        with self.registry.lock:
            rows = self.registry.db.execute(query, params).fetchall()
            counts = self.registry.db.execute(
                "SELECT count(*),count(archive_reference),"
                "sum(status NOT IN ('done','failed')) FROM role_tasks"
            ).fetchone()
            supervision = [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT * FROM role_supervision WHERE reason IS NOT NULL ORDER BY phase LIMIT 3"
                )
            ]
            current = self.registry.db.execute(
                "SELECT id,question_text AS question,stage,status,reason,updated,lease_until "
                "FROM role_tasks WHERE owner=? AND lease_until>=? AND ? "
                "AND coalesce(json_extract(context,'$.execution_mode'),'qualified_roles')=? "
                "AND coalesce(json_extract(context,'$.contract'),'reviewed-rule-role-v5')=? "
                "AND (? IS NULL OR json_extract(context,'$.pilot_grant_id')=?) "
                "AND (json_type(context,'$.selection_authority') IS NULL "
                "OR json_extract(context,'$.selection_authority')=json(?)) "
                "ORDER BY updated DESC,id LIMIT 1",
                (
                    self.owner,
                    time.time(),
                    current_authority,
                    self.execution_mode,
                    current_contract,
                    pilot_grant_id,
                    pilot_grant_id,
                    selection_json,
                ),
            ).fetchone()
            pending = self.registry.db.execute(
                "SELECT count(*) AS total,"
                "coalesce(sum(stage='tool_wait'),0) AS tools,"
                "coalesce(sum(stage='data_wait'),0) AS data,"
                "coalesce(sum(stage='outcome'),0) AS outcomes "
                "FROM role_tasks WHERE status NOT IN ('done','failed') AND ? "
                "AND coalesce(json_extract(context,'$.execution_mode'),'qualified_roles')=? "
                "AND coalesce(json_extract(context,'$.contract'),'reviewed-rule-role-v5')=? "
                "AND (? IS NULL OR json_extract(context,'$.pilot_grant_id')=?) "
                "AND (json_type(context,'$.selection_authority') IS NULL "
                "OR json_extract(context,'$.selection_authority')=json(?))",
                (
                    current_authority,
                    self.execution_mode,
                    current_contract,
                    pilot_grant_id,
                    pilot_grant_id,
                    selection_json,
                ),
            ).fetchone()
        enabled = self._activation_enabled()
        queued = pending["total"] - pending["tools"] - pending["data"] - pending["outcomes"]
        activity = {
            "state": "unavailable"
            if not current_authority
            else "paused"
            if not enabled
            else "running"
            if current
            else "queued"
            if queued
            else "waiting"
            if pending["total"]
            else "idle",
            "reason": (
                "Current research authority unavailable; retained tasks are unchanged"
                if not current_authority
                else "Research is paused"
                if not enabled
                else "The current task owns the inference or processing lease"
                if current
                else "Saved investigations await dispatch and its protected prerequisites"
                if queued
                else "Saved investigations await tool review, eligible data or paper outcomes"
                if pending["total"]
                else "No queued investigation or eligible continuation; no model request is running"
            ),
            "checked_at": time.time(),
            "pending_tools": pending["tools"],
            "pending_data": pending["data"],
            "pending_outcomes": pending["outcomes"],
            "queued": queued,
        }
        return {
            "enabled": enabled,
            "paper_pilot": self.paper_pilot,
            "experimental": self.paper_pilot,
            "execution_mode": self.execution_mode,
            "current_task": dict(current) if current else None,
            "activity": activity,
            "question_selection": self.question_selection_status(),
            "contract": current_contract,
            "reason": self.reason
            if not enabled
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
            "supervision": supervision,
            "readiness": self.readiness(),
        }

    def view(self, identity: str) -> dict[str, Any]:
        task = self.get(identity)
        recorded_contract = task["context"].get("contract", VERSION)
        try:
            selected_contract: str | None = self._contract_version()
        except (ValueError, OSError, KeyError):
            selected_contract = None
        # This is current applicability, not a new historical outcome. Older
        # tasks stay unchanged when the selected profile's contract changes.
        task["contract_applicability"] = {
            "state": "unavailable"
            if selected_contract is None
            else "matching"
            if recorded_contract == selected_contract
            else "different",
            "reason": "Current role contract unavailable; retained history is unchanged"
            if selected_contract is None
            else "Saved role contract matches the selected worker; admission is separate"
            if recorded_contract == selected_contract
            else "Frozen role contract changed; retained investigation is inactive under the "
            "selected profile",
            "recorded_contract": recorded_contract,
            "selected_contract": selected_contract,
        }
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
        self._disclose_outcome(task["id"], task["result"])
        if len(json.dumps(task).encode()) > 131072:
            raise ValueError(
                "Task detail exceeds its bounded response allowance; exact attempts retained"
            )
        return task

    def training_candidate(self, identity: str, stage: str, attempt: int) -> dict[str, Any]:
        """Private operator export; preserve the normal outcome-disclosure boundary."""
        from trading.llm_training import candidate_from_task

        if stage not in {"idea", "review", "followup"} or not 1 <= attempt <= 100:
            raise ValueError("Select a retained attempt")
        with self.registry.lock, self.registry.transaction():
            row = self.registry.db.execute(
                "SELECT id,created,updated,stage,status,archive_reference,archive_sha256,"
                "json_extract(context,'$.contract') AS contract,"
                "json_extract(context,'$.execution_mode') AS execution_mode,"
                "json_extract(context,'$.question') AS question,"
                "json_extract(context,'$.issued.sha256') AS bundle_sha256,"
                "json_extract(result,'$.outcome') AS outcome "
                "FROM role_tasks WHERE id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown role task")
            if row["archive_reference"]:
                saved = self.history.read(row)
                context = json.loads(saved["context"])
            else:
                context = {
                    "contract": row["contract"],
                    "execution_mode": row["execution_mode"],
                    "question": json.loads(row["question"]),
                    "issued": {"sha256": row["bundle_sha256"]},
                }
            if context.get("execution_mode") == PAPER_RESEARCH_PILOT:
                raise ValueError(
                    "Experimental pilot answers are retained; training export needs "
                    "separate authorization"
                )
            if row["archive_reference"]:
                selected = [
                    a for a in saved["attempts"] if a["stage"] == stage and a["attempt"] == attempt
                ]
                result = json.loads(saved["result"]) if saved["result"] else None
            else:
                selected = [
                    dict(a)
                    for a in self.registry.db.execute(
                        "SELECT stage,attempt,started,finished,"
                        "CASE WHEN length(CAST(packet AS BLOB))<=131072 THEN packet END AS packet,"
                        "CASE WHEN length(CAST(response AS BLOB))<=131072 "
                        "THEN response END AS response,"
                        "length(CAST(packet AS BLOB)) AS packet_bytes,"
                        "length(CAST(response AS BLOB)) AS response_bytes "
                        "FROM role_attempts WHERE task=? AND stage=? AND attempt=?",
                        (identity, stage, attempt),
                    )
                ]
                result = {"outcome": json.loads(row["outcome"])} if row["outcome"] else None
            if len(selected) != 1:
                raise ValueError("Selected retained attempt is unavailable")
            a = selected[0]
            if a["packet"] is None or (
                a.get("packet_bytes", 0) > 131072
                or a.get("response_bytes", 0) > 131072
                or len(a["packet"].encode("utf-8")) > 131072
                or len((a["response"] or "").encode("utf-8")) > 131072
            ):
                raise ValueError("Selected retained attempt exceeds its export allowance")
            task = {"id": identity, "context": context, "attempts": selected}
            export = candidate_from_task(task, stage, attempt)
            # Shared authority handling, after exact selected-record verification.
            self._disclose_outcome(identity, result)
            return export

    def _disclose_outcome(self, identity: str, result: dict[str, Any] | None) -> None:
        if result and result.get("outcome"):
            outcome = result["outcome"]["body"]
            with nullcontext() if self.registry.db.in_transaction else self.registry.transaction():
                self.registry.db.execute(
                    "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,'role task disclosure')",
                    ("role-view:" + identity, outcome["window_start"], outcome["available_at"]),
                )

    def retry(self, identity: str) -> dict[str, Any]:
        """One explicit operational retry; never request a preferred verdict."""
        task = self.get(identity)
        if not self._same_mode(task):
            raise ValueError("Retained task belongs to a different role execution mode")
        if task["stage"] == "archive_evaluation" and task["status"] == "failed":
            evaluation = task.get("evaluation")
            if not isinstance(evaluation, dict) or not isinstance(evaluation.get("inputs"), list):
                raise ValueError("Original full evaluation is unavailable; archive retry refused")
            self.history.restore(identity)
            with self.registry.transaction():
                if (
                    self.registry.db.execute(
                        "SELECT count(*) FROM role_tasks WHERE status NOT IN ('done','failed')"
                    ).fetchone()[0]
                    >= 8
                ):
                    raise ValueError("Eight active role questions; retry when a slot is available")
                retained = self.registry.db.execute(
                    "SELECT evaluation FROM role_tasks WHERE id=?", (identity,)
                ).fetchone()
                if retained is None or json.loads(retained["evaluation"] or "null") != evaluation:
                    raise ValueError("Original evaluation changed; archive retry refused")
                changed = self.registry.db.execute(
                    "UPDATE role_tasks SET status='queued',retry_at=0 "
                    "WHERE id=? AND stage='archive_evaluation' AND status='failed' "
                    "AND owner IS NULL AND lease_until IS NULL AND evaluation=?",
                    (identity, retained["evaluation"]),
                ).rowcount
                if changed != 1:
                    raise ValueError("Retained archive stage changed; inspect its current owner")
                self.registry.event(
                    identity,
                    "role_archive_retry_authorized",
                    {"stage": task["stage"], "model_attempts_unchanged": True},
                )
            return self.view(identity)
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
    ) -> bool:
        with self.registry.transaction():
            if (
                "finite_test" in task["context"]
                and task["stage"] != "outcome"
                and not (task["stage"] == "submit" and self._finite_accepted(task))
                and (
                    stage != task["stage"]
                    or any(k in values for k in ("proposal", "evaluation", "result"))
                )
            ):
                self._finite_current(task)
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
            params.extend(
                [
                    task["id"],
                    task["stage"],
                    self.owner,
                    time.time(),
                    int(not task.get("_claimed_owner")),
                ]
            )
            changed = bool(
                self.registry.db.execute(
                    "UPDATE role_tasks SET " + ",".join(assignments) + " WHERE id=? AND stage=? "
                    "AND (owner=? AND lease_until>=? "
                    "OR ?=1 AND owner IS NULL AND lease_until IS NULL)",
                    params,
                ).rowcount
            )
            if (
                changed
                and task["context"]["contract"] == PATTERN_VERSION
                and task["stage"] == "evaluate"
                and stage == "archive_evaluation"
            ):
                self._pattern_numerical_exposure(task, values["evaluation"])
                self.registry.db.execute(
                    "UPDATE role_tasks SET evaluation=? WHERE id=?",
                    (json.dumps(values["evaluation"], sort_keys=True, allow_nan=False), task["id"]),
                )
            return changed

    def _pattern_numerical_exposure(self, task: dict[str, Any], evaluation: dict[str, Any]) -> None:
        """Publish actual v8 numerical exposure in the lease-checked task transaction."""
        bridge = self.pattern_comparisons
        if bridge is None:
            raise ValueError("Original pattern preparation owner is unavailable")
        source = task["context"]["pattern_comparison"]
        method_id = self._pattern_task_method(task)
        if method_id != "p0" or "pattern_method" in task["context"]:
            if evaluation.get("pattern_method") != task["context"]["pattern_method"]:
                raise InputWait("Numerical evaluation method identity changed")
            self._pattern_learning_admission(
                task["context"]["pattern_learning"],
                task["context"]["selection_authority"],
                task["context"]["policy"],
            )()
        original = bridge.get(source["preparation_request_id"])
        if original is None or any(
            original[key] != source[key] for key in ("finding_sha256", "issued_bundle_sha256")
        ):
            raise ValueError("Original pattern numerical preparation identity differs")
        if evaluation.get("pattern_source") != {
            key: source[key]
            for key in ("finding_sha256", "issued_bundle_sha256", "preparation_request_id")
        }:
            raise ValueError("Actual pattern numerical source identity is missing or changed")
        at, inputs, reference = (
            evaluation.get("evaluated_at"),
            evaluation.get("inputs"),
            evaluation.get("reference"),
        )
        if (
            not isinstance(at, (int, float))
            or isinstance(at, bool)
            or not math.isfinite(at)
            or at <= 0
            or not isinstance(inputs, list)
            or not 305 <= len(inputs) <= 600
            or not isinstance(reference, dict)
            or reference.get("evaluated_at") != at
            or evaluation.get("financial_authority") is not False
            or reference.get("financial_authority") is not False
        ):
            raise ValueError("Actual matched numerical prefix identity is unavailable")
        fields = {"open_ms", "close_ms", "open", "high", "low", "close", "volume"}
        previous = None
        for row in inputs:
            if (
                not isinstance(row, dict)
                or set(row) != fields
                or type(row["open_ms"]) is not int
                or type(row["close_ms"]) is not int
                or row["open_ms"] % 60000
                or row["close_ms"] != row["open_ms"] + 59999
                or row["close_ms"] >= at * 1000
                or (previous is not None and row["open_ms"] != previous + 60000)
            ):
                raise ValueError("Actual numerical prefix must be contiguous closed minute bars")
            for key in fields - {"open_ms", "close_ms"}:
                if not isinstance(row[key], str) or not Decimal(row[key]).is_finite():
                    raise ValueError("Actual numerical prefix scalar identity is unavailable")
            previous = row["open_ms"]
        feature_sha = fingerprint([row | {"available_at": at} for row in inputs])
        for result in (evaluation, reference):
            feature = result.get("feature")
            if (
                not isinstance(feature, dict)
                or feature.get("input_cutoff") != at
                or feature.get("input_bars_sha256") != feature_sha
            ):
                raise ValueError(
                    "Actual numerical prefix differs from its evaluated feature identity"
                )
        windows = [
            tuple(pair) for pair in original["finding"]["native_proof"]["disclosed_intervals"]
        ] + [(inputs[0]["open_ms"] / 1000, (inputs[-1]["close_ms"] + 1) / 1000)]
        bridge._permitted(windows, method_id=method_id)
        identity = fingerprint(inputs)
        window_ids = []
        for index, (start, end) in enumerate(windows):
            window_id = f"role-pattern-numerical:{task['id']}:{identity}:{index}"
            expected = (start, end, "Pattern comparison preparation disclosure")
            old = self.registry.db.execute(
                "SELECT start,end,origin FROM evidence_windows WHERE request_id=?", (window_id,)
            ).fetchone()
            if old is not None and tuple(old) != expected:
                raise ValueError("Original numerical disclosure window identity differs")
            self.registry.db.execute(
                "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,?)", (window_id, *expected)
            )
            window_ids.append(window_id)
        evaluation["input_disclosure"] = {
            "input_count": len(inputs),
            "input_sha256": identity,
            "intervals": windows,
            "window_ids": window_ids,
            "observed_at": at,
        }

    def _current(self, task: dict[str, Any]) -> AutonomousLab:
        finite_outcome = "finite_test" in task["context"] and (
            task["stage"] == "outcome"
            or (task["stage"] == "submit" and self._finite_accepted(task))
        )
        if finite_outcome:
            with self.registry.lock:
                self.finite.binding(task)
        elif not self._same_mode(task):
            raise InputWait("Retained task belongs to a different role execution mode")
        if not finite_outcome:
            self._finite_current(task)
        if task.get("_claimed_owner"):
            with self.registry.lock:
                owned = self.registry.db.execute(
                    "SELECT 1 FROM role_tasks WHERE id=? AND owner=? AND lease_until>=?",
                    (task["id"], self.owner, time.time()),
                ).fetchone()
            if not owned:
                raise InputWait(
                    "Task ownership expired or changed; retained completion awaits its owner"
                )
        c = self.controller
        if c is None:
            raise InputWait("Paper controller unavailable; task retained")
        if (
            task["stage"] in {"idea", "review", "followup"}
            and task["context"]["contract"] != self._contract_version()
        ):
            raise ValueError("Frozen role contract changed; replan before new inference")
        lab = c.paper.state.get("autonomous_lab")
        if (
            self.paper_pilot
            and not finite_outcome
            and (c.paper.state.get("paused") or (lab and lab.get("proposals_paused")))
        ):
            raise InputWait("Operator pause prevents experimental pilot advancement")
        if finite_outcome or task["stage"] in {"outcome", "followup", "complete"}:
            # Historical results remain researchable after policy/parent changes.
            if task["stage"] == "followup":
                self._pattern_task_method(task)
            return c
        if not lab or fingerprint(lab["policy"]) != task["context"]["policy_sha256"]:
            raise ValueError("Paper policy changed after dispatch; create a new scoped task")
        if task["context"].get("contract") == PATTERN_VERSION:
            saved = task["context"]["pattern_comparison"]
            learning = task["context"].get("pattern_learning")
            method_id = self._pattern_task_method(task)
            research_only = bool(learning and learning["dispatch_available"] is False)
            if learning is not None:
                self._pattern_learning_admission(
                    learning,
                    task["context"]["selection_authority"],
                    task["context"]["policy"],
                    task_proposal=task["proposal"] if task["stage"] == "submit" else None,
                )()
            original = self._pattern_original(
                {
                    "request_id": saved["preparation_request_id"],
                    "finding_sha256": saved["finding_sha256"],
                    "issued_bundle_sha256": saved["issued_bundle_sha256"],
                },
                research_only=research_only,
                method_id=method_id,
            )
            self._pattern_ready(task["context"]["policy"], time.time())
            if research_only and (task["proposal"] is not None or task["stage"] != "idea"):
                raise InputWait("Used fixed p0 is read-only; no new experiment dispatch is offered")
            used = self._pattern_admission(
                self._pattern_method(original, research_only=research_only),
                time.time(),
                task["proposal"],
                research_only=research_only,
            )
            if learning is not None:
                if used == learning["dispatch_available"] and not (
                    "pattern_method" in task["context"]
                    and task["stage"] == "submit"
                    and task["proposal"] is not None
                ):
                    raise InputWait("Fixed comparison dispatch availability changed")
                self._pattern_learning_body(learning)
            bars = c.paper.history["BTCUSD"][-600:]
            self._pattern_permitted(
                original,
                bars[0].open_ms / 1000,
                (bars[-1].close_ms + 1) / 1000,
                research_only=research_only,
                method_id=method_id,
            )
        if task["proposal"]:
            finance.validate_parent(c.paper.state, LabProposal.model_validate(task["proposal"]))
        if task["context"]["contract"] != self._contract_version():
            raise ValueError("Frozen capability contract changed; replan this task")
        return c

    @staticmethod
    def _pattern_shared_outcome(prior: dict[str, Any], current: dict[str, Any]) -> None:
        """Reference only exactly equal facts in this same packet's scored e1 body.

        The original e5 body is e1.body overlaid by its named fields, removing
        body_remove keys. samples_overlay_common=true applies its execution_samples
        and common dictionary as bases for their named differences and removals.
        Complete original event hashes remain independent; no score is recomputed.
        """
        body = copy.deepcopy(prior["body"])
        base = current["body"]
        samples, base_samples = body.get("execution_samples"), base.get("execution_samples")
        if (
            isinstance(samples, dict)
            and isinstance(base_samples, dict)
            and isinstance(samples.get("common"), dict)
            and isinstance(base_samples.get("common"), dict)
        ):
            common, base_common = samples["common"], base_samples["common"]
            samples["common"] = {
                key: value
                for key, value in common.items()
                if key not in base_common or fingerprint(value) != fingerprint(base_common[key])
            }
            body["execution_samples"] = {
                key: value
                for key, value in samples.items()
                if key == "common"
                or key not in base_samples
                or fingerprint(value) != fingerprint(base_samples[key])
            }
            prior["samples_overlay_common"] = True
            removed = sorted(set(base_common) - set(common))
            if removed:
                prior["sample_common_remove"] = removed
            removed = sorted(set(base_samples) - set(samples))
            if removed:
                prior["samples_remove"] = removed
        prior["body"] = {
            key: value
            for key, value in body.items()
            if key not in base or fingerprint(value) != fingerprint(base[key])
        }
        prior["body_base"] = "e1.body"
        removed = sorted(set(base) - set(body))
        if removed:
            prior["body_remove"] = removed

    def _packet(self, task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        role, packet = self._base_packet(task)
        version = task["context"].get("contract", VERSION)
        method_id = self._pattern_task_method(task)
        method_policy = "pattern_method" in task["context"]
        learning_policy = task["context"].get("selection_authority", {}).get("question_policy") in {
            PATTERN_LEARNING_QUESTION_POLICY,
            PATTERN_METHOD_QUESTION_POLICY,
        }
        if version in (TOOL_REQUEST_VERSION, CAPABILITY_VERSION, PATTERN_VERSION):
            packet["contract"] = version
            if role == "researcher":
                packet["tool_inventory"] = {
                    "strategy_family": sorted(
                        {v["family"] for v in packet["capabilities"].values()}
                        | (
                            {v["reference_family"] for v in packet["capabilities"].values()}
                            if version == PATTERN_VERSION
                            else set()
                        )
                    ),
                    "feature": sorted(
                        {
                            key
                            for feature in task["context"]["tool_evidence"]["features"].values()
                            for key in feature
                        }
                    ),
                    "analysis_tool": ["matched_comparison", "reviewed_rule_inputs"],
                }
                if learning_policy:
                    fixed = task["context"]["fixed_comparison"][method_id]
                    packet["tool_inventory"]["strategy_family"] = sorted(
                        (
                            fixed[label].get("proposal")
                            or fixed[label]["proposal_without_bundle_digest"]
                        )["strategy"]["family"]
                        for label in ("candidate", "reference")
                    )
        knowledge = task["context"].get("knowledge")
        if task["context"].get("execution_mode") == PAPER_RESEARCH_PILOT and knowledge is not None:
            raise ValueError("Paper pilot packet cannot include separately authorized RAG inputs")
        if knowledge is not None:
            if self.knowledge is None:
                raise ValueError("RAG source owner unavailable; retained packet is not regenerated")
            self.knowledge.check_passages(knowledge["passages"], external=False)
            packet["retrieval_contract"] = RETRIEVAL_CONTRACT
            packet["knowledge"] = knowledge
            for passage in knowledge["passages"]:
                packet["evidence"][passage["citation"]] = passage
        if "selection_authority" in task["context"]:
            packet["selection_authority"] = task["context"]["selection_authority"]
        if "question_selection" in task["context"]:
            packet["question_selection"] = task["context"]["question_selection"]
        if version == PATTERN_VERSION:
            fixed = task["context"]["fixed_comparison"][method_id]
            if (
                learning_policy
                and task["context"]["lesson"] is not None
                and task["stage"] != "followup"
            ):
                packet["fixed_comparison"] = {
                    method_id: {
                        "candidate": (
                            self._pattern_method_identity(method_id)["candidate"]
                            if method_policy
                            else task["context"]["lesson"]["context"]["family"]
                        ),
                        "reference": (
                            fixed["reference"].get("proposal")
                            or fixed["reference"]["proposal_without_bundle_digest"]
                        )["strategy"]["family"],
                        "detail_sha256": fingerprint(fixed),
                    }
                }
            else:
                packet["fixed_comparison"] = {
                    method_id: (
                        pattern_followup_controls(fixed, task["proposal"])
                        if task["stage"] == "followup"
                        else pattern_controls(fixed)
                    )
                }
            if task["stage"] == "followup":
                packet["evidence"]["e1"] = pattern_followup_outcome(task["result"]["outcome"])
            packet["evidence"]["e3"] = pattern_packet(task["context"]["pattern_comparison"])
            if learning_policy:
                learning = task["context"]["pattern_learning"]
                prior = task["context"]["lesson"]
                # The full implementation identity remains covered by the exact
                # retained fixed-controls digest, rather than repeated source prose.
                packet["fixed_comparison"][method_id].pop("source_sha256", None)
                packet["evidence"]["e5"] = {
                    "state": learning["state"],
                    "lesson": learning["lesson"],
                }
                if method_policy:
                    packet["evidence"]["e5"]["method_transition"] = {
                        "previous": learning["previous_method"]["method_id"]
                        if learning["previous_method"]
                        else None,
                        "next": method_id,
                        "method_policy_sha256": pattern_method_policy_sha(),
                    }
                if learning["predecessor_task"] is not None:
                    packet["evidence"]["e5"]["predecessor_task"] = learning["predecessor_task"]
                if learning.get("predecessor_observation") is not None:
                    observation = copy.deepcopy(learning["predecessor_observation"])
                    result = observation.get("result")
                    if result and result.get("outcome") is not None:
                        result["outcome"] = pattern_followup_outcome(result["outcome"])
                    packet["evidence"]["e5"]["predecessor_observation"] = observation
                if prior is not None:
                    packet["evidence"]["e5"].update(
                        source_task=learning["source_task"],
                        cutoff=learning["cutoff"],
                        dispatch_available=learning["dispatch_available"],
                        outcome=pattern_followup_outcome(prior["source"]),
                        cost_policy_sha256=fingerprint(prior["context"]["cost_policy"]),
                        data_basis=prior["context"]["data_basis"],
                        unknowns=prior["unknowns"],
                        support=prior["support"],
                    )
                    if learning["predecessor_task"] == learning["source_task"]:
                        packet["evidence"]["e5"].pop("predecessor_task", None)
                    # Remove repeated explanatory prose, never scored fields.
                    scored = packet["evidence"]["e5"]["outcome"]
                    scored.pop("detail")
                    if (
                        "execution_samples" not in prior["source"]["body"]
                        and "execution_samples" in scored["body"]
                    ):
                        scored["body"]["execution_samples"]["encoding"] = "sample=common+named"
                    packet["evidence"]["e3"].pop("detail")
                    packet.pop("scope", None)
                    if prior["unknowns"] == [
                        "Recognition, lateness, execution, exit and size causes "
                        "require linked diagnostics",
                        "Related windows are correlated; retrieval frequency "
                        "is not statistical support",
                        "No incumbent qualification or independent market benefit follows",
                    ]:
                        packet["evidence"]["e5"]["unknowns"] = [
                            "Recognition/lateness/execution/exit/size causes need diagnostics",
                            "Correlated windows; retrieval is not statistical support",
                            "No qualification or independent market benefit",
                        ]
            if role == "reviewer":
                evaluation = task["evaluation"]
                packet["evidence"]["e0"] = {
                    "method_sha256": fingerprint(task["proposal"]),
                    "issued_bundle_sha256": task["context"]["issued"]["sha256"],
                }
                packet["evidence"]["e1"] = {
                    "status": evaluation["status"],
                    "evaluated_at": evaluation["evaluated_at"],
                    "expires_at": evaluation["expires_at"],
                    "feature": pattern_feature(evaluation["feature"]),
                    "reference_feature": pattern_feature(evaluation["reference"]["feature"]),
                    "input_count": evaluation["input_count"],
                    "input_sha256": evaluation["input_sha256"],
                    "detail_sha256": fingerprint(evaluation),
                    "financial_authority": False,
                }
            if "question_selection" in packet:
                packet["question_selection"] = {
                    key: packet["question_selection"][key] for key in ("selection_sha", "method")
                }
            if "e2" in packet["evidence"]:
                causal = task["context"]["tool_evidence"]
                packet["evidence"]["e2"] = {
                    "features": {
                        key: pattern_feature(value) for key, value in causal["features"].items()
                    },
                    "reference_features": {
                        key: pattern_feature(value)
                        for key, value in causal["reference_features"].items()
                    },
                    "executable_book": {
                        key: causal["executable_book"][key]
                        for key in ("observed", "bids", "asks")
                        if key in causal["executable_book"]
                    },
                    "request_data_conditions": {
                        key: {"kind": v["kind"]}
                        for key, v in task["context"]["wait_requirements"].items()
                    },
                }
            packet["question"] = "Test fixed p0 prospectively; refute benefit on inadequate "
            packet["question"] += "coverage or nonpositive matched net after-cost delta."
            if (
                task["context"].get("selection_authority", {}).get("question_policy")
                == PATTERN_LEARNING_QUESTION_POLICY
            ):
                packet["question"] = (
                    "Assess fixed p0: refute benefit on inadequate coverage or "
                    "nonpositive after-cost delta."
                )
            if task["context"].get("pattern_learning", {}).get("dispatch_available") is False:
                packet["question"] = (
                    "Assess new event using prior outcome. Used p0 unavailable; "
                    "no_change or typed wait."
                )
                # The same false dispatch fact is carried explicitly in e2.
                packet["evidence"]["e5"].pop("dispatch_available", None)
                # No method is offered. Its complete current evaluation and
                # executable snapshot remain in the exact retained context;
                # these references do not advertise a dispatch-ready feature.
                causal = task["context"]["tool_evidence"]
                # e3.detail_sha256 already covers this original preparation,
                # including its issued-bundle identity; there is no offered p0.
                packet["evidence"].pop("e0", None)
                packet["evidence"]["e2"] = {
                    "current_inputs": {
                        key: fixed["current_inputs"][key] for key in ("count", "sha256", "cutoff")
                    },
                    "evaluation_sha256": fingerprint(causal),
                    "dispatch_available": False,
                    "request_data_conditions": {
                        key: {"kind": value["kind"]}
                        for key, value in task["context"]["wait_requirements"].items()
                    },
                }
            if method_policy:
                # Exact source/controls hashes retain the repeated scope prose.
                # Numerical facts and every original scored field remain present.
                packet.pop("scope", None)
                if "question_selection" in packet:
                    packet["question_selection"].pop("method", None)
                packet["evidence"]["e3"].pop("detail", None)
                packet["evidence"]["e5"]["method_transition"].pop("method_policy_sha256")
                # Its exact value is already in the mandatory seven-field authority.
                if task["context"]["lesson"] is not None:
                    native = packet["evidence"]["e3"]
                    native["coverage_columns"] = ["frame", "observed", "expected", "missing"]
                    native["native_proof"] = {
                        "verified": native["native_proof"]["archive_verified"],
                        "recognition_rows": native["native_proof"]["recognition_rows"],
                        "contiguous": native["native_proof"]["contiguous_relevant_window"],
                    }
                    native.pop("detail_sha256")  # Original finding SHA covers native facts.
                    native["original_event"]["reason_sha256"] = fingerprint(
                        native["original_event"].pop("reason")
                    )
                    # Keep current eligible/reason/ATR facts. Two feature hashes are
                    # replaced by the exact complete captured numerical snapshot SHA.
                    current = packet["evidence"].get("e2")
                    if current and "features" in current:
                        for group in ("features", "reference_features"):
                            for feature in current[group].values():
                                feature.pop("detail_sha256")
                        current["detail_sha256"] = fingerprint(task["context"]["tool_evidence"])
                    comparison = packet["fixed_comparison"][method_id]
                    if packet["capabilities"]:
                        comparison.pop("candidate")
                        comparison.pop("reference")
                    prior_packet = packet["evidence"]["e5"]
                    if task["stage"] == "idea":
                        # The exact selection SHA retains its issued bundle/source;
                        # this stage offers only server-captured capability keys.
                        packet["evidence"].pop("e0", None)
                    if prior_packet["cost_policy_sha256"] != fingerprint(task["context"]["policy"]):
                        raise InputWait("Prior and current fixed cost policy differ")
                    prior_packet.pop("cost_policy_sha256")
                    prior_packet["same_cost_policy"] = True
                    if prior_packet["unknowns"] == [
                        "Recognition/lateness/execution/exit/size causes need diagnostics",
                        "Correlated windows; retrieval is not statistical support",
                        "No qualification or independent market benefit",
                    ]:
                        prior_packet["unknowns"] = [
                            "Unresolved recognition/lateness/execution/exit/size",
                            "Correlated; retrieval is not support",
                            "No qualification/independent benefit",
                        ]
                    prior_packet["outcome"].pop("id")
                    prior_packet["outcome"].pop("at")
                    # The full original event identity remains source_sha256;
                    # all scored body fields/types stay losslessly recoverable.
                    if prior_packet.get("dispatch_available") is True:
                        prior_packet.pop("dispatch_available")
                    if (
                        current
                        and current.get("executable_book", {}).get("observed")
                        == (prior_packet["cutoff"])
                    ):
                        prior_packet.pop("cutoff")
                if task["stage"] == "followup":
                    packet["evidence"]["e1"].pop("detail", None)
                    if task["context"]["lesson"] is not None:
                        # Exact selection/fixed-controls hashes retain these repeated
                        # preparation references; e1 retains the actual proposal ID.
                        packet["evidence"].pop("e0", None)
                        comparison = packet["fixed_comparison"][method_id]
                        comparison.pop("detail")
                        if comparison["proposal_id"] != packet["evidence"]["e1"]["body"].get(
                            "proposal_id"
                        ):
                            raise InputWait(
                                "Executed fixed method and scored proposal identity differ"
                            )
                        comparison.pop("proposal_id")
                        packet["evidence"]["e1"].pop("id")
                        packet["evidence"]["e1"].pop("at")
                        samples = packet["evidence"]["e1"]["body"].get("execution_samples")
                        if "execution_samples" not in task["result"]["outcome"]["body"] and samples:
                            samples["encoding"] = "common+named"
                        prior = packet["evidence"]["e5"]
                        prior_samples = prior["outcome"]["body"].get("execution_samples")
                        if "execution_samples" not in task["context"]["lesson"]["source"][
                            "body"
                        ] and isinstance(prior_samples, dict):
                            prior_samples["encoding"] = "common+named"
                        if fingerprint(prior.get("cutoff")) == fingerprint(
                            packet["evidence"]["e3"]["verification_at"]
                        ):
                            # The exact same causal decision cutoff is already e3's
                            # verification_at; retain distinct values when different.
                            prior.pop("cutoff")
                        self._pattern_shared_outcome(
                            packet["evidence"]["e5"]["outcome"], packet["evidence"]["e1"]
                        )
                packet["question"] = f"Independent {method_id}: gaps or net after costs<=0."
                if not task["context"]["pattern_learning"]["dispatch_available"]:
                    packet["question"] = (
                        "All fixed methods used; inspect exact prior and typed wait."
                    )
            for capability in packet["capabilities"].values():
                capability.pop("lookback", None)
                capability.pop("reference_lookback", None)
        return role, packet

    def _base_packet(self, task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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
        evidence: dict[str, Any] = {
            "e0": {"issued_bundle_sha256": context["issued"]["sha256"]}
            if context.get("contract") == PATTERN_VERSION
            else bundle_summary(context["issued"]["bundle"])
        }
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
        if context.get("contract", VERSION) == CAPABILITY_VERSION:
            # These are the already issued method's fixed controls, not new
            # model-selectable parameters. Old v5/v6 wire packets stay unchanged.
            controls = (
                "volume_multiple",
                "holding_horizon",
                "exit_seconds",
                "progress_seconds",
                "stop_atr",
                "input_version",
            )
            for key, value in context["catalog"].items():
                capabilities[key]["fixed_comparison"] = {
                    "strategy": {field: value["strategy"][field] for field in controls},
                    "reference": {field: value["reference"][field] for field in controls},
                    "strategy_sha256": value["strategy_sha256"],
                    "reference_sha256": value["reference_sha256"],
                    "parameter_selection": "server_frozen_only",
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

    async def development_answer(self, identity: str, transport: Any) -> Idea | Review:
        """Answer one normal frozen packet, without advancing its operating stage."""
        if self.enabled or (self.activation and self.activation()):
            raise ValueError("Development answers require operating research disabled")
        task = self.get(identity)
        if "selection_authority" in task["context"]:
            raise ValueError("Autonomous selection cannot use a retained development authorization")
        if task["stage"] not in {"idea", "review", "followup"} or (
            task["status"] not in {"queued", "waiting"}
            or task.get("owner")
            or task.get("archive_reference")
        ):
            raise ValueError("Development requires an idle retained role question")
        role, packet = self._packet(task)
        # Development is retained by ordinary history/cost accounting, but cannot
        # become _answer's qualified operating answer for this task/stage.
        stage = "development_" + task["stage"]
        with self.registry.lock:
            previous = self.registry.db.execute(
                "SELECT * FROM role_attempts WHERE task=? AND stage=? "
                "ORDER BY attempt DESC LIMIT 1",
                (identity, stage),
            ).fetchone()
        if previous:
            if fingerprint(json.loads(previous["packet"])) != fingerprint(packet):
                raise ValueError(
                    "Completed development answer belongs to a different frozen packet"
                )
            if not previous["response"]:
                raise ValueError("Previous development completion unknown; no invisible retry")
            response = json.loads(previous["response"])
            if response.get("kind") == "development_transport_failure" or response.get(
                "transport_failure"
            ):
                raise ValueError("Retained development transport failed; no invisible retry")
            if not response.get("complete"):
                raise ValueError("Retained development response is incomplete")
            return validate(
                role, response["answer"], packet, contract_version=packet.get("contract", VERSION)
            )
        profile = await asyncio.to_thread(transport.development_admit, role)
        if profile.get("development_only") is not True:
            raise ValueError("Development needs its explicitly frozen separate profile")
        preflight = getattr(transport, "preflight", None)
        if callable(preflight):
            await asyncio.to_thread(preflight, role, packet, profile)
        started = time.time()
        with self.registry.transaction():
            current = self.registry.db.execute(
                "SELECT * FROM role_tasks WHERE id=?", (identity,)
            ).fetchone()
            if (
                not current
                or current["stage"] != task["stage"]
                or current["owner"]
                or (
                    current["status"] not in {"queued", "waiting"}
                    or current["archive_reference"]
                    or fingerprint(json.loads(current["context"])) != fingerprint(task["context"])
                )
            ):
                raise ValueError("Role question changed before development admission")
            used = self.registry.db.execute(
                "SELECT coalesce(sum(wall_reserved),0),coalesce(sum(tokens_reserved),0) "
                "FROM role_attempt_allowances WHERE started>=? AND actor IS NULL",
                (started - 3600,),
            ).fetchone()
            if used[0] + profile["timeout_seconds"] > profile["hourly_wall_seconds"] or (
                used[1] + profile["token_allowance"] > profile["hourly_tokens"]
            ):
                raise InputWait("Existing role allowance constrains this development attempt")
            self.registry.db.execute(
                "INSERT INTO role_attempts(task,stage,attempt,started,status,profile,packet,"
                "wall_reserved,tokens_reserved) VALUES(?,?,1,?,'running',?,?,?,?)",
                (
                    identity,
                    stage,
                    started,
                    json.dumps(profile),
                    json.dumps(packet),
                    profile["timeout_seconds"],
                    profile["token_allowance"],
                ),
            )
        try:
            work = asyncio.create_task(asyncio.to_thread(transport.infer, role, packet, profile))
            cancelled = None
            try:
                response = await asyncio.shield(work)
            except asyncio.CancelledError as interrupted:
                cancelled = interrupted
                if hasattr(transport, "cancel"):
                    transport.cancel()
                # Retain a response that won the race with cancellation, or wait
                # for owned termination before releasing this attempt's costs.
                response = await work
            body = json.dumps(response, sort_keys=True, allow_nan=False)
            if len(body.encode()) > 32768:
                raise ValueError("Development final output exceeds the retained answer bound")
            with self.registry.transaction():
                saved = self.registry.db.execute(
                    "UPDATE role_attempts SET response=?,finished=?,status='answered',"
                    "wall_reserved=max(wall_reserved,?-started) "
                    "WHERE task=? AND stage=? AND attempt=1",
                    (body, time.time(), time.time(), identity, stage),
                )
                if saved.rowcount != 1:
                    raise ValueError("Development answer has no retained attempt; repair required")
            if not response.get("complete"):
                raise ValueError("Original development response is incomplete")
            if cancelled:
                raise cancelled
            return validate(
                role, response["answer"], packet, contract_version=packet.get("contract", VERSION)
            )
        except BaseException as exc:
            failure_body = None
            if isinstance(exc, DevelopmentTransportFailure):
                failure_body = json.dumps(exc.receipt, sort_keys=True, allow_nan=False)
                if exc.response is not None:
                    # Cleanup must not discard a returned original answer. Its failure
                    # annotation withholds success while retaining that exact answer.
                    original = json.dumps(exc.response, sort_keys=True, allow_nan=False)
                    if len(original.encode()) <= 32768:
                        # The model answer keeps its existing 32-KiB limit. The
                        # supervisor's <=2-KiB failure receipt has its own bound;
                        # adding that metadata cannot erase a bounded original.
                        failure_body = json.dumps(
                            exc.response | {"transport_failure": exc.receipt},
                            sort_keys=True,
                            allow_nan=False,
                        )
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE role_attempts SET finished=?,status='failed',reason=?,"
                    "wall_reserved=max(wall_reserved,?-started),response=coalesce(response,?) "
                    "WHERE task=? AND stage=? AND attempt=1",
                    (
                        time.time(),
                        type(exc).__name__ + ": " + str(exc)[:400],
                        time.time(),
                        failure_body,
                        identity,
                        stage,
                    ),
                )
            raise

    async def _answer(self, task: dict[str, Any]) -> Idea | Review:
        if not await asyncio.to_thread(self._same_mode, task):
            raise ValueError("Retained task belongs to a different role execution mode")
        role, packet = self._packet(task)
        with self.registry.lock:
            previous = self.registry.db.execute(
                "SELECT * FROM role_attempts WHERE task=? AND stage=? ORDER BY attempt "
                "DESC LIMIT 1",
                (task["id"], task["stage"]),
            ).fetchone()
        if previous and previous["response"]:
            if self.paper_pilot and previous["status"] != "answered":
                raise ValueError("Retained failed pilot answer cannot authorize stage advancement")
            if fingerprint(json.loads(previous["packet"])) != fingerprint(packet):
                raise ValueError("Completed answer belongs to a different frozen packet")
            return validate(
                role,
                json.loads(previous["response"])["answer"],
                packet,
                contract_version=packet.get("contract", VERSION),
            )
        if previous and previous["status"] != "retry_authorized":
            # An unknown completion is never an invisible retry for a preferred verdict.
            raise ValueError(
                "Previous inference completion unknown; review retained attempt before "
                "explicit retry"
            )
        if not self._activation_enabled() or self.transport is None:
            raise InputWait(
                "Role inference disabled; selected policy and explicit activation required"
            )
        try:
            profile = await asyncio.to_thread(self.transport.admit, role)
        except Exception as exc:
            raise InputWait("Required role is unavailable: " + str(exc)[:300]) from exc
        if self.paper_pilot:
            await asyncio.to_thread(self._current, task)
        preflight = getattr(self.transport, "instance_preflight", None) or getattr(
            self.transport, "preflight", None
        )
        if callable(preflight):
            await asyncio.to_thread(preflight, role, packet, profile)
        started = time.time()
        timeout = profile["timeout_seconds"]
        attempt_number = previous["attempt"] + 1 if previous else 1
        with self.registry.transaction():
            owned = self.registry.db.execute(
                "SELECT 1 FROM role_tasks WHERE id=? AND owner=? AND lease_until>=?",
                (task["id"], self.owner, started),
            ).fetchone()
            if not owned:
                raise InputWait("Role ownership changed before inference; no new attempt")
            finite = self._finite_current(task)
            reservation = None
            if finite is not None:
                saved_finite = self.finite.binding(task)
                if self.finite.count(saved_finite) >= finite["finite_test"]["max_requests"]:
                    raise InputWait("Finite lifetime request allowance is exhausted")
                reservation = self._finite_reservation(
                    saved_finite, task["id"], task["stage"], attempt_number, packet
                )
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
                "UPDATE role_tasks SET lease_until=?,status='running' WHERE id=? AND owner=?",
                (started + timeout + 30, task["id"], self.owner),
            )
        try:
            cancelled = None
            infer = self.transport.infer
            arguments: tuple[Any, ...] = (role, packet, profile)
            if reservation is not None:
                infer = getattr(self.transport, "infer_reserved", None)
                if not callable(infer):
                    raise ValueError("Finite transport requires verified reserved dispatch")
                self.transport.finite_request_verifier = self.validate_finite_request
                arguments += (reservation,)
            if self.paper_pilot:
                work = asyncio.create_task(asyncio.to_thread(infer, *arguments))
                try:
                    response = await asyncio.shield(work)
                except asyncio.CancelledError as interrupted:
                    cancelled = interrupted
                    self.transport.cancel()
                    response = await work  # The transport owns bounded child termination.
            else:
                response = await asyncio.to_thread(infer, *arguments)
            body = json.dumps(response, sort_keys=True, allow_nan=False)
            if len(body.encode()) > 32768:
                raise ValueError("Model final output exceeds the recorded answer bound")
            # Persist before validation or dispatch. A restart reuses the completed answer.
            with self.registry.transaction():
                retained = self.registry.db.execute(
                    "UPDATE role_attempts SET response=?,finished=?,status='answered', "
                    "wall_reserved=max(wall_reserved,?-started) "
                    "WHERE task=? AND stage=? AND attempt=?",
                    (body, time.time(), time.time(), task["id"], task["stage"], attempt_number),
                )
                if retained.rowcount != 1:
                    raise ValueError("Completed answer has no retained attempt; repair required")
                # An expired owner may have reported unknown completion before
                # this immutable receipt arrives. Reconcile that uncertainty,
                # only if no newer attempt/owner/verdict has superseded it.
                self.registry.db.execute(
                    "UPDATE role_tasks SET status='queued',reason=NULL,retry_at=0 "
                    "WHERE id=? AND stage=? AND status='failed' AND owner IS NULL "
                    "AND reason LIKE 'Previous inference completion unknown%' "
                    "AND NOT EXISTS(SELECT 1 FROM role_attempts WHERE task=? "
                    "AND stage=? AND attempt>?)",
                    (task["id"], task["stage"], task["id"], task["stage"], attempt_number),
                )
            if self.paper_pilot and not response.get("complete", True):
                raise ValueError("Original pilot response is incomplete")
            if cancelled:
                raise cancelled
            return validate(
                role, response["answer"], packet, contract_version=packet.get("contract", VERSION)
            )
        except BaseException as exc:
            if not isinstance(exc, Exception) and not (
                self.paper_pilot and isinstance(exc, asyncio.CancelledError)
            ):
                raise  # Default transport cancellation retains unknown completion.
            failure_body = None
            if isinstance(exc, DevelopmentTransportFailure):
                failure_body = json.dumps(exc.receipt, sort_keys=True, allow_nan=False)
                if exc.response is not None:
                    original = json.dumps(exc.response, sort_keys=True, allow_nan=False)
                    if len(original.encode()) <= 32768:
                        failure_body = json.dumps(
                            exc.response | {"transport_failure": exc.receipt},
                            sort_keys=True,
                            allow_nan=False,
                        )
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE role_attempts SET finished=?,status='failed',reason=?, "
                    "wall_reserved=max(wall_reserved,?-started),response=coalesce(response,?) "
                    "WHERE "
                    "task=? AND stage=? AND attempt=?",
                    (
                        time.time(),
                        str(exc)[:500],
                        time.time(),
                        failure_body,
                        task["id"],
                        task["stage"],
                        attempt_number,
                    ),
                )
            raise

    async def step(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        # Submitted finite outcomes remain observable after pause/expiry. This
        # branch never authorizes another model request or proposal.
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT t.id FROM role_tasks t JOIN role_finite_tasks f ON f.task=t.id "
                "WHERE t.stage='outcome' AND t.status NOT IN ('done','failed') "
                "AND t.retry_at<=? AND (t.owner IS NULL OR t.lease_until<?) "
                "ORDER BY t.updated LIMIT 1",
                (now, now),
            ).fetchone()
            if row is None and self.controller is not None:
                waiting_submits = self.registry.db.execute(
                    "SELECT t.id,t.context,t.proposal FROM role_tasks t "
                    "JOIN role_finite_tasks f ON f.task=t.id WHERE t.stage='submit' "
                    "AND t.status NOT IN ('done','failed') AND t.retry_at<=? "
                    "AND (t.owner IS NULL OR t.lease_until<?) ORDER BY t.updated LIMIT 8",
                    (now, now),
                ).fetchall()
                for pending in waiting_submits:
                    if self._finite_accepted(
                        {
                            "id": pending["id"],
                            "context": json.loads(pending["context"]),
                            "proposal": json.loads(pending["proposal"]),
                        }
                    ):
                        row = pending
                        break
        finite_outcome = row is not None
        if not finite_outcome:
            try:
                finite = await asyncio.to_thread(self._finite_current)
                pilot_grant_id = await asyncio.to_thread(self._pilot_grant_id)
                selection_json = await asyncio.to_thread(self._selection_json)
            except InputWait:
                return False
        with self.registry.transaction():
            if not finite_outcome:
                row = self.registry.db.execute(
                    "SELECT id FROM role_tasks WHERE status NOT IN ('done','failed') AND "
                    "stage NOT IN ('data_wait','tool_wait') "
                    "AND coalesce(json_extract(context,'$.execution_mode'),'qualified_roles')=? "
                    "AND coalesce(json_extract(context,'$.contract'),'reviewed-rule-role-v5')=? "
                    "AND (? IS NULL OR json_extract(context,'$.pilot_grant_id')=?) "
                    "AND (json_type(context,'$.selection_authority') IS NULL "
                    "OR json_extract(context,'$.selection_authority')=json(?)) "
                    "AND (?=0 OR EXISTS(SELECT 1 FROM role_finite_tasks f "
                    "WHERE f.task=role_tasks.id AND f.grant_id=?)) "
                    "AND retry_at<=? AND (owner IS NULL OR lease_until<?) ORDER BY updated LIMIT 1",
                    (
                        self.execution_mode,
                        self._contract_version(),
                        pilot_grant_id,
                        pilot_grant_id,
                        selection_json,
                        int(finite is not None),
                        finite["grant_id"] if finite is not None else None,
                        now,
                        now,
                    ),
                ).fetchone()
            if row:
                claimed = self.registry.db.execute(
                    "UPDATE role_tasks SET owner=?,lease_until=? WHERE id=? "
                    "AND (owner IS NULL OR lease_until<?)",
                    (self.owner, time.time() + 630, row["id"], now),
                ).rowcount
                if not claimed:
                    row = None
        if not row:
            return False
        task = self.get(row["id"])
        task["_claimed_owner"] = self.owner
        try:
            c = await asyncio.to_thread(self._current, task)
            admitted = (
                True
                if finite_outcome
                else (
                    await asyncio.to_thread(self._admitted)
                    if self.paper_pilot
                    else self._admitted()
                )
            )
            if not admitted and not finite_outcome:
                raise InputWait("Optional role work yields to financial processing/resource guard")
            stage = task["stage"]
            if stage in {"data_wait", "tool_wait"}:
                return False  # Only a new eligible source/event resumes this dependency.
            if stage in {"idea", "review", "followup"}:
                answer = await self._answer(task)
                await asyncio.to_thread(self._current, task)
                if self.paper_pilot and (
                    not self._activation_enabled() or not await asyncio.to_thread(self._admitted)
                ):
                    raise InputWait(
                        "Paper pilot admission or activation changed; completed answer retained"
                    )
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
                elif isinstance(answer, IdeaV6) and answer.action == "request_tool":
                    self._update(
                        task,
                        "tool_wait",
                        "waiting",
                        result=(task["result"] or {}) | answer.model_dump(),
                        reason="Requested tool awaits implementation review; nothing installed",
                    )
                elif stage == "followup":
                    changed = self._update(
                        task,
                        "complete",
                        "done",
                        result={
                            **task["result"],
                            "followup": answer.model_dump(),
                            "support": "Recorded comparison; annotation grants no new P/L",
                        },
                    )
                    if changed:
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
                if task["context"]["contract"] == PATTERN_VERSION:
                    proposal = LabProposal.model_validate(task["proposal"])
                    reference = LabProposal.model_validate(
                        {
                            **proposal.model_dump(),
                            "strategy": proposal.reference.model_dump(),
                            "reference": proposal.strategy.model_dump(),
                        }
                    )
                    reference_evaluation = await asyncio.to_thread(c.evaluate, reference, now)
                    if reference_evaluation.pop("inputs") != evaluation["inputs"]:
                        raise ValueError(
                            "Current candidate/reference numerical input identities differ"
                        )
                    evaluation["reference"] = reference_evaluation
                    evaluation["pattern_source"] = {
                        key: task["context"]["pattern_comparison"][key]
                        for key in (
                            "finding_sha256",
                            "issued_bundle_sha256",
                            "preparation_request_id",
                        )
                    }
                    if "pattern_method" in task["context"]:
                        evaluation["pattern_method"] = task["context"]["pattern_method"]
                self._update(task, "archive_evaluation", evaluation=evaluation)
            elif stage == "archive_evaluation":
                await self._owned(self._archive_evaluation, task)
            elif stage == "submit":
                try:
                    existing = c.inbox.get(task["proposal"]["request_id"])
                except ValueError:
                    existing = None
                if existing and fingerprint(existing["body"]) != fingerprint(task["proposal"]):
                    raise ValueError("Proposal acknowledgment identity differs")
                if not existing and not c.inbox.has_capacity():
                    raise InputWait("Ordinary paper inbox is full; retain the approved proposal")
                proposal = LabProposal.model_validate(task["proposal"])
                if "finite_test" in task["context"]:
                    if self._finite_accepted(task):
                        submitted = existing
                    else:
                        submitted = c.submit(
                            proposal, now, _finite_scope=self.finite_proposal(task, proposal)
                        )
                else:
                    submitted = existing or c.submit(proposal, now)
                if submitted is None:
                    raise ValueError("Accepted proposal acknowledgment is unavailable")
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
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self._update(
                task,
                task["stage"],
                "waiting",
                reason="Paper database unavailable; saved stage retained for retry",
                retry_at=now + 30,
            )
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

    async def _owned(self, function: Callable[..., Any], *args: Any) -> Any:
        """Drain native archive/maintenance work before shared owners can close."""
        work = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError as cancelled:
            try:
                await work
            except Exception:
                self.reason = (
                    "Owned research work failed during shutdown; original records retained"
                )
            raise cancelled

    def _archive_evaluation(self, task: dict[str, Any]) -> None:
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
        try:
            finite = self._finite_current(task)
            with self.history.storage() as store:
                if self._finite_current() != finite:
                    raise InputWait("Finite scope changed while waiting for archive ownership")
                reference = store.append([packet], time.time())[0]
                if store.reopen(reference) != packet:
                    raise InputWait("Saved role evidence detail verification failed")
        except HistoryUnavailable as exc:
            raise InputWait(str(exc)) from exc
        compact = {k: v for k, v in task["evaluation"].items() if k != "inputs"}
        compact.update(
            input_count=len(task["evaluation"]["inputs"]),
            input_sha256=fingerprint(task["evaluation"]["inputs"]),
            detail_reference=reference,
        )
        # History rollover takes registry then storage. Release storage before this
        # lease-checked publication so evaluation cannot reverse that lock order.
        self._update(task, "review", evaluation=compact)

    def _selection_authority(self) -> dict[str, Any] | None:
        authority = getattr(self.transport, "selection_authority", None)
        return authority() if self.paper_pilot and callable(authority) else None

    def _selection_json(self) -> str:
        return json.dumps(self._selection_authority(), sort_keys=True, allow_nan=False)

    def _selection_room(
        self, authority: dict[str, Any], policy: dict[str, Any], now: float
    ) -> None:
        c = self.controller
        if (
            c is None
            or not self._activation_enabled()
            or not self._admitted()
            or not c.paper.running
            or c.paper.error
        ):
            raise InputWait(
                "Fresh investigation waits for protected paper admission and activation"
            )
        state = c.paper.state
        last_tick = state.get("last_tick", 0)
        if not 0 <= time.time() - last_tick <= 10:
            raise InputWait(
                "Fresh investigation waits for protected paper admission and activation"
            )
        lab = state.get("autonomous_lab")
        if (
            not lab
            or fingerprint(lab["policy"]) != fingerprint(policy)
            or state.get("paused")
            or lab.get("proposals_paused")
        ):
            raise InputWait("Fresh investigation waits for its unchanged unpaused paper policy")
        if authority != self._selection_authority():
            raise InputWait("Fresh investigation selection authority changed")
        broader = (
            authority["question_policy"] == PATTERN_METHOD_QUESTION_POLICY
            and self._finite_current() is None
        )
        pending_condition = "status NOT IN ('done','failed')"
        if broader:
            pending_condition = (
                "(status='failed' OR (status<>'done' AND NOT (status='waiting' "
                "AND owner IS NULL AND lease_until IS NULL AND (stage='tool_wait' "
                "OR (stage IN ('data_wait','outcome') AND retry_at>?)))))"
            )
        pending = self.registry.db.execute(
            "SELECT 1 FROM role_tasks WHERE " + pending_condition + " "
            "AND json_extract(context,'$.execution_mode')=? "
            "AND json_extract(context,'$.contract')=? "
            "AND json_extract(context,'$.pilot_grant_id')=? "
            "AND (json_type(context,'$.selection_authority') IS NULL "
            "OR json_extract(context,'$.selection_authority')=json(?)) LIMIT 1",
            (
                *((now,) if broader else ()),
                PAPER_RESEARCH_PILOT,
                authority["contract_version"],
                authority["grant_id"],
                json.dumps(authority, sort_keys=True, allow_nan=False),
            ),
        ).fetchone()
        followup = self.registry.db.execute(
            "SELECT 1 FROM role_followups f JOIN role_tasks t ON t.id=f.task "
            "WHERE f.state='pending' "
            + ("AND f.retry_at<=? " if broader else "")
            + "AND json_extract(t.context,'$.execution_mode')=? "
            "AND json_extract(t.context,'$.contract')=? "
            "AND json_extract(t.context,'$.pilot_grant_id')=? "
            "AND (json_type(t.context,'$.selection_authority') IS NULL "
            "OR json_extract(t.context,'$.selection_authority')=json(?)) LIMIT 1",
            (
                *((now,) if broader else ()),
                PAPER_RESEARCH_PILOT,
                authority["contract_version"],
                authority["grant_id"],
                json.dumps(authority, sort_keys=True, allow_nan=False),
            ),
        ).fetchone()
        if pending or followup:
            raise InputWait(
                "Saved investigation, tool/data wait or mature follow-up takes priority"
            )
        if (
            self.registry.db.execute(
                "SELECT count(*) FROM role_question_selections WHERE created>=?", (now - 86400,)
            ).fetchone()[0]
            >= policy["daily_trials"]
        ):
            raise InputWait("Declared daily fresh-investigation ceiling reached; no new question")

    def _selection_source(self, horizon: str, policy: dict[str, Any], now: float) -> dict[str, Any]:
        assert self.controller is not None
        paper = self.controller.paper
        bars = paper.lab_history(now, horizon)
        spec = RuleSpec.model_validate({"family": "range_reversion", "holding_horizon": horizon})
        observed_frame = paper.control_frames().get("BTCUSD")
        frame = dict(observed_frame) if observed_frame else None
        observed_at = time.time()  # Current executable prerequisite; causal bars still use now.
        book = frame.get("book") if frame else None
        if (
            not fresh_frame(frame, observed_at)
            or not book
            or not book.bids
            or not book.asks
            or any(
                not v.is_finite() or v <= 0 for pair in (book.bids[0], book.asks[0]) for v in pair
            )
            or book.bids[0][0] >= book.asks[0][0]
            or (frame is not None and frame.get("diagnostic_risk_input_valid") is not True)
            or (frame is not None and frame.get("entry_allowed") is not True)
        ):
            raise InputWait("Fresh investigation needs a current usable executable book")
        if (
            len(bars) < spec.timing["warmup_minutes"]
            or bars[-1].close_ms >= now * 1000
            or bars[-1].open_ms + 60000 < paper.ready_at * 1000
            or "BTCUSD" in paper._candle_errors
            or any(b.open_ms - a.open_ms != 60000 for a, b in zip(bars, bars[1:], strict=False))
        ):
            raise InputWait("Fresh investigation needs complete causal coverage after bootstrap")
        feature = reviewed_feature(
            bars, now, spec, policy["execution_profile"], paper.memory_book("BTCUSD")
        )
        excursion, hurdle = feature.get("excursion_bps"), feature.get("modeled_hurdle_bps")
        if (
            feature.get("eligible") is not True
            or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in (excursion, hurdle)
            )
            or float(excursion or 0) <= float(hurdle or 0)
        ):
            raise InputWait("No reviewed range excursion clears its modeled execution-cost hurdle")
        return {
            "method": "r1",
            "horizon": horizon,
            "source_sha": fingerprint([str(b) for b in bars]),
            "source_start": bars[0].open_ms / 1000,
            "source_end": bars[-1].close_ms / 1000,
            "source_count": len(bars),
            "source_basis": paper.state.get("evidence_kind", "observed_public_market"),
            "strategy_sha": fingerprint(spec.model_dump()),
            "reference_sha": fingerprint(
                RuleSpec.model_validate({"holding_horizon": horizon}).model_dump()
            ),
            "excursion_bps": excursion,
            "modeled_hurdle_bps": hurdle,
        }

    def _selection_lesson(
        self, authority: dict[str, Any], policy: dict[str, Any], horizon: str
    ) -> dict[str, Any] | None:
        row = self.registry.db.execute(
            "SELECT l.id,l.sha AS sha256 FROM research_lessons l JOIN role_tasks t ON t.id=l.task "
            "WHERE l.horizon=? AND json_extract(t.context,'$.execution_mode')=? "
            "AND json_extract(t.context,'$.contract')=? "
            "AND json_extract(t.context,'$.pilot_grant_id')=? "
            "AND json_extract(t.context,'$.policy_sha256')=? "
            "AND json_extract(t.context,'$.selection_authority')=json(?) "
            "ORDER BY l.seq DESC LIMIT 1",
            (
                horizon,
                PAPER_RESEARCH_PILOT,
                authority["contract_version"],
                authority["grant_id"],
                fingerprint(policy),
                json.dumps(authority, sort_keys=True, allow_nan=False),
            ),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _pattern_event_identity(finding: dict[str, Any]) -> str:
        selection = finding["selection"]
        return fingerprint(
            {
                "campaign_id": finding["campaign_id"],
                "selection": {
                    k: selection[k] for k in ("symbol", "timeframe", "event_kind", "event_seq")
                },
                "original_event": finding["original_event"],
                "native_input_sha256": finding["native_proof"]["input_window_sha256"],
            }
        )

    def _pattern_source(
        self,
        original: dict[str, Any],
        policy: dict[str, Any],
        now: float,
        *,
        research_only: bool = False,
        learning_policy: bool = False,
        method_id: str = "p0",
    ) -> dict[str, Any]:
        self._pattern_ready(policy, now)
        assert self.controller is not None
        proposal = self._pattern_method(original, research_only=research_only)
        used = self._pattern_admission(proposal, time.time(), research_only=research_only)
        # The original cutoff remains causal while the executable frame uses its
        # current observation clock. This check is input identity, not evaluation.
        inputs: list[dict[str, Any]] = [
            {
                "open_ms": b.open_ms,
                "close_ms": b.close_ms,
                "open": str(b.open),
                "high": str(b.high),
                "low": str(b.low),
                "close": str(b.close),
                "volume": str(b.volume),
            }
            for b in self.controller.paper.history.get("BTCUSD", [])[-600:]
        ]
        source: dict[str, Any] = {
            "method": method_id,
            "horizon": "medium",
            "source_sha": digest(inputs),
            "source_start": inputs[0]["open_ms"] / 1000,
            "source_end": inputs[-1]["close_ms"] / 1000,
            "source_count": len(inputs),
            "source_basis": self.controller.paper.state.get(
                "evidence_kind", "observed_public_market"
            ),
            "strategy_sha": fingerprint(proposal.strategy.model_dump()),
            "reference_sha": fingerprint(proposal.reference.model_dump()),
            "original_event_sha": self._pattern_event_identity(original["finding"]),
            "method_source_sha": fingerprint(original["mapping"]["source_sha256"]),
            "comparison": {
                k: original[k] for k in ("request_id", "finding_sha256", "issued_bundle_sha256")
            },
        }
        if learning_policy:
            source.update(
                dispatch_available=not used,
                dispatch_reason=(
                    f"Equivalent fixed {method_id} was already used; research evidence only, "
                    "no new proposal or financial dispatch"
                    if used
                    else f"Fixed {method_id} remains offered subject to all existing "
                    "admission gates"
                ),
            )
        authority = self._selection_authority()
        if authority and authority["question_policy"] == PATTERN_METHOD_QUESTION_POLICY:
            source["method_identity"] = self._pattern_method_identity(method_id)
            source["used_methods"] = self._pattern_method_used()
        return source

    def _check_pattern_selection(
        self,
        selection: dict[str, Any],
        question: Question,
        policy: dict[str, Any],
        inputs: dict[str, Any],
        catalog: dict[str, Any],
        now: float,
    ) -> None:
        bridge = self.pattern_comparisons
        if bridge is None:
            raise InputWait("Pattern comparison owner is unavailable")
        # Publication only reads the bounded immutable bundle and current minute
        # owner. Archive verification/borrow has already completed outside this lock.
        original = bridge.get(selection["comparison"]["request_id"])
        research_only = selection.get("learning", {}).get("dispatch_available") is False
        if (
            original is None
            or original["status"]
            not in {
                "waiting",
                "research_only" if research_only else "supported",
            }
            or bool(original.get("research_only")) != research_only
        ):
            raise InputWait("Original preparation is unavailable or has a different research mode")
        learning_policy = selection["authority"]["question_policy"] in {
            PATTERN_LEARNING_QUESTION_POLICY,
            PATTERN_METHOD_QUESTION_POLICY,
        }
        method_id = selection["method"]
        if learning_policy:
            self._check_pattern_learning(selection["learning"], question, now, publication=True)
            if selection["authority"]["question_policy"] == PATTERN_METHOD_QUESTION_POLICY:
                self._pattern_method_admission(selection["learning"])
        source = self._pattern_source(
            original,
            policy,
            now,
            research_only=research_only,
            learning_policy=learning_policy,
            method_id=method_id,
        )
        self._pattern_permitted(
            original,
            source["source_start"],
            source["source_end"] + 0.001,
            research_only=research_only,
            method_id=method_id,
        )
        if (
            question.parent is not None
            or (question.lesson is not None and not learning_policy)
            or question.horizon != "medium"
            or question.request_id != "auto-" + selection["selection_sha"][:32]
            or selection["authority"] != self._selection_authority()
            or selection["scope_sha"]
            != fingerprint({"authority": selection["authority"], "policy_sha": fingerprint(policy)})
            or any(selection[key] != value for key, value in source.items())
            or source["source_sha"] != inputs["closed_bar_sha256"]
            or source["source_count"] != inputs["closed_bar_count"]
            or (
                source.get("dispatch_available", True)
                and source["strategy_sha"] != catalog[method_id]["strategy_sha256"]
            )
            or (
                source.get("dispatch_available", True)
                and source["reference_sha"] != catalog[method_id]["reference_sha256"]
            )
            or (source.get("dispatch_available") is False and bool(catalog))
            or original["mapping"]["source_sha256"] != bridge._method_sources()
            or original["current_policy_sha256"] != digest(policy)
        ):
            raise InputWait("Pattern finding, method, policy or current causal input changed")
        if learning_policy:
            self._check_pattern_learning(selection["learning"], question, now, publication=True)

    def _pattern_terminal(
        self,
        identity: str,
        authority: dict[str, Any],
        *,
        records: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Follow only the exact bounded dependency lineage, without changing old answers."""
        seen: set[str] = set()
        original: dict[str, Any] | None = None
        for _ in range(20):
            if identity in seen:
                raise InputWait("Pattern dependency lineage contains a cycle")
            seen.add(identity)
            task = self.get(identity)
            if records is not None:
                with self.registry.lock:
                    row = self._pattern_learning_record(identity)
                    if (
                        row["archive_reference"] != task["archive_reference"]
                        or row["archive_sha256"] != task["archive_sha256"]
                        or row["stage"] != task["stage"]
                        or row["status"] != task["status"]
                        or (
                            row["archive_reference"] is None
                            and any(
                                (json.loads(row[key]) if row[key] else None) != task[key]
                                for key in ("context", "proposal", "result")
                            )
                        )
                    ):
                        raise InputWait("Predecessor storage changed during original recovery")
                    records.append({"task": identity, "sha256": fingerprint(row)})
            context = task["context"]
            if (
                context.get("contract") != PATTERN_VERSION
                or context.get("selection_authority") != authority
            ):
                raise InputWait("Pattern dependency lineage authority differs")
            preparation = context.get("pattern_comparison")
            if not isinstance(preparation, dict):
                raise InputWait("Pattern dependency lineage preparation is unavailable")
            proof = {
                key: preparation[key]
                for key in ("preparation_request_id", "finding_sha256", "issued_bundle_sha256")
            }
            if original is None:
                original = proof
            elif proof != original:
                raise InputWait("Pattern dependency lineage original preparation differs")
            with self.registry.lock:
                children = self.registry.db.execute(
                    "SELECT id FROM role_tasks WHERE "
                    "json_extract(context,'$.predecessor_task')=? ORDER BY id LIMIT 2",
                    (identity,),
                ).fetchall()
            if not children:
                return task
            if (
                len(children) != 1
                or task["status"] != "done"
                or task["stage"] != "complete"
                or (task["result"] or {}).get("action") != "request_data"
            ):
                raise InputWait("Pattern dependency lineage is not an exact completed wait")
            identity = children[0]["id"]
        raise InputWait("Pattern dependency lineage exceeds its bounded review")

    def _pattern_learning_record(self, identity: str) -> dict[str, Any]:
        row = self.registry.db.execute(
            "SELECT id,stage,status,context,proposal,result,archive_reference,archive_sha256 "
            "FROM role_tasks WHERE id=?",
            (identity,),
        ).fetchone()
        if row is None:
            raise InputWait("Original pattern predecessor is unavailable")
        return dict(row)

    def _pattern_learning_body(self, binding: dict[str, Any]) -> dict[str, Any] | None:
        lesson = binding["lesson"]
        if lesson is None:
            if binding["state"] not in {
                "first_question",
                "unfunded_no_change",
                "pending_dependency",
                "scientific_rejection",
            }:
                raise InputWait("Expected mature lesson is unavailable")
            return None
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT body,sha,created FROM research_lessons WHERE id=? AND task=?",
                (lesson["id"], binding["source_task"]),
            ).fetchone()
        if row is None:
            raise InputWait("Original mature supported lesson is unavailable")
        body: dict[str, Any] = json.loads(row["body"])
        if (
            row["sha"] != lesson["sha256"]
            or fingerprint(body) != row["sha"]
            or body["id"] != lesson["id"]
            or body["task"] != binding["source_task"]
            or fingerprint(body["source"]) != binding["source_sha256"]
            or body["source_sha256"] != binding["source_sha256"]
            or body["source"]["body"]["available_at"] > binding["cutoff"]
            or body["source"]["at"] > binding["cutoff"]
            or row["created"] > binding["cutoff"]
        ):
            raise InputWait("Original lesson identity/source or causal cutoff differs")
        if self.pattern_comparisons is None:
            raise InputWait("Pattern learning disclosure owner is unavailable")
        with self.registry.lock:
            start = body["source"]["body"]["window_start"]
            end = body["source"]["body"]["available_at"]
            protected = self.registry.db.execute(
                "SELECT 1 FROM evidence_windows WHERE start<=? AND end>=? AND origin NOT IN "
                "('role outcome disclosure','lesson disclosure','role dependency disclosure',"
                "'role task disclosure',?,?,?,?) LIMIT 1",
                (end, start, *TRAINING_ORIGINS),
            ).fetchone()
            prospective = self.registry.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prospective_plans'"
            ).fetchone()
            reserved = (
                prospective
                and self.registry.db.execute(
                    "SELECT 1 FROM prospective_plans WHERE start<=? AND end>=? LIMIT 1",
                    (end, start),
                ).fetchone()
            )
            if protected or reserved:
                raise InputWait("Prior outcome overlaps protected or prospective evaluation input")
        return body  # Mutable access, notes and selection annotations are never evidence.

    @staticmethod
    def _pattern_predecessor_state(task: dict[str, Any], now: float) -> str | None:
        if (
            task["status"] == "waiting"
            and task["execution"]["kind"] == "unclaimed"
            and task["lease_until"] is None
            and (
                task["stage"] == "tool_wait"
                or (task["stage"] in {"data_wait", "outcome"} and task["retry_at"] > now)
            )
        ):
            return "pending_dependency"
        review = (task["result"] or {}).get("review")
        if (
            task["status"] == "done"
            and task["stage"] == "complete"
            and isinstance(review, dict)
            and review.get("action") == "reject"
            and set(review.get("issues", [])) <= {"unsupported_claim"}
        ):
            return "scientific_rejection"
        return None

    def _pattern_root_selection(
        self,
        task: dict[str, Any],
        records: list[dict[str, str]],
        authority: dict[str, Any],
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        # Dependency continuations intentionally do not get another selection.
        # The checked lineage still owns the immutable selection at its root.
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT body FROM role_question_selections WHERE task=? AND scope_sha=?",
                (
                    records[0]["task"] if records else task["id"],
                    fingerprint({"authority": authority, "policy_sha": fingerprint(policy)}),
                ),
            ).fetchone()
        if row is None:
            raise InputWait("Original predecessor selection is unavailable")
        prior: dict[str, Any] = json.loads(row["body"])
        if (
            prior["authority"] != authority
            or prior["method"] != self._pattern_task_method(task)
            or prior["comparison"]["request_id"]
            != task["context"]["pattern_comparison"]["preparation_request_id"]
        ):
            raise InputWait("Original predecessor selection differs from its lineage")
        return prior

    def _pattern_learning_prior(
        self,
        task: dict[str, Any] | None,
        records: list[dict[str, str]],
        authority: dict[str, Any],
        policy: dict[str, Any],
        source: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        binding: dict[str, Any] = {
            "authority": authority,
            "policy_sha256": fingerprint(policy),
            "state": "first_question" if task is None else "unfunded_no_change",
            "predecessor_task": task["id"] if task else None,
            "records": records,
            "lesson": None,
            "source_sha256": None,
            "source_task": None,
            "source_record": None,
            "cutoff": now,
            "dispatch_available": source["dispatch_available"],
            "dispatch_reason": source["dispatch_reason"],
        }
        method_policy = authority["question_policy"] == PATTERN_METHOD_QUESTION_POLICY
        if method_policy:
            binding.update(
                next_method=source["method_identity"],
                previous_method=None,
                used_methods=source["used_methods"],
                method_claims=source["method_claims"],
            )
        if task is None:
            return binding
        context, outcome = task["context"], (task["result"] or {}).get("outcome")
        if context.get("selection_authority") != authority or context.get(
            "policy_sha256"
        ) != fingerprint(policy):
            raise InputWait("Original predecessor belongs to different authority or cost policy")
        state = self._pattern_predecessor_state(task, now) if method_policy else None
        if state is not None:
            root_selection = self._pattern_root_selection(task, records, authority, policy)
            binding.update(
                state=state,
                previous_method=self._pattern_method_identity(self._pattern_task_method(task)),
                predecessor_observation={
                    "task": task["id"],
                    "at": now,
                    "stage": task["stage"],
                    "status": task["status"],
                    "result": task["result"],
                    "proposal_sha256": fingerprint(task["proposal"]),
                    "selection_sha": root_selection["selection_sha"],
                    "selection_body_sha256": fingerprint(root_selection),
                    "scope": "Retained observation at selection; no supported lesson "
                    "or qualification asserted",
                },
            )
            return binding
        if outcome is None:
            if task["proposal"] is not None:
                raise InputWait("Prepared/submitted predecessor still lacks its mature outcome")
            inherited = context.get("pattern_learning")
            if inherited and inherited["lesson"] is not None:
                if (
                    inherited["source_task"] == task["id"]
                    or context["lesson"]["task"] != inherited["source_task"]
                ):
                    raise InputWait("Inherited mature source cannot point to an unfunded successor")
                with self.registry.lock:
                    before = self._pattern_learning_record(inherited["source_task"])
                original = self.get(inherited["source_task"])
                with self.registry.lock:
                    if before != self._pattern_learning_record(inherited["source_task"]):
                        raise InputWait("Original mature source storage changed during recovery")
                if not (original["result"] or {}).get("outcome"):
                    raise InputWait("Inherited source has no actual mature outcome")
                carried = self._pattern_learning_prior(original, [], authority, policy, source, now)
                if (
                    carried["lesson"] != inherited["lesson"]
                    or carried["source_sha256"] != inherited["source_sha256"]
                    or context["lesson"] != self._pattern_learning_body(carried)
                    or self._pattern_root_selection(task, records, authority, policy)["learning"]
                    != inherited
                    or original["status"] != "done"
                    or original["stage"] != "complete"
                    or original["result"].get("followup", {}).get("action") != "no_change"
                ):
                    raise InputWait("Inherited mature lesson no longer matches its original source")
                return carried | {"predecessor_task": task["id"], "records": records}
            return binding
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT id,sha FROM research_lessons WHERE task=?", (task["id"],)
            ).fetchone()
        if row is None:
            raise InputWait("Recorded mature outcome requires its original supported lesson")
        with self.registry.lock:
            source_record = self._pattern_learning_record(task["id"])
            if (
                source_record["archive_reference"] != task["archive_reference"]
                or source_record["archive_sha256"] != task["archive_sha256"]
                or source_record["stage"] != task["stage"]
                or source_record["status"] != task["status"]
                or (
                    source_record["archive_reference"] is None
                    and any(
                        (json.loads(source_record[key]) if source_record[key] else None)
                        != task[key]
                        for key in ("context", "proposal", "result")
                    )
                )
            ):
                raise InputWait("Original mature source changed during recovery")
        binding.update(
            state="mature_outcome",
            source_task=task["id"],
            source_record={
                "task": task["id"],
                "sha256": fingerprint(source_record),
            },
            lesson={"id": row["id"], "sha256": row["sha"]},
            source_sha256=fingerprint(outcome),
            proposal_id=task["proposal"]["request_id"] if task["proposal"] else None,
            proposal_sha256=fingerprint(task["proposal"]),
        )
        prior = self._pattern_learning_body(binding)
        assert prior is not None
        proposal, score = task["proposal"], outcome["body"]
        prior_method = self._pattern_task_method(task)
        expected_method = self._pattern_method_identity(prior_method) if method_policy else None
        if method_policy:
            binding["previous_method"] = expected_method
        if (
            proposal is None
            or prior["version"] != "supported-lesson-v1"
            or prior["source"] != outcome
            or context.get("selection_authority") != authority
            or context.get("policy_sha256") != fingerprint(policy)
            or fingerprint(prior["context"]["cost_policy"]) != fingerprint(policy)
            or prior["context"]["data_basis"] != source["source_basis"]
            or prior["context"]["horizon"] != "medium"
            or prior["context"]["strategy_sha256"]
            != (expected_method["strategy_sha256"] if expected_method else source["strategy_sha"])
            or prior["context"]["reference_sha256"]
            != (expected_method["reference_sha256"] if expected_method else source["reference_sha"])
            or fingerprint(proposal["strategy"])
            != (expected_method["strategy_sha256"] if expected_method else source["strategy_sha"])
            or fingerprint(proposal["reference"])
            != (expected_method["reference_sha256"] if expected_method else source["reference_sha"])
            or fingerprint(context["fixed_comparison"][prior_method]["source_sha256"])
            != source["method_source_sha"]
            or score["proposal_id"] != proposal["request_id"]
            or not score["window_start"] < score["window_end"] <= score["available_at"] <= now
        ):
            raise InputWait("Mature lesson differs from the exact scoped method/cost/source")
        return binding

    def _check_pattern_learning(
        self, binding: dict[str, Any], question: Question, now: float, *, publication: bool = False
    ) -> None:
        if binding["cutoff"] != now:
            raise InputWait("Pattern lesson cutoff changed before publication")
        records = binding["records"]
        if (
            len(records) > 20
            or (records[-1]["task"] if records else None) != binding["predecessor_task"]
        ):
            raise InputWait("Original pattern predecessor lineage differs")
        observation = binding.get("predecessor_observation")
        if observation is not None:
            with self.registry.lock:
                row = self.registry.db.execute(
                    "SELECT body FROM role_question_selections WHERE selection_sha=?",
                    (observation["selection_sha"],),
                ).fetchone()
            if (
                row is None
                or fingerprint(json.loads(row["body"])) != (observation["selection_body_sha256"])
            ):
                raise InputWait("Original predecessor selection changed or is unavailable")
            if binding["state"] == "scientific_rejection":
                original = self.get(observation["task"])
                if original["result"] != observation["result"] or (
                    self._pattern_predecessor_state(original, now) != "scientific_rejection"
                ):
                    raise InputWait("Original scientific rejection changed")
        # Waiting tasks are expected to resume. Bind their immutable selection
        # and captured observation without requiring mutable state forever.
        for index, record in enumerate(records if observation is None or publication else []):
            with self.registry.lock:
                if fingerprint(self._pattern_learning_record(record["task"])) != record["sha256"]:
                    raise InputWait("Original predecessor changed before publication")
                children = self.registry.db.execute(
                    "SELECT id FROM role_tasks WHERE json_extract(context,'$.predecessor_task')=? "
                    "ORDER BY id LIMIT 2",
                    (record["task"],),
                ).fetchall()
            expected = [records[index + 1]["task"]] if index + 1 < len(records) else []
            if [row["id"] for row in children] != expected:
                raise InputWait("Original predecessor lineage changed before publication")
        prior = self._pattern_learning_body(binding)
        if question.lesson != (prior["id"] if prior else None):
            raise InputWait("Question no longer binds its original mature lesson")
        if binding["source_record"] is not None:
            record = binding["source_record"]
            with self.registry.lock:
                if fingerprint(self._pattern_learning_record(record["task"])) != record["sha256"]:
                    raise InputWait(
                        "Original mature source task/archive changed before publication"
                    )

    def _pattern_learning_admission(
        self,
        binding: dict[str, Any],
        authority: dict[str, Any],
        policy: dict[str, Any],
        task_proposal: dict[str, Any] | None = None,
    ) -> Callable[[], None]:
        def check() -> None:
            c = self.controller
            if (
                c is None
                or not self._activation_enabled()
                or self._selection_authority() != authority
                or binding["authority"] != authority
                or binding["policy_sha256"] != fingerprint(policy)
                or fingerprint(c.paper.state.get("autonomous_lab", {}).get("policy"))
                != fingerprint(policy)
            ):
                raise InputWait("Original learning authority or policy changed before disclosure")
            self._check_pattern_learning(
                binding,
                Question(
                    question="Inspect exact original mature source",
                    horizon="medium",
                    lesson=binding["lesson"]["id"] if binding["lesson"] else None,
                ),
                binding["cutoff"],
            )
            if authority["question_policy"] == PATTERN_METHOD_QUESTION_POLICY:
                self._pattern_method_admission(binding, task_proposal)

        return check

    def _select_pattern_question(
        self, authority: dict[str, Any], policy: dict[str, Any], scope: str, now: float
    ) -> int:
        bridge = self.pattern_comparisons
        if bridge is None or "medium" not in policy["holding_horizons"]:
            raise InputWait("Pattern comparison awaits its declared medium owner")
        if self._contract_version() != PATTERN_VERSION:
            raise InputWait("Pattern selection needs its exact v8 contract")
        with self.registry.lock:
            previous = self.registry.db.execute(
                "SELECT task,source_end,selection_sha,body FROM role_question_selections "
                "WHERE scope_sha=? AND horizon='medium' ORDER BY source_end DESC LIMIT 1",
                (scope,),
            ).fetchone()
        method_policy = authority["question_policy"] == PATTERN_METHOD_QUESTION_POLICY
        learning_policy = authority["question_policy"] in {
            PATTERN_LEARNING_QUESTION_POLICY,
            PATTERN_METHOD_QUESTION_POLICY,
        }
        records: list[dict[str, str]] = []
        predecessor = None
        if previous:
            task = self._pattern_terminal(
                previous["task"], authority, records=records if learning_policy else None
            )
            predecessor = task
            result = task["result"] or {}
            if (
                task["status"] != "done"
                or task["stage"] != "complete"
                or result.get("followup", result).get("action") != "no_change"
            ) and not (
                method_policy
                and self._finite_current() is None
                and self._pattern_predecessor_state(task, now) is not None
            ):
                raise InputWait("Original adverse/wait/result needs reviewed capability or scope")
        finite = self._finite_current()
        if finite is not None:
            with self.registry.lock:
                if self.finite.prior(finite) is not None:
                    raise InputWait("Finite test already claimed its one original research chain")
            choices = [PatternFindingSelection.model_validate(finite["finite_test"]["selection"])]
        else:
            choices = bridge.candidates(now)
        if not choices:
            raise InputWait(
                "No supported saved BTC/native-5m volume-confirmed breakout/retest in the "
                "bounded recent daily captures; chart recognition alone is not research eligibility"
            )
        learning = None
        research_only = False
        method_id = "p0"
        used_methods = None
        method_claims = None
        if method_policy:
            used_methods = self._pattern_method_used()
            method_claims = self._pattern_method_claims(authority, fingerprint(policy))
            unused = next(
                (
                    key
                    for key in PATTERN_METHODS
                    if not used_methods[key] and key not in method_claims
                ),
                None,
            )
            if unused is None and predecessor is None:
                raise InputWait(
                    "All fixed methods were used; no owned mature source for observation"
                )
            if unused is None:
                assert predecessor is not None
                if not all(used_methods.values()):
                    raise InputWait(
                        "All fixed methods are used or owned by retained investigations; "
                        "resolve their waits/rejections. No further refinement method "
                        "is implemented"
                    )
                method_id = self._pattern_task_method(predecessor)
            else:
                method_id = unused
        if learning_policy:
            assert self.controller is not None
            candidate = RuleSpec.model_validate(
                {
                    "version": "reviewed-lab-rules-v4",
                    "family": PATTERN_METHODS[method_id][0],
                    "holding_horizon": "medium",
                }
            )
            reference = RuleSpec.model_validate(
                {
                    "version": "reviewed-lab-rules-v4",
                    "family": PATTERN_METHODS[method_id][1],
                    "holding_horizon": "medium",
                }
            )
            used = self.controller.inbox.used(fingerprint(candidate.model_dump()))
            prior_source = {
                "source_basis": self.controller.paper.state.get(
                    "evidence_kind", "observed_public_market"
                ),
                "strategy_sha": fingerprint(candidate.model_dump()),
                "reference_sha": fingerprint(reference.model_dump()),
                "method_source_sha": fingerprint(bridge._method_sources()),
                "dispatch_available": not used,
                "dispatch_reason": (
                    f"Equivalent fixed {method_id} was already used; research evidence only, "
                    "no new proposal or financial dispatch"
                    if used
                    else f"Fixed {method_id} remains offered subject to all existing "
                    "admission gates"
                ),
            }
            if method_policy:
                prior_source.update(
                    method_identity=self._pattern_method_identity(method_id),
                    used_methods=used_methods,
                    method_claims=method_claims,
                )
            learning = self._pattern_learning_prior(
                predecessor, records, authority, policy, prior_source, now
            )
            research_only = (
                learning["state"] == "mature_outcome" and not learning["dispatch_available"]
            )
            if method_policy:
                self._pattern_method_admission(learning)
        skipped: list[str] = []
        for selection in choices:
            try:
                described = bridge.describe(
                    selection, research_only=research_only, method_id=method_id
                )
            except (ValueError, OSError) as exc:
                if finite is not None:
                    raise  # The finite grant permits only its exact original finding.
                skipped.append(f"{selection.event_kind}:{selection.event_seq}: {str(exc)[:160]}")
                continue
            if (
                finite is not None
                and described["finding_sha256"] != finite["finite_test"]["finding_sha256"]
            ):
                raise ValueError(
                    "Finite selection differs from the exact approved original finding"
                )
            event_sha = self._pattern_event_identity(described["finding"])
            with self.registry.lock:
                duplicate = self.registry.db.execute(
                    "SELECT 1 FROM role_question_selections WHERE scope_sha=? "
                    "AND json_extract(body,'$.original_event_sha')=? LIMIT 1",
                    (scope, event_sha),
                ).fetchone()
            if duplicate:
                skipped.append("This original native event was already investigated; no repeat")
                continue
            if previous and (
                described["finding"]["original_event"]["bar_close_ms"] / 1000
                - json.loads(previous["body"])["original_event_end"]
                < max(
                    policy["horizon_seconds"], RuleSpec(holding_horizon="medium").timing["review"]
                )
            ):
                skipped.append(
                    "Distinct later native evidence has not matured for another question"
                )
                continue
            break
        else:
            raise InputWait(
                f"No eligible original among {len(choices)} bounded retained candidates: "
                + "; ".join(dict.fromkeys(skipped))[:380]
            )
        preparation_key: dict[str, Any] = {"scope": scope, "event": event_sha}
        if method_policy:
            preparation_key["method"] = self._pattern_method_identity(method_id)
        preparation_id = "role-pattern-" + fingerprint(preparation_key)[:32]
        if method_policy and learning is not None:
            learning["claim_preparation"] = preparation_id
        original = bridge.get(preparation_id)
        if original is None:
            original = bridge.prepare(
                PatternComparisonCommand(
                    **selection.model_dump(),
                    request_id=preparation_id,
                    expected_finding_sha256=described["finding_sha256"],
                ),
                now,
                admission=(
                    self._finite_admission(finite)
                    if finite is not None
                    else self._pattern_learning_admission(learning, authority, policy)
                    if learning is not None
                    else None
                ),
                research_only=research_only,
                method_id=method_id,
            )
        elif (
            self._pattern_event_identity(original["finding"]) != event_sha
            or original["mapping"] != described["mapping"]
            or original["current_policy_sha256"] != digest(policy)
        ):
            raise ValueError("Stable preparation differs from this original event/method/policy")
        if (
            original["status"]
            not in {
                "waiting",
                "research_only" if research_only else "supported",
            }
            or bool(original.get("research_only")) != research_only
        ):
            raise InputWait("Original deterministic preparation has a different research mode")
        source = self._pattern_source(
            original,
            policy,
            now,
            research_only=research_only,
            learning_policy=learning_policy,
            method_id=method_id,
        )
        if learning is not None and (
            learning["dispatch_available"] != source["dispatch_available"]
            or learning["dispatch_reason"] != source["dispatch_reason"]
        ):
            raise InputWait(
                "Original fixed-method dispatch availability changed during preparation"
            )
        key = fingerprint(
            {"scope_sha": scope, **source}
            | (
                {
                    "learning": {
                        k: v
                        for k, v in learning.items()
                        if k not in {"records", "source_record", "cutoff"}
                    }
                }
                if learning is not None
                else {}
            )
        )
        selected = {
            **source,
            "authority": authority,
            "scope_sha": scope,
            "selection_sha": key,
            "lesson": learning["lesson"] if learning is not None else None,
            "prior_selection": previous["selection_sha"] if previous else None,
            "candidate_search": {
                "considered": len(skipped) + 1,
                "skipped": skipped[:8],
                "skipped_count": len(skipped),
                "scope": "At most 32 historical findings in seven recent daily captures; "
                "current executable inputs and every original eligibility check remain required",
            },
            "original_event_end": original["finding"]["original_event"]["bar_close_ms"] / 1000,
            "reason": "Verified saved native breakout/retest motivates the fixed p0 comparison.",
            "falsification": "Reject benefit when mature matched net after-cost delta is "
            "nonpositive or the declared outcome coverage is inadequate.",
            "limitations": [
                "The native pivot detector and trading-bank predicate are distinct.",
                "Only the relevant recognition window and current minute prefix are contiguous; "
                "full-year and medium outcome coverage are not inferred.",
                "Maximum six-hour holding is not minimum 24-hour outcome review.",
                "Software support is not profit, model quality or qualification; "
                "operating/inference costs remain uncertain.",
            ],
        }
        if learning is not None:
            selected["learning"] = learning
        if method_policy:
            selected["reason"] = (
                f"Distinct saved native question motivates independent {method_id} "
                f"{PATTERN_METHODS[method_id][0]} versus {PATTERN_METHODS[method_id][1]}; "
                "original mature source is evidence, not parent-trial authority."
            )
        question = Question(
            question="Does fixed p0 breakout-retest improve future matched net after-cost "
            "outcomes versus cost-breakout? The saved native pattern motivates this "
            "distinct bank hypothesis; refute benefit or choose a typed wait/no_change "
            "when supported evidence is insufficient.",
            horizon="medium",
            request_id="auto-" + key[:32],
            lesson=learning["lesson"]["id"]
            if learning is not None and learning["lesson"]
            else None,
        )
        if method_policy:
            question = question.model_copy(
                update={
                    "question": (
                        f"Does fixed {method_id} {PATTERN_METHODS[method_id][0]} improve future "
                        "matched "
                        f"net after-cost outcomes versus {PATTERN_METHODS[method_id][1]}? "
                        "Use the exact original prior facts and current distinct native evidence; "
                        "refute benefit or choose a typed wait/no_change. "
                        "Independent comparison only."
                    )
                }
            )
        created = self.enqueue(
            question, now, _selection=selected, _pattern_comparison=source["comparison"]
        )
        self._supervision(
            "questions",
            "Selected " + created["id"] + "; prospective hypothesis, no edge claim",
            now + 60,
            "selected",
            scope_sha=scope,
        )
        return int(created["_selection_created"])

    def _check_selection(
        self,
        selection: dict[str, Any],
        question: Question,
        policy: dict[str, Any],
        inputs: dict[str, Any],
        catalog: dict[str, Any],
        now: float,
    ) -> None:
        if selection["authority"]["question_policy"] in {
            PATTERN_QUESTION_POLICY,
            PATTERN_LEARNING_QUESTION_POLICY,
            PATTERN_METHOD_QUESTION_POLICY,
        }:
            self._check_pattern_selection(selection, question, policy, inputs, catalog, now)
            return
        authority = selection["authority"]
        if (
            question.parent is not None
            or question.lesson is not None
            or question.request_id != "auto-" + selection["selection_sha"][:32]
            or selection["scope_sha"]
            != fingerprint({"authority": authority, "policy_sha": fingerprint(policy)})
            or selection["source_sha"] != inputs["closed_bar_sha256"]
            or selection["source_count"] != inputs["closed_bar_count"]
            or selection["strategy_sha"] != catalog["r1"]["strategy_sha256"]
            or selection["reference_sha"] != catalog["r1"]["reference_sha256"]
            or selection["horizon"] != question.horizon
            or self._selection_source(question.horizon, policy, now)
            != {key: selection[key] for key in self._selection_source_keys()}
            or selection["lesson"] != self._selection_lesson(authority, policy, question.horizon)
        ):
            raise InputWait(
                "Selection source, frozen comparison or lesson changed before publication"
            )

    @staticmethod
    def _selection_source_keys() -> tuple[str, ...]:
        return (
            "method",
            "horizon",
            "source_sha",
            "source_start",
            "source_end",
            "source_count",
            "source_basis",
            "strategy_sha",
            "reference_sha",
            "excursion_bps",
            "modeled_hurdle_bps",
        )

    def select_fresh_question(self, now: float | None = None) -> int:
        """At most one evidence-backed r1 investigation in the existing worker/registry."""
        now = time.time() if now is None else now
        authority = self._selection_authority()
        if authority is None:
            return 0  # Existing grants retain their exact manual/continuation behavior.
        with self.registry.lock:
            state = self.registry.db.execute(
                "SELECT retry_at FROM role_supervision WHERE phase='questions'"
            ).fetchone()
            if state and state["retry_at"] > now:
                return 0
        scope: str | None = None
        try:
            if self.controller is None or not self.controller.paper.state.get("autonomous_lab"):
                raise InputWait("Fresh investigation awaits a declared paper lab policy")
            policy = self.controller.paper.state["autonomous_lab"]["policy"]
            scope = fingerprint({"authority": authority, "policy_sha": fingerprint(policy)})
            with self.registry.lock:
                self._selection_room(authority, policy, now)
            if authority["question_policy"] in {
                PATTERN_QUESTION_POLICY,
                PATTERN_LEARNING_QUESTION_POLICY,
                PATTERN_METHOD_QUESTION_POLICY,
            }:
                return self._select_pattern_question(authority, policy, scope, now)
            reasons = []
            for horizon in policy["holding_horizons"]:
                with self.registry.lock:
                    previous = self.registry.db.execute(
                        "SELECT task,source_end,selection_sha FROM role_question_selections "
                        "WHERE scope_sha=? "
                        "AND horizon=? ORDER BY source_end DESC LIMIT 1",
                        (scope, horizon),
                    ).fetchone()
                if previous:
                    task = self.get(previous["task"])
                    result = task["result"] or {}
                    verdict = result.get("followup", result).get("action")
                    if (
                        task["status"] != "done"
                        or task["stage"] != "complete"
                        or verdict != "no_change"
                    ):
                        reasons.append(
                            horizon + ": retained adverse result needs reviewed capability or scope"
                        )
                        continue
                try:
                    source = self._selection_source(horizon, policy, now)
                except InputWait as exc:
                    reasons.append(horizon + ": " + str(exc))
                    continue
                if previous:
                    block = max(
                        policy["horizon_seconds"],
                        RuleSpec(holding_horizon=horizon).timing["review"],
                    )
                    if (
                        source["source_end"] - previous["source_end"] < block
                        or source["source_start"] > previous["source_end"] + 60
                        or source["source_count"] * 60 < block * policy["coverage_fraction"]
                    ):
                        reasons.append(
                            horizon + ": later qualifying source block/coverage has not matured"
                        )
                        continue
                with self.registry.lock:
                    lesson = self._selection_lesson(authority, policy, horizon)
                key = fingerprint({"scope_sha": scope, **source, "lesson": lesson})
                selection = {
                    **source,
                    "authority": authority,
                    "scope_sha": scope,
                    "selection_sha": key,
                    "lesson": lesson,
                    "prior_selection": previous["selection_sha"] if previous else None,
                    "reason": (
                        f"Closed-source range excursion {source['excursion_bps']} bps exceeds "
                        f"the modeled execution-cost hurdle {source['modeled_hurdle_bps']} bps "
                        "for frozen r1."
                    ),
                    "falsification": (
                        "Reject claimed benefit if the mature prospective matched net after-cost "
                        "delta is nonpositive or declared coverage is inadequate."
                    ),
                    "limitations": [
                        "A causal entry prerequisite is not observed profit or model usefulness.",
                        "Warmup and later blocks may be correlated; no independent-sample claim.",
                        "The signal hurdle covers modeled execution costs; "
                        "operating/inference costs require the matched result.",
                        "Source basis: " + source["source_basis"],
                    ],
                }
                question = Question(
                    question=(
                        "Is the saved eligible range excursion sufficient to justify frozen r1 "
                        "range reversion versus breakout prospectively? Refute benefit if mature "
                        "matched net after-cost delta is nonpositive or coverage inadequate; "
                        "choose no_change or a declared dependency if evidence is insufficient."
                    ),
                    horizon=horizon,
                    request_id="auto-" + key[:32],
                )
                created = self.enqueue(question, now, _selection=selection)
                self._supervision(
                    "questions",
                    "Selected " + created["id"] + "; experimental investigation, no quality claim",
                    now + 60,
                    "selected",
                    scope_sha=scope,
                )
                return int(created["_selection_created"])
            raise InputWait("; ".join(reasons)[:500] or "No eligible declared comparison source")
        except InputWait as exc:
            self._supervision("questions", str(exc)[:500], now + 60, "waiting", scope_sha=scope)
            return 0

    def question_selection_status(self) -> dict[str, Any]:
        try:
            authority = self._selection_authority()
        except (ValueError, OSError, KeyError) as exc:
            return {
                "policy": None,
                "state": "unavailable",
                "reason": "Selection authority unavailable: " + type(exc).__name__,
            }
        if authority is None:
            return {
                "policy": None,
                "state": "disabled",
                "reason": (
                    "Fresh investigations require a separately selected explicit question policy"
                ),
            }
        if not self._activation_enabled():
            return {
                "policy": authority["question_policy"],
                "state": "disabled",
                "reason": "Fresh investigation selection is paused; saved provenance is unchanged",
            }
        with self.registry.lock:
            state = self.registry.db.execute(
                "SELECT * FROM role_supervision WHERE phase='questions'"
            ).fetchone()
            lab = self.controller.paper.state.get("autonomous_lab") if self.controller else None
            scope = (
                fingerprint({"authority": authority, "policy_sha": fingerprint(lab["policy"])})
                if lab
                else None
            )
            selected = self.registry.db.execute(
                "SELECT task,body FROM role_question_selections WHERE scope_sha=? "
                "ORDER BY created DESC LIMIT 1",
                (scope,),
            ).fetchone()
        if state and state["scope_sha"] != scope and state["scope_sha"] is not None:
            state = None
        return {
            "policy": authority["question_policy"],
            "state": (
                state["status"]
                if state and state["status"] in {"selected", "waiting"}
                else "unavailable"
                if state
                else "waiting"
            ),
            "reason": state["reason"]
            if state
            else "Awaiting evidence-backed selection; no model request or quality claim",
            "experimental": True,
            "task": selected["task"] if selected else None,
            "evidence": json.loads(selected["body"]) if selected else None,
        }

    async def run(self) -> None:
        while True:
            if self.activation is not None:
                try:
                    self.enabled = await asyncio.to_thread(self.activation)
                except (ValueError, OSError, KeyError):
                    self.enabled = False
            if self.enabled:
                await self._maintain("dependencies", self.resume_sources)
                await self._maintain("followups", self.select_followups)
                await self._maintain("questions", self.select_fresh_question)
                await self._maintain("dispatch", self.step, thread=False)
            await asyncio.sleep(1)

    def _supervision(
        self,
        phase: str,
        reason: str | None,
        retry_at: float,
        status: str,
        *,
        scope_sha: str | None = None,
    ) -> None:
        with self.registry.transaction():
            old = self.registry.db.execute(
                "SELECT * FROM role_supervision WHERE phase=?", (phase,)
            ).fetchone()
            if reason is None and (old is None or old["reason"] is None):
                return
            self.registry.db.execute(
                "INSERT INTO role_supervision VALUES(?,?,?,?,?,?) ON CONFLICT(phase) DO UPDATE "
                "SET status=excluded.status,reason=excluded.reason,retry_at=excluded.retry_at,"
                "updated=excluded.updated,scope_sha=excluded.scope_sha",
                (phase, status, reason, retry_at, time.time(), scope_sha),
            )
            if old is None or old["reason"] != reason or old["status"] != status:
                self.registry.event(
                    "role-supervisor:" + phase,
                    "role_supervisor_" + status,
                    {"reason": reason, "retry_at": retry_at},
                )

    async def _maintain(
        self, phase: str, operation: Callable[[], Any], *, thread: bool = True
    ) -> None:
        now = time.time()
        if self._maintenance_due.get(phase, 0) > now:
            return
        try:
            with self.registry.lock:
                state = self.registry.db.execute(
                    "SELECT retry_at FROM role_supervision WHERE phase=?", (phase,)
                ).fetchone()
            if state and state["retry_at"] > now:
                return
            if thread:
                await self._owned(operation)
            else:
                await operation()
            if phase != "questions":
                self._supervision(phase, None, 0, "recovered")
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            sqlite3.OperationalError,
            OSError,
            HistoryUnavailable,
            InputWait,
        ) as exc:
            self.reason = f"Research {phase} unavailable ({type(exc).__name__}); bounded retry"
            self._maintenance_due[phase] = now + 30
            try:
                self._supervision(phase, self.reason, now + 30, "waiting")
            except sqlite3.OperationalError:
                pass  # Cannot persist while this registry is unwritable; keep the visible fault.
        except Exception as exc:
            self.reason = f"Research {phase} failed ({type(exc).__name__}); repair required"
            self._supervision(phase, self.reason, 0, "failed")
            raise  # Programming/permanent failures are exposed, not retried as an outage.

    def select_followups(self) -> dict[str, int]:
        """Bounded completed-comparison trigger; unchanged/replayed results coalesce.

        Required qualification gates remain at dispatch. This selector never
        changes the numerical learner, financial allocation or family quotas.
        """
        try:
            self.history.discover_followups()
        except HistoryUnavailable:
            self.reason = "Older follow-up storage unavailable; bounded migration retry recorded"
        pilot_grant_id = self._pilot_grant_id()
        selection_json = self._selection_json()
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT task AS id FROM role_followups f JOIN role_tasks t ON t.id=f.task "
                "WHERE f.state='pending' AND f.retry_at<=? "
                "AND coalesce(json_extract(t.context,'$.execution_mode'),'qualified_roles')=? "
                "AND (t.archive_reference IS NULL "
                "OR json_extract(t.context,'$.contract') IS NOT NULL) "
                "AND coalesce(json_extract(t.context,'$.contract'),'reviewed-rule-role-v5')=? "
                "AND (? IS NULL OR json_extract(t.context,'$.pilot_grant_id')=?) "
                "AND (json_type(t.context,'$.selection_authority') IS NULL "
                "OR json_extract(t.context,'$.selection_authority')=json(?)) "
                "AND NOT EXISTS "
                "(SELECT 1 FROM research_selection s JOIN research_lessons l ON l.id=s.lesson "
                "WHERE l.task=f.task AND s.retry_at>?) ORDER BY f.retry_at,task LIMIT 20",
                (
                    time.time(),
                    self.execution_mode,
                    self._contract_version(),
                    pilot_grant_id,
                    pilot_grant_id,
                    selection_json,
                    time.time(),
                ),
            ).fetchall()
        selected = waiting = 0
        for row in rows:
            try:
                task = self.get(row["id"])
                if not self._same_mode(task):
                    continue
                identity = self.lessons.record(task)
            except (HistoryUnavailable, OSError, sqlite3.OperationalError):
                with self.registry.transaction():
                    self.registry.db.execute(
                        "UPDATE role_followups SET retry_at=? WHERE task=?",
                        (time.time() + 30, row["id"]),
                    )
                continue
            with self.registry.lock:
                prior = self.registry.db.execute(
                    "SELECT state FROM research_selection WHERE lesson=?", (identity,)
                ).fetchone()
            if prior and prior["state"] in {"selected", "waiting"}:
                with self.registry.transaction():
                    self.registry.db.execute(
                        "UPDATE role_followups SET state='consumed' WHERE task=?", (task["id"],)
                    )
                continue
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
                with self.registry.transaction():
                    self.registry.db.execute(
                        "UPDATE role_followups SET state='consumed' WHERE task=?", (task["id"],)
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
                    ),
                    _selection_authority=task["context"].get("selection_authority"),
                )
                # Reconciliation after a lost acknowledgment returns the exact same task.
                self.lessons.selected(
                    identity,
                    "selected",
                    "New mature comparison and supported different capability",
                    next_task["id"],
                )
                with self.registry.transaction():
                    self.registry.db.execute(
                        "UPDATE role_followups SET state='consumed' WHERE task=?", (task["id"],)
                    )
                selected += 1
            except (ValueError, OSError) as exc:
                self.lessons.selected(identity, "deferred", str(exc)[:500])
                with self.registry.transaction():
                    self.registry.db.execute(
                        "UPDATE role_followups SET retry_at=? WHERE task=?",
                        (time.time() + 60, task["id"]),
                    )
        return {"selected": selected, "waiting": waiting}

    def resume_sources(self, now: float | None = None) -> int:
        """Exchange one waiting slot atomically, using its frozen typed dependency."""
        if self.controller is None:
            return 0
        now = time.time() if now is None else now
        pilot_grant_id = self._pilot_grant_id()
        selection_json = self._selection_json()
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT id FROM role_tasks WHERE stage='data_wait' AND status='waiting' "
                "AND coalesce(json_extract(context,'$.execution_mode'),'qualified_roles')=? "
                "AND coalesce(json_extract(context,'$.contract'),'reviewed-rule-role-v5')=? "
                "AND (? IS NULL OR json_extract(context,'$.pilot_grant_id')=?) "
                "AND (json_type(context,'$.selection_authority') IS NULL "
                "OR json_extract(context,'$.selection_authority')=json(?)) "
                "AND retry_at<=? AND owner IS NULL ORDER BY updated,id LIMIT 20",
                (
                    self.execution_mode,
                    self._contract_version(),
                    pilot_grant_id,
                    pilot_grant_id,
                    selection_json,
                    now,
                ),
            ).fetchall()
        resumed = 0
        for row in rows:
            try:
                resumed += self._resume_source(row["id"], now)
            except (
                psycopg.OperationalError,
                psycopg.InterfaceError,
                sqlite3.OperationalError,
                OSError,
                HistoryUnavailable,
            ) as exc:
                with self.registry.transaction():
                    self.registry.db.execute(
                        "UPDATE role_tasks SET reason=?,retry_at=? WHERE id=? "
                        "AND stage='data_wait' AND status='waiting' AND owner IS NULL",
                        (
                            "Dependency database/storage unavailable: " + type(exc).__name__,
                            now + 30,
                            row["id"],
                        ),
                    )
        return resumed

    def _resume_source(self, identity: str, now: float) -> int:
        task = self.get(identity)
        if not self._same_mode(task):
            return 0
        if "finite_test" in task["context"]:
            with self.registry.lock:
                if self.finite.count(self.finite.binding(task)) >= 3:
                    return 0
        question = Question.model_validate(task["context"]["question"])
        requirement = (task["result"] or {}).get("wait_requirement")
        if not requirement:
            return 0  # Historical free text is retained; never guess a dependency.
        outcome = None
        if requirement["kind"] == "closed_bars":
            assert self.controller is not None
            if task["context"].get("contract") == PATTERN_VERSION:
                saved = task["context"]["pattern_comparison"]
                method_id = self._pattern_task_method(task)
                research_only = bool(
                    task["context"].get("pattern_learning", {}).get("dispatch_available") is False
                )
                if "pattern_method" in task["context"]:
                    self._pattern_learning_admission(
                        task["context"]["pattern_learning"],
                        task["context"]["selection_authority"],
                        task["context"]["policy"],
                    )()
                original = self._pattern_original(
                    {
                        "request_id": saved["preparation_request_id"],
                        "finding_sha256": saved["finding_sha256"],
                        "issued_bundle_sha256": saved["issued_bundle_sha256"],
                    },
                    research_only=research_only if "pattern_method" in task["context"] else False,
                    method_id=method_id,
                )
                inputs = self.controller.evaluate(
                    self._pattern_method(original, research_only=research_only)
                    if "pattern_method" in task["context"]
                    else LabProposal.model_validate(original["proposal"]),
                    now,
                )["inputs"]
                if (
                    digest(inputs) == requirement["source_sha256"]
                    or inputs[-1]["close_ms"] / 1000 <= requirement["last_closed_at"]
                ):
                    self._defer_source(identity, now)
                    return 0
                bars = []
            else:
                bars = self.controller.paper.lab_history(now, requirement["horizon"])
            if task["context"].get("contract") != PATTERN_VERSION and (
                fingerprint([str(b) for b in bars]) == requirement["source_sha256"]
                or max((b.close_ms / 1000 for b in bars), default=0)
                <= requirement["last_closed_at"]
            ):
                self._defer_source(identity, now)
                return 0
        elif requirement["kind"] == "mature_outcome":
            assert self.controller is not None
            with reader(self.controller.paper) as view:
                outcome = view.connection.execute(
                    "SELECT id,at,body FROM paper_events WHERE kind='lab_trial_scored' "
                    "AND body->>'trial_id'=%s AND at<=%s ORDER BY id DESC LIMIT 1",
                    (requirement["trial_id"], now),
                ).fetchone()
            if not outcome or outcome["body"]["available_at"] > now:
                self._defer_source(identity, now)
                return 0
        else:
            return 0
        try:
            self.enqueue(
                question.model_copy(update={"request_id": None}),
                now,
                _resume_from=task,
                _dependency_evidence=dict(outcome) if outcome else None,
                _selection_authority=task["context"].get("selection_authority"),
            )
        except HistoryUnavailable:
            raise
        except ValueError as exc:
            with self.registry.transaction():
                self.registry.db.execute(
                    "UPDATE role_tasks SET reason=?,retry_at=? WHERE id=? "
                    "AND stage='data_wait' AND status='waiting' AND owner IS NULL",
                    ("Continuation blocked: " + str(exc)[:300], now + 30, identity),
                )
            return 0
        return 1

    def _defer_source(self, identity: str, now: float) -> None:
        # An unchanged dependency owns a bounded retry, not the whole queue.
        with self.registry.transaction():
            self.registry.db.execute(
                "UPDATE role_tasks SET retry_at=? WHERE id=? AND stage='data_wait' "
                "AND status='waiting' AND owner IS NULL",
                (now + 30, identity),
            )

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
                "FROM role_attempt_allowances"
            ).fetchone()
            completed = self.registry.db.execute(
                "SELECT count(*) FROM role_tasks WHERE status='done'"
            ).fetchone()[0]
            external = self.registry.db.execute(
                "SELECT count(*) FROM role_attempt_allowances WHERE actor IS NOT NULL"
            ).fetchone()[0]
        return {
            "selection": selections,
            "completed_questions": completed,
            "attempts": totals[0],
            "reserved_wall_seconds": totals[1],
            "reserved_token_allowance": totals[2],
            "paid_usd": None if external else "0",
            "actual_model_tokens": None,
            "limits": "Allowance is conservative reservation, not measured model tokens or benefit",
        }
