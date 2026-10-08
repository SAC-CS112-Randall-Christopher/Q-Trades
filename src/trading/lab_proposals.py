"""One inbox/evaluation path in the existing research registry for all proposal sources."""

import json
import time
from collections.abc import Callable
from typing import Any

from trading.autonomous_spec import LabProposal, RuleSpec
from trading.experiment_registry import ExperimentRegistry, fingerprint


class LabProposals:
    def __init__(self, registry: ExperimentRegistry):
        self.registry = registry
        self.finite_validator: Callable[[dict[str, Any], LabProposal], None] | None = None
        with registry.lock:
            registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS lab_bundles(
                    sha256 TEXT PRIMARY KEY, at REAL NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lab_proposals(
                    seq INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    created REAL NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL,
                    rule_sha256 TEXT NOT NULL, kind TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT, evaluation TEXT,
                    trial_id TEXT, finished REAL);
                CREATE INDEX IF NOT EXISTS lab_proposal_queue ON lab_proposals(status,seq);
                CREATE INDEX IF NOT EXISTS lab_rule_history ON lab_proposals(rule_sha256,status);
                CREATE TRIGGER IF NOT EXISTS lab_bundle_immutable BEFORE UPDATE ON lab_bundles
                  BEGIN SELECT RAISE(ABORT,'Issued proposer evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS lab_bundle_retained BEFORE DELETE ON lab_bundles
                  BEGIN SELECT RAISE(ABORT,'Issued proposer evidence is retained'); END;
                CREATE TRIGGER IF NOT EXISTS lab_proposal_retained BEFORE DELETE ON lab_proposals
                  BEGIN SELECT RAISE(ABORT,'Attempted proposals are retained'); END;
                CREATE TRIGGER IF NOT EXISTS lab_proposal_frozen BEFORE UPDATE ON lab_proposals
                  WHEN NEW.body<>OLD.body OR NEW.sha256<>OLD.sha256
                  OR NEW.rule_sha256<>OLD.rule_sha256 OR NEW.kind<>OLD.kind
                  OR (OLD.evaluation IS NOT NULL AND NEW.evaluation IS NOT OLD.evaluation)
                  BEGIN SELECT RAISE(ABORT,'Proposal and evaluation are frozen'); END;
                CREATE TABLE IF NOT EXISTS lab_finite_proposals(
                    grant_id TEXT PRIMARY KEY,proposal_id TEXT UNIQUE NOT NULL,
                    body TEXT NOT NULL,sha256 TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS lab_finite_proposal_frozen
                  BEFORE UPDATE ON lab_finite_proposals
                  BEGIN SELECT RAISE(ABORT,'Finite proposal authority is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS lab_finite_proposal_retained
                  BEFORE DELETE ON lab_finite_proposals
                  BEGIN SELECT RAISE(ABORT,'Finite proposal authority is retained'); END;
            """)
        if "next_retry" not in {
            row[1] for row in registry.db.execute("PRAGMA table_info(lab_proposals)")
        }:
            with registry.transaction():
                registry.db.execute(
                    "ALTER TABLE lab_proposals ADD COLUMN next_retry REAL NOT NULL DEFAULT 0"
                )

    def bundle(self, body: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(body, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Permitted research bundle exceeds its declared bound")
        with self.registry.transaction():
            # Serialize disclosure with the same BEGIN IMMEDIATE used by holdouts.
            # An evaluation winning this race withholds its interval from the bundle.
            # Previously disclosed training is reusable, but never untouched evidence.
            body = json.loads(encoded)
            evidence = body.get("evidence", {})
            for key in ("training_episodes", "completed_trials"):
                permitted = []
                for item in evidence.get(key, []):
                    start = item.get("cutoff", item.get("window_start"))
                    end = item.get("available_at")
                    if start is None or end is None:
                        continue
                    overlap = self.registry.db.execute(
                        "SELECT 1 FROM evidence_windows WHERE start<=? AND end>=? "
                        "AND origin<>'lab proposer disclosure' LIMIT 1",
                        (end, start),
                    ).fetchone()
                    prospective = self.registry.db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='prospective_plans'"
                    ).fetchone()
                    if prospective:
                        prospective = self.registry.db.execute(
                            "SELECT 1 FROM prospective_plans WHERE start<=? AND end>=? LIMIT 1",
                            (end, start),
                        ).fetchone()
                    if overlap or prospective:
                        continue
                    exposure = "lab-exposure:" + fingerprint(
                        {
                            "source": key,
                            "identity": item.get("episode", item.get("trial_id")),
                            "start": start,
                            "end": end,
                        }
                    )
                    self.registry.db.execute(
                        "INSERT OR IGNORE INTO evidence_windows "
                        "VALUES(?,?,?,'lab proposer disclosure')",
                        (exposure, start, end),
                    )
                    permitted.append(item)
                if key in evidence:
                    evidence[key] = permitted
            if "novelty_sha256" in body:
                body["novelty_sha256"] = fingerprint(evidence)
            sha = fingerprint(body)
            encoded = json.dumps(body, sort_keys=True, allow_nan=False)
            self.registry.db.execute(
                "INSERT OR IGNORE INTO lab_bundles VALUES(?,?,?)", (sha, time.time(), encoded)
            )
        return {"sha256": sha, "bundle": body}

    def submit(
        self,
        proposal: LabProposal,
        evaluation: dict[str, Any],
        *,
        rejection: str | None = None,
        _finite_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = self.registry
        if _finite_scope is not None:
            _finite_scope = json.loads(json.dumps(_finite_scope, sort_keys=True, allow_nan=False))
        digest = fingerprint(proposal.model_dump())
        rule = fingerprint(proposal.strategy.model_dump())
        with r.transaction():
            old = r.db.execute(
                "SELECT * FROM lab_proposals WHERE request_id=?", (proposal.request_id,)
            ).fetchone()
            if old:
                if old["sha256"] != digest:
                    raise ValueError("Proposal identity cannot be rewritten")
                if _finite_scope is not None and self.finite_scope(proposal) != _finite_scope:
                    raise ValueError("Existing proposal has different finite authority")
                return self.get(proposal.request_id)
            if _finite_scope is not None:
                self.validate_finite_scope(_finite_scope, proposal)
                if r.db.execute(
                    "SELECT 1 FROM lab_finite_proposals WHERE grant_id=? OR proposal_id=?",
                    (_finite_scope["grant_id"], proposal.request_id),
                ).fetchone():
                    raise ValueError("Finite investigation already owns its one proposal")
            if not r.db.execute(
                "SELECT 1 FROM lab_bundles WHERE sha256=?", (proposal.evidence_bundle_sha256,)
            ).fetchone():
                raise ValueError(
                    "Proposal must cite the exact server-issued evidence bundle it received"
                )
            reason = rejection
            builtin = {
                "reviewed-breakout-v1": RuleSpec(),
                "reviewed-breakout-medium-v2": RuleSpec(holding_horizon="medium"),
                "reviewed-breakout-long-v2": RuleSpec(holding_horizon="long"),
            }
            if proposal.kind == "replication" and proposal.replication_of not in builtin:
                prior = r.db.execute(
                    (
                        "SELECT rule_sha256 FROM lab_proposals WHERE request_id=? AND "
                        "status='completed'"
                    ),
                    (proposal.replication_of,),
                ).fetchone()
                if not prior or prior["rule_sha256"] != rule:
                    reason = (
                        "Replication must identify completed evidence with exactly matching rules"
                    )
            elif proposal.kind == "replication" and proposal.strategy != builtin.get(
                proposal.replication_of or ""
            ):
                reason = "Reviewed breakout replication must use its exact reviewed rules"
            if proposal.kind != "replication" and self.used(rule):
                reason = (
                    "Equivalent reviewed settings were already attempted; label an "
                    "exact replication"
                )
            if not self.has_capacity():
                raise ValueError(
                    "Four active proposal jobs already queued; wait for bounded dispatch"
                )
            status = "rejected" if reason else "evaluated"
            if _finite_scope is not None:
                # Claim and inbox publication share the existing transaction. A
                # failed INSERT/event publishes neither; acknowledged intent is
                # permanent even when the model's later authority is stopped.
                self.validate_finite_scope(_finite_scope, proposal)
                r.db.execute(
                    "INSERT INTO lab_finite_proposals VALUES(?,?,?,?)",
                    (
                        _finite_scope["grant_id"],
                        proposal.request_id,
                        json.dumps(_finite_scope, sort_keys=True, allow_nan=False),
                        fingerprint(_finite_scope),
                    ),
                )
            r.db.execute(
                (
                    "INSERT INTO "
                    "lab_proposals(request_id,created,body,sha256,rule_sha256,kind,status,reason,evaluation)"
                    " VALUES(?,?,?,?,?,?,?,?,?)"
                ),
                (
                    proposal.request_id,
                    time.time(),
                    json.dumps(proposal.model_dump(), sort_keys=True),
                    digest,
                    rule,
                    proposal.kind,
                    status,
                    reason,
                    json.dumps(evaluation, sort_keys=True),
                ),
            )
            r.event(
                proposal.request_id,
                "lab_proposal_" + status,
                {
                    "source": proposal.source,
                    "bundle_sha256": proposal.evidence_bundle_sha256,
                    "reason": reason,
                    "financial_authority": False,
                },
            )
        return self.get(proposal.request_id)

    def validate_finite_scope(self, scope: dict[str, Any], proposal: LabProposal) -> None:
        if (
            type(scope) is not dict
            or scope.get("proposal_id") != proposal.request_id
            or scope.get("proposal_sha") != fingerprint(proposal.model_dump())
            or not callable(self.finite_validator)
        ):
            raise ValueError("Finite proposal requires its exact claimed worker authority")
        self.finite_validator(scope, proposal)

    def finite_scope(self, proposal: LabProposal) -> dict[str, Any] | None:
        """Read immutable authority before acquiring the transport's dispatch fence."""
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT body,sha256 FROM lab_finite_proposals WHERE proposal_id=?",
                (proposal.request_id,),
            ).fetchone()
        if row is None:
            return None
        scope: dict[str, Any] = json.loads(row["body"])
        if (
            fingerprint(scope) != row["sha256"]
            or scope.get("proposal_id") != proposal.request_id
            or scope.get("proposal_sha") != fingerprint(proposal.model_dump())
        ):
            raise ValueError("Retained finite proposal authority differs")
        return scope

    def has_capacity(self) -> bool:
        with self.registry.lock:
            queued = self.registry.db.execute(
                "SELECT count(*) FROM lab_proposals "
                "WHERE status IN ('evaluated','reserved','blocked')"
            ).fetchone()[0]
            return bool(queued < 4)

    def used(self, rule_sha256: str) -> bool:
        with self.registry.lock:
            return (
                self.registry.db.execute(
                    (
                        "SELECT 1 FROM lab_proposals WHERE rule_sha256=? AND "
                        "status<>'rejected' LIMIT 1"
                    ),
                    (rule_sha256,),
                ).fetchone()
                is not None
            )

    def get(self, request_id: str) -> dict[str, Any]:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT * FROM lab_proposals WHERE request_id=?", (request_id,)
            ).fetchone()
        if not row:
            raise ValueError("Unknown proposal")
        result = dict(row)
        result["body"] = json.loads(row["body"])
        result["evaluation"] = json.loads(row["evaluation"]) if row["evaluation"] else None
        return result

    def next(self, now: float | None = None) -> dict[str, Any] | None:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT request_id FROM lab_proposals WHERE status IN "
                "('evaluated','reserved','blocked') AND next_retry<=? ORDER BY seq LIMIT 1",
                (time.time() if now is None else now,),
            ).fetchone()
        return self.get(row["request_id"]) if row else None

    def update(
        self,
        request_id: str,
        status: str,
        trial_id: str | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        if status not in {"reserved", "funded", "completed", "rejected"}:
            raise ValueError("Unsupported proposal lifecycle")
        with self.registry.transaction():
            changed = self.registry.db.execute(
                (
                    "UPDATE lab_proposals SET "
                    "status=?,trial_id=COALESCE(trial_id,?),finished=?,reason=?,next_retry=0 WHERE "
                    "request_id=? AND status NOT IN ('completed','rejected')"
                ),
                (
                    status,
                    trial_id,
                    time.time() if status in {"completed", "rejected"} else None,
                    reason,
                    request_id,
                ),
            ).rowcount
            if changed and status == "rejected":
                self.registry.event(
                    request_id,
                    "lab_proposal_rejected",
                    {"reason": reason, "financial_authority": False},
                )

    def defer(self, request_id: str, reason: str, next_retry: float) -> None:
        with self.registry.transaction():
            changed = self.registry.db.execute(
                "UPDATE lab_proposals SET status='blocked',reason=?,next_retry=? "
                "WHERE request_id=? AND status IN ('evaluated','blocked')",
                (reason[:300], next_retry, request_id),
            ).rowcount
            if changed:
                self.registry.event(
                    request_id,
                    "lab_proposal_blocked",
                    {"reason": reason, "next_retry": next_retry, "financial_authority": False},
                )

    def defer_reserved(self, request_id: str, reason: str, next_retry: float) -> None:
        """Preserve the existing reserved intent while new funding is refused."""
        with self.registry.transaction():
            self.registry.db.execute(
                "UPDATE lab_proposals SET reason=?,next_retry=? "
                "WHERE request_id=? AND status='reserved'",
                (reason[:300], next_retry, request_id),
            )

    def retry_due(self) -> float | None:
        with self.registry.lock:
            due = self.registry.db.execute(
                "SELECT min(next_retry) FROM lab_proposals WHERE status='blocked'"
            ).fetchone()[0]
            return float(due) if due is not None else None

    def unfinished_funded(self) -> list[dict[str, Any]]:
        with self.registry.lock:
            return [
                dict(r)
                for r in self.registry.db.execute(
                    "SELECT request_id,trial_id FROM lab_proposals WHERE status='funded' "
                    "ORDER BY seq LIMIT 20"
                )
            ]

    def page(self, before: int = 0) -> dict[str, Any]:
        with self.registry.lock:
            rows = self.registry.db.execute(
                (
                    "SELECT seq,request_id,status,reason,trial_id,created FROM "
                    "lab_proposals WHERE (?=0 OR seq<?) ORDER BY seq DESC LIMIT 21"
                ),
                (before, before),
            ).fetchall()
            counts = self.registry.db.execute(
                "SELECT status,count(*) AS count FROM lab_proposals GROUP BY status"
            ).fetchall()
        return {
            "proposals": [dict(r) for r in rows[:20]],
            "counts": [dict(r) for r in counts],
            "has_more": len(rows) > 20,
            "next_before": rows[19]["seq"] if len(rows) > 20 else None,
        }
