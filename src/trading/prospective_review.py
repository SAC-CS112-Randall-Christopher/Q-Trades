"""Frozen subsequent-system reviews in the existing registry. No financial writes."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading.execution_replay import source_hashes
from trading.experiment_registry import ExperimentRegistry
from trading.experiment_worker import code_fingerprint
from trading.incremental_memory import LearningJournal
from trading.paper_learning import POLICY, comparison, config
from trading.research_evidence import digest


def review_fingerprint() -> str:
    return digest(
        {
            "evaluator": code_fingerprint(),
            "policy": POLICY,
            "sources": source_hashes(),
            "review": hashlib.sha256(
                Path(__file__).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest(),
        }
    )


class ProspectiveSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,64}$")
    name: str = Field(min_length=3, max_length=90)
    starts_at: float
    days: Literal[28] = 28
    component_requests: list[str] = Field(default_factory=list, max_length=8)
    candidate: str | None = None
    paid_budget_usd: Literal["0"] = "0"


class ProspectiveReview:
    def __init__(self, registry: ExperimentRegistry):
        self.registry = registry
        self.journal = LearningJournal(registry)
        registry.db.executescript("""
            CREATE TABLE IF NOT EXISTS prospective_plans(
                seq INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                start REAL NOT NULL, end REAL NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS prospective_update BEFORE UPDATE ON prospective_plans
                BEGIN SELECT RAISE(ABORT,'Prospective rules are frozen'); END;
            CREATE TRIGGER IF NOT EXISTS prospective_delete BEFORE DELETE ON prospective_plans
                BEGIN SELECT RAISE(ABORT,'Prospective history is retained'); END;
        """)

    def freeze(self, spec: ProspectiveSpec, state: dict[str, Any]) -> dict[str, Any]:
        r = self.registry
        with r.transaction():
            old = r.db.execute(
                "SELECT * FROM prospective_plans WHERE request_id=?", (spec.request_id,)
            ).fetchone()
            if old:
                body: dict[str, Any] = json.loads(old["body"])
                if digest(body) != old["sha256"] or body["spec"] != spec.model_dump():
                    raise ValueError("Retry must preserve original prospective rules")
                return body
            now = time.time()
            if not now + 3300 <= spec.starts_at <= now + 7 * 86400:
                raise ValueError("Choose an untouched start 55 minutes to seven days ahead")
            end = spec.starts_at + spec.days * 86400
            if r.db.execute("SELECT count(*) FROM prospective_plans").fetchone()[0] >= 4:
                raise ValueError("Four prospective plans retained; no trial reset")
            boundary = r.db.execute("SELECT max(end) FROM evidence_windows").fetchone()[0]
            if spec.starts_at - 3300 <= boundary:
                raise ValueError("Start overlaps consumed information plus label purge")
            if r.db.execute(
                "SELECT 1 FROM prospective_plans WHERE start<=? AND end>=?",
                (end, spec.starts_at - 3300),
            ).fetchone():
                raise ValueError("Prospective comparison overlaps an earlier frozen plan")
            components = []
            for request in spec.component_requests:
                job = r.get(request)
                result = job.get("result") if job else None
                if (
                    not result
                    or not result.get("eligible_for_forward_review")
                    or result.get("evidence_kind") == "synthetic_qa"
                ):
                    raise ValueError("Combine only independently qualified components")
                components.append({"request": request, "result_sha256": digest(result)})
            candidate = state["accounts"].get(spec.candidate or "")
            if spec.candidate and (
                not candidate
                or not candidate.get("numerical_artifact")
                or spec.candidate not in state.get("forward_controls", {})
            ):
                raise ValueError("Use an admitted frozen candidate and its matched CP7 control")
            body = {
                "version": "prospective-system-review-v1",
                "spec": spec.model_dump(),
                "ends_at": end,
                "frozen_at": now,
                "source_sha256": review_fingerprint(),
                "components": components,
                "configurations": {name: config(a) for name, a in state["accounts"].items()},
                "policy": POLICY,
                "controls": ["unchanged_baseline", "cash", "simple_exposure"],
                "stopping": "28 days fixed; drift/missing coverage retains no-promotion",
                "update_procedure": "Frozen; research updates remain separate shadows",
                "authority": "No funding, account creation, promotion or live execution",
            }
            r.db.execute(
                "INSERT INTO prospective_plans VALUES(NULL,?,?,?,?,?)",
                (spec.request_id, spec.starts_at, end, json.dumps(body), digest(body)),
            )
            r.event(spec.request_id, "prospective_frozen", {"sha256": digest(body)})
            return body

    def plans(self) -> list[dict[str, Any]]:
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT * FROM prospective_plans ORDER BY seq DESC"
            ).fetchall()
            result = []
            for row in rows:
                body = json.loads(row["body"])
                if digest(body) != row["sha256"]:
                    raise ValueError("Prospective plan fingerprint mismatch")
                result.append(body)
            return result

    def report(
        self, request: str, state: dict[str, Any], windows: dict[str, Any], now: float
    ) -> dict[str, Any]:
        plan = next((p for p in self.plans() if p["spec"]["request_id"] == request), None)
        if not plan:
            raise ValueError("Prospective plan unavailable")
        start, end = plan["spec"]["starts_at"], plan["ends_at"]
        drift = [
            name
            for name, frozen in plan["configurations"].items()
            if name not in state["accounts"] or config(state["accounts"][name]) != frozen
        ]
        if plan["source_sha256"] != review_fingerprint():
            drift.append("Evaluator source changed")
        selected = [
            w for w in windows["windows"] if start <= w["start"] and w["end"] <= min(now, end)
        ]
        candidate = plan["spec"]["candidate"]
        result = (
            comparison(
                state,
                candidate,
                selected,
                now,
                start - 1,
                truncated=windows.get("truncated", False),
            )
            if candidate
            else None
        )
        report = {
            "plan_sha256": digest(plan),
            "observed_at": now,
            "status": "waiting" if now < start else "insufficient" if now < end else "complete",
            "decision": "no_promotion",
            "configuration_drift": drift,
            "candidate_comparison": result,
            "complete_windows": len(selected),
            "combined_components": len(plan["components"]),
            "whole_account_effect": result.get("mean_daily_paired_return") if result else None,
            "reason": "No justified combined candidate"
            if not candidate
            else "CP7 evidence and separate human paper-role approval remain required",
            "failure_attribution": "Unresolved without independent executable evidence",
            "next_experiment": "Repair coverage before extending model complexity",
            "search_history": {
                row["status"]: row["n"]
                for row in self.registry.db.execute(
                    "SELECT status,count(*) n FROM experiments GROUP BY status"
                )
            },
            "financial_authority": False,
            "paid_usd": "0",
            "live_execution": False,
        }
        # Every inspection remains a permanent stage. No deletion or trial reset.
        with self.registry.transaction():
            self.journal.put(
                request, "inspection-" + digest(report), now, "prospective_inspection", report
            )
        return report
