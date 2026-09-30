"""One inbox/evaluation path in the existing research registry for all proposal sources."""

import json
import time
from typing import Any

from trading.autonomous_spec import LabProposal, RuleSpec
from trading.experiment_registry import ExperimentRegistry, fingerprint


class LabProposals:
    def __init__(self, registry: ExperimentRegistry):
        self.registry = registry
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
            """)

    def bundle(self, body: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(body, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Permitted research bundle exceeds its declared bound")
        sha = fingerprint(body)
        with self.registry.transaction():
            self.registry.db.execute(
                "INSERT OR IGNORE INTO lab_bundles VALUES(?,?,?)", (sha, time.time(), encoded)
            )
        return {"sha256": sha, "bundle": body}

    def submit(self, proposal: LabProposal, evaluation: dict[str, Any]) -> dict[str, Any]:
        r = self.registry
        digest = fingerprint(proposal.model_dump())
        rule = fingerprint(proposal.strategy.model_dump())
        with r.transaction():
            old = r.db.execute(
                "SELECT * FROM lab_proposals WHERE request_id=?", (proposal.request_id,)
            ).fetchone()
            if old:
                if old["sha256"] != digest:
                    raise ValueError("Proposal identity cannot be rewritten")
                return self.get(proposal.request_id)
            if not r.db.execute(
                "SELECT 1 FROM lab_bundles WHERE sha256=?", (proposal.evidence_bundle_sha256,)
            ).fetchone():
                raise ValueError(
                    "Proposal must cite the exact server-issued evidence bundle it received"
                )
            reason = None
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
            elif (
                proposal.kind == "replication"
                and proposal.strategy != builtin.get(proposal.replication_of or "")
            ):
                reason = "Reviewed breakout replication must use its exact reviewed rules"
            if proposal.kind != "replication" and self.used(rule):
                reason = (
                    "Equivalent reviewed settings were already attempted; label an "
                    "exact replication"
                )
            queued = r.db.execute(
                "SELECT count(*) FROM lab_proposals WHERE status IN ('evaluated','reserved')"
            ).fetchone()[0]
            if queued >= 4:
                raise ValueError(
                    "Four active proposal jobs already queued; wait for bounded dispatch"
                )
            status = "rejected" if reason else "evaluated"
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

    def next(self) -> dict[str, Any] | None:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT request_id FROM lab_proposals WHERE status IN "
                "('evaluated','reserved') ORDER BY seq LIMIT 1"
            ).fetchone()
        return self.get(row["request_id"]) if row else None

    def update(self, request_id: str, status: str, trial_id: str | None = None) -> None:
        if status not in {"reserved", "funded", "completed", "rejected"}:
            raise ValueError("Unsupported proposal lifecycle")
        with self.registry.transaction():
            self.registry.db.execute(
                (
                    "UPDATE lab_proposals SET "
                    "status=?,trial_id=COALESCE(trial_id,?),finished=? WHERE "
                    "request_id=? AND status NOT IN ('completed','rejected')"
                ),
                (status, trial_id, time.time() if status == "completed" else None, request_id),
            )

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
