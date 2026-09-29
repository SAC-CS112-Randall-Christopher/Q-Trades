"""Finite observe/evaluate/retain cycles with immutable plans and no financial authority."""

import json
import math
import time
from collections.abc import Callable
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading.experiment_registry import TERMINAL, ExperimentPlan, ExperimentRegistry, fingerprint


class ResearchCampaignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,48}$")
    name: str = Field(min_length=3, max_length=90)
    first_test_start: float
    window_minutes: Literal[240] = 240
    iterations: int = Field(ge=2, le=8)
    expires_at: float
    worker_wall_budget_seconds: Literal[100, 200, 400] = 100
    paid_budget_usd: Literal["0"] = "0"

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if not all(math.isfinite(x) for x in (self.first_test_start, self.expires_at)):
            raise ValueError("Campaign boundaries must be finite")
        if not 0 < self.first_test_start < self.expires_at <= time.time() + 72 * 3600:
            raise ValueError("Declare a finite campaign ending within 72 hours")
        end = (
            self.first_test_start
            + (self.iterations - 1) * (self.window_minutes * 60 + 3660)
            + self.window_minutes * 60
        )
        if end > self.expires_at or self.iterations * 50 > self.worker_wall_budget_seconds:
            raise ValueError("All windows and two bounded attempts per fit must fit the budget")
        return self


class ResearchCampaigns:
    def __init__(
        self,
        registry: ExperimentRegistry,
        enqueue: Callable[[ExperimentPlan], dict[str, Any]],
        code_hash: Callable[[], str],
    ):
        self.registry, self.enqueue, self.code_hash = registry, enqueue, code_hash
        with registry.lock:
            registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS research_campaigns (
                    seq INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    spec TEXT NOT NULL, spec_sha256 TEXT NOT NULL, code_sha256 TEXT NOT NULL,
                    created REAL NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                    iteration INTEGER NOT NULL DEFAULT 0, active_request TEXT,
                    allocated_wall_seconds INTEGER NOT NULL DEFAULT 0,
                    last_dispatch REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT 'Observe',
                    phase TEXT NOT NULL DEFAULT 'observe'
                );
                CREATE TRIGGER IF NOT EXISTS immutable_research_campaign BEFORE UPDATE
                ON research_campaigns WHEN NEW.spec != OLD.spec
                    OR NEW.spec_sha256 != OLD.spec_sha256 OR NEW.code_sha256 != OLD.code_sha256
                    OR NEW.request_id != OLD.request_id
                    BEGIN SELECT RAISE(ABORT, 'Research campaign plans are frozen'); END;
                CREATE TRIGGER IF NOT EXISTS retain_research_campaign BEFORE DELETE
                ON research_campaigns
                    BEGIN SELECT RAISE(ABORT, 'Campaign history is permanent'); END;
            """)

    def create(self, spec: ResearchCampaignSpec) -> dict[str, Any]:
        r = self.registry
        with r.transaction():
            old = r.db.execute(
                "SELECT * FROM research_campaigns WHERE request_id=?", (spec.request_id,)
            ).fetchone()
            if old:
                if old["spec_sha256"] != fingerprint(spec.model_dump()):
                    raise ValueError("Campaign retry must preserve its frozen plan")
                return {"request_id": spec.request_id, "status": old["status"], "retry": True}
            if r.db.execute("SELECT count(*) FROM research_campaigns").fetchone()[0] >= 4:
                raise ValueError("Four campaigns retained; no history is pruned")
            if (
                r.db.execute(
                    "SELECT count(*) FROM research_campaigns WHERE status='active'"
                ).fetchone()[0]
                >= 2
            ):
                raise ValueError("Two active research campaigns allowed")
            end = r.db.execute("SELECT max(end) FROM evidence_windows").fetchone()[0]
            if spec.first_test_start - 3600 <= end:
                raise ValueError("Campaign must start after consumed evidence plus label purge")
            r.db.execute(
                "INSERT INTO research_campaigns(request_id,spec,spec_sha256,code_sha256,created) "
                "VALUES (?,?,?,?,?)",
                (
                    spec.request_id,
                    spec.model_dump_json(),
                    fingerprint(spec.model_dump()),
                    self.code_hash(),
                    time.time(),
                ),
            )
            r.event(
                spec.request_id,
                "campaign_frozen",
                {
                    "spec": spec.model_dump(),
                    "financial_authority": False,
                    "method": "Three registered mechanisms; simpler numerical alternative; no LLM",
                },
            )
        return {"request_id": spec.request_id, "status": "active", "retry": False}

    def step(self, now: float) -> None:
        r = self.registry
        # A single persistent supervisor owns scheduling. Registry leases fence fitting.
        with r.lock:
            campaigns = r.db.execute(
                "SELECT * FROM research_campaigns WHERE status='active' ORDER BY last_dispatch,seq"
            ).fetchall()
        for row in campaigns:
            spec = json.loads(row["spec"])
            cid, iteration, active = row["request_id"], row["iteration"], row["active_request"]
            if active:
                status = r.status(active)
                if status in TERMINAL:
                    job = r.get(active)
                    with r.transaction():
                        r.event(
                            cid,
                            "evaluate_retain_or_reject",
                            {
                                "experiment": active,
                                "status": status,
                                "decision": (job or {}).get("result", {}).get("decision", "reject")
                                if (job or {}).get("result")
                                else "reject",
                                "qualification": "No automatic admission or promotion",
                            },
                        )
                        r.db.execute(
                            "UPDATE research_campaigns SET iteration=iteration+1,"
                            "active_request=NULL,"
                            "phase='retain',reason='Outcome retained; observe next window' "
                            "WHERE request_id=? AND active_request=?",
                            (cid, active),
                        )
                    continue
                if status is not None:
                    if now > spec["expires_at"]:
                        self.cancel(cid, "Campaign wall-clock budget expired")
                    continue
                # Interrupted between linking and enqueue: reuse exactly the same intent.
            if iteration >= spec["iterations"] or now > spec["expires_at"]:
                with r.transaction():
                    reason = (
                        "Finite iterations completed"
                        if iteration >= spec["iterations"]
                        else ("Campaign wall-clock budget expired")
                    )
                    r.db.execute(
                        "UPDATE research_campaigns SET status='completed',reason=?,phase='retain' "
                        "WHERE request_id=?",
                        (reason, cid),
                    )
                    r.event(cid, "campaign_finished", {"reason": reason})
                continue
            start = spec["first_test_start"] + iteration * (spec["window_minutes"] * 60 + 3660)
            end = start + spec["window_minutes"] * 60
            if now < end:
                with r.transaction():
                    r.db.execute(
                        "UPDATE research_campaigns SET phase='observe',reason=? WHERE request_id=? "
                        "AND phase!='observe'",
                        ("Waiting for untouched window and matured labels", cid),
                    )
                continue
            if self.code_hash() != row["code_sha256"]:
                self.cancel(cid, "Registered evaluator changed; frozen campaign stopped")
                continue
            request_id = active or f"{cid}-i{iteration + 1}"
            plan = ExperimentPlan.model_validate(
                {
                    "request_id": request_id,
                    "name": spec["name"] + f" / {iteration + 1}",
                    "mechanism": "Evaluate all three fixed mechanisms with equal family coverage.",
                    "falsification": "Reject insufficient or unqualified evidence; no promotion.",
                    "experiment_mode": "distinct_families",
                    "horizon_minutes": 60,
                    # Frozen at the declared window end, never replaced on restart.
                    "as_of": float(end),
                    "test_start": float(start),
                    "test_end": float(end),
                }
            )
            with r.transaction():
                current = r.db.execute(
                    "SELECT status,active_request FROM research_campaigns WHERE request_id=?",
                    (cid,),
                ).fetchone()
                if current["status"] != "active":
                    continue
                if not current["active_request"]:
                    if row["allocated_wall_seconds"] + 50 > spec["worker_wall_budget_seconds"]:
                        raise ValueError("Campaign attempt budget exhausted")
                    r.db.execute(
                        "UPDATE research_campaigns SET active_request=?,allocated_wall_seconds="
                        "allocated_wall_seconds+50,last_dispatch=?,phase='experiment',reason=? "
                        "WHERE request_id=?",
                        (request_id, now, "Fixed hypothesis queued", cid),
                    )
                    r.event(
                        cid,
                        "observe_diagnose_hypothesize",
                        {
                            "iteration": iteration + 1,
                            "plan": plan.model_dump(),
                            "allocated_attempt_seconds": 50,
                            "family_coverage": "All three",
                        },
                    )
            try:
                self.enqueue(plan)
            except (ValueError, OSError):
                with r.transaction():
                    r.event(
                        cid,
                        "proposal_rejected",
                        {
                            "experiment": request_id,
                            "reason": "Protected overlap, queue limit or unavailable storage",
                        },
                    )
                    r.db.execute(
                        "UPDATE research_campaigns SET active_request=NULL,iteration=iteration+1,"
                        "phase='reject',reason='Proposal refused; search attempt retained' "
                        "WHERE request_id=?",
                        (cid,),
                    )
            break  # Fair dispatch: at most one acquisition per supervisory cycle.

    def cancel(self, request_id: str, reason: str = "Operator cancelled campaign") -> None:
        r = self.registry
        with r.transaction():
            row = r.db.execute(
                "SELECT active_request,status FROM research_campaigns WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if not row:
                raise ValueError("Unknown research campaign")
            if row["status"] != "active":
                return
            r.db.execute(
                "UPDATE research_campaigns SET status='cancelled',reason=?,phase='retain' "
                "WHERE request_id=?",
                (reason, request_id),
            )
            r.event(request_id, "campaign_cancelled", {"reason": reason})
            active = row["active_request"]
        if active:
            r.cancel(active)

    def snapshot(self) -> list[dict[str, Any]]:
        r = self.registry
        with r.lock:
            rows = r.db.execute(
                "SELECT * FROM research_campaigns ORDER BY seq DESC LIMIT 4"
            ).fetchall()
        return [dict(row, spec=json.loads(row["spec"])) for row in rows]

    def receipt(self, request_id: str) -> dict[str, Any]:
        r = self.registry
        with r.lock:
            row = r.db.execute(
                "SELECT * FROM research_campaigns WHERE request_id=?", (request_id,)
            ).fetchone()
            if not row:
                raise ValueError("Unknown research campaign")
            events = [
                dict(e)
                for e in r.db.execute(
                    "SELECT at,kind,body FROM experiment_events WHERE request_id=? ORDER BY seq",
                    (request_id,),
                )
            ]
        return dict(row, spec=json.loads(row["spec"]), events=events)
