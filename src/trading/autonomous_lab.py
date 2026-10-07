"""Bounded application supervisor; the existing paper writer owns financial effects."""

import json
import shutil
import sqlite3
import time
from collections.abc import Callable
from typing import Any

import psycopg

from trading import autonomous_finance as finance
from trading.account_purpose import research_account
from trading.autonomous_spec import ORIGINALS, LabPolicy, LabProposal, RuleSpec
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.lab_proposals import LabProposals
from trading.paper_economics import sample
from trading.paper_engine import PaperEngine, fresh_frame
from trading.paper_runtime import PaperRuntime
from trading.research_activity import sqlite_rows
from trading.research_evidence import digest
from trading.research_storage import compact_path, load_plan, storage_snapshot
from trading.rule_components import reviewed_feature


class InputWait(ValueError):
    """Fresh causal inputs are temporarily unavailable; preserve the queued proposal."""


class AutonomousLab:
    def __init__(
        self, registry: ExperimentRegistry, paper: PaperRuntime, can_research: Callable[[], bool]
    ):
        self.registry, self.paper, self.can_research = registry, paper, can_research
        self.inbox = LabProposals(registry)
        self.last_error: str | None = None

    def start(self, policy: LabPolicy) -> dict[str, Any]:
        self.paper.require_healthy_control()
        result: dict[str, Any] = {}
        self.paper._transact_state(time.time(), lambda e: result.update(finance.start(e, policy)))
        return result

    def control(self, action: str, target: str | None) -> dict[str, Any]:
        self.paper.require_healthy_control()
        result: dict[str, Any] = {}
        self.paper._transact_state(
            time.time(), lambda e: result.update(finance.control(e, action, target))
        )
        return result

    def bundle(self, now: float) -> dict[str, Any]:
        lab = self.paper.state.get("autonomous_lab", {})
        episodes = []
        path = compact_path(self.registry.path.parent)
        if path.exists():
            rows = sqlite_rows(
                path,
                "SELECT p.episode,p.cutoff,p.available,p.body,p.sha256,o.body AS outcome "
                ",o.sha256 AS outcome_sha FROM compact_prefixes p "
                "LEFT JOIN compact_outcomes o ON p.episode=o.episode ORDER BY p.seq DESC LIMIT 16",
            )
            for row in rows:
                from trading.outcome_continuation import continued_outcome

                prefix = json.loads(row["body"])
                label = (
                    json.loads(row["outcome"])
                    if row["outcome"]
                    else continued_outcome(
                        path.parent, "compact", row["episode"], row["sha256"], now
                    )
                )
                if not label or label.get("status") != "available":
                    continue
                if row["outcome"] and digest(label) != row["outcome_sha"]:
                    raise ValueError("Disclosed outcome checksum differs; proposal inputs blocked")
                end = label["available_at"]
                if max(row["available"], end) > now or digest(prefix) != row["sha256"]:
                    continue
                with self.registry.lock:
                    protected = self.registry.db.execute(
                        "SELECT 1 FROM evidence_windows WHERE start<=? AND end>=? "
                        "AND origin<>'lab proposer disclosure' LIMIT 1",
                        (end, row["cutoff"]),
                    ).fetchone()
                    prospective = self.registry.db.execute(
                        "SELECT 1 FROM prospective_plans WHERE start<=? AND end>=? LIMIT 1",
                        (end, row["cutoff"]),
                    ).fetchone()
                if protected or prospective:
                    continue
                episodes.append(
                    {
                        "episode": row["episode"],
                        "sha256": row["sha256"],
                        "archive_type": "compact",
                        "cutoff": row["cutoff"],
                        "available_at": end,
                        "net_bps": label["net_bps"],
                        "coverage": label.get("coverage"),
                        "training_only": True,
                    }
                )
        with self.paper.store.transaction_lock:
            recent = self.paper.store.connection.execute(
                "SELECT body FROM paper_events "
                "WHERE kind='lab_trial_scored' ORDER BY id DESC LIMIT 12"
            ).fetchall()
        keys = (
            "trial_id",
            "proposal_id",
            "outcome",
            "available_at",
            "delta_usd",
            "net_after_operating_usd",
            "reason",
            "window_end",
            "window_start",
        )
        scores = [
            {k: r["body"].get(k) for k in keys} for r in recent if r["body"]["available_at"] <= now
        ]
        bars = self.paper.history.get("BTCUSD", [])
        evidence = {"training_episodes": episodes, "completed_trials": scores}
        return self.inbox.bundle(
            {
                "schema": "permitted-lab-bundle-v1",
                "as_of": now,
                "policy_id": lab.get("policy", {}).get("request_id"),
                "evidence": evidence,
                "current_inputs": {
                    "last_closed_at": bars[-1].close_ms / 1000 if bars else None,
                    "retained_candles": len(bars),
                },
                "novelty_sha256": fingerprint(evidence),
                "uncertainty": "Shared data and sibling outcomes are correlated; no qualification",
                "protected_evaluation": "Withheld; exposed outcomes are training information only",
                "permissions": (
                    "Reviewed configurations; no SQL, code, credentials or financial authority"
                ),
            }
        )

    def submit(self, proposal: LabProposal, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        evaluation = self.evaluate(proposal, now)
        rejection = None
        try:
            finance.validate_parent(self.paper.state, proposal)
        except finance.InvalidProposal as exc:
            rejection = str(exc)
        result = self.inbox.submit(proposal, evaluation, rejection=rejection)
        recorder = getattr(self.paper, "evidence", None)
        if recorder is not None and result["status"] == "evaluated":
            p = LabPolicy.model_validate(self.paper.state["autonomous_lab"]["policy"])
            recorder.enqueue(
                {
                    "schema": "causal-evidence-v1",
                    "kind": "lab_inputs",
                    "at": now,
                    "proposal": proposal.model_dump(),
                    "evaluation": evaluation,
                    "protected_until": now
                    + max(p.horizon_seconds, proposal.strategy.timing["review"])
                    + 86400,
                }
            )
        return result

    def evaluate(self, proposal: LabProposal, now: float) -> dict[str, Any]:
        """Existing deterministic prospective check; no inbox or financial effects."""
        lab = self.paper.state.get("autonomous_lab")
        if not lab or proposal.policy_id != lab["policy"]["request_id"]:
            raise ValueError("Start a declared lab policy before submitting an experiment")
        p = LabPolicy.model_validate(lab["policy"])
        if proposal.strategy.holding_horizon not in p.holding_horizons:
            raise ValueError("Proposed holding horizon is outside the frozen policy")
        bars = (
            self.paper.history.get("BTCUSD", [])[-600:]
            if proposal.strategy.version == "reviewed-lab-rules-v4"
            else self.paper.lab_history(now, proposal.strategy.holding_horizon)
        )
        frames = self.paper.control_frames()
        feature = reviewed_feature(
            bars, now, proposal.strategy, p.execution_profile, self.paper.memory_book("BTCUSD")
        )
        available = feature.get("input_available_at")
        if (
            not fresh_frame(frames.get("BTCUSD"), now)
            or len(bars) < 305
            or "atr" not in feature
            or available is None
            or not 0
            <= now - available
            <= (300 if proposal.strategy.version == "reviewed-lab-rules-v4" else 90)
        ):
            raise InputWait("Awaiting contiguous causal candles and a fresh executable book")
        return {
            "status": "supported_exploratory_configuration",
            "evaluated_at": now,
            "expires_at": now + 90,
            "feature": feature,
            "inputs": [
                {
                    "open_ms": b.open_ms,
                    "close_ms": b.close_ms,
                    "open": str(b.open),
                    "high": str(b.high),
                    "low": str(b.low),
                    "close": str(b.close),
                    "volume": str(b.volume),
                }
                for b in bars[
                    -600 if proposal.strategy.version == "reviewed-lab-rules-v4" else -9000 :
                ]
            ],
            "financial_authority": False,
            "profit_required": False,
            "replay": "No new historical replay claimed; compare subsequent executable accounts",
        }

    def _family_available(self, family: str, independent: bool = False) -> bool:
        lab = self.paper.state["autonomous_lab"]
        policy = LabPolicy.model_validate(lab["policy"])
        used = finance.slots(self.paper.state)["used"]

        def size(t: dict[str, Any]) -> int:
            return (
                2
                if t["status"] == "reserved"
                else sum(
                    t[key] in self.paper.state["accounts"] for key in ("candidate", "reference")
                )
            )

        trials = list(lab["trials"].values())
        same = sum(
            size(t) for t in trials if t["contract"]["proposal"]["strategy"]["family"] == family
        )
        independent_used = sum(
            size(t) for t in trials if t["contract"]["proposal"]["kind"] == "independent"
        )
        keep = 0 if independent else max(0, policy.independent_slots - independent_used)
        return used + 2 + keep <= policy.slots and same + 2 <= policy.family_slots

    def propose(self, now: float) -> LabProposal | None:
        lab = self.paper.state["autonomous_lab"]
        trials = list(lab["trials"].values())
        horizons = lab["policy"].get("holding_horizons", ["short"])
        base = RuleSpec(holding_horizon=horizons[0])
        issued = self.bundle(now)
        parents = [t for t in trials if t["status"] == "preserved" and not t["branched"]]
        for parent in parents:
            parent_account = self.paper.state["accounts"].get(parent["candidate"], {})
            if (
                not parent_account
                or not research_account(parent_account, parent["candidate"])
                or parent_account.get("risk_stop_id")
                or parent_account.get("fault")
                or parent_account.get("lab_retiring")
            ):
                continue
            reference = RuleSpec.model_validate(parent["contract"]["proposal"]["strategy"])
            if not self._family_available(reference.family):
                continue
            labels = issued["bundle"]["evidence"]["training_episodes"]
            mean = sum(float(e["net_bps"]) for e in labels) / len(labels) if labels else 0
            direction = -1 if mean > 0 else 1
            candidates = sorted(
                (n for n in range(5, 31) if n != reference.lookback),
                key=lambda n: (abs(n - reference.lookback), n * direction),
            )
            for n in candidates:
                spec = reference.model_copy(update={"lookback": n})
                if self.inbox.used(fingerprint(spec.model_dump())):
                    continue
                return LabProposal(
                    request_id="proposal-"
                    + fingerprint({"parent": parent["id"], "spec": spec.model_dump()})[:24],
                    policy_id=lab["policy"]["request_id"],
                    source="deterministic",
                    kind="variation",
                    strategy=spec,
                    reference=reference,
                    parent_trial=parent["id"],
                    parent_strategy_sha256=fingerprint(reference.model_dump()),
                    mechanism="Change the lookback; retain parent's costs, sizing, risk and exits",
                    question=f"Does lookback {n} improve the matched result? Training-label mean "
                    f"{mean:.3f} bps informs direction; it is not fresh confirmation.",
                    evidence_bundle_sha256=issued["sha256"],
                )
        if not self.inbox.used(fingerprint(base.model_dump())):
            if not self._family_available("breakout"):
                return None
            return LabProposal(
                request_id="proposal-"
                + fingerprint({"policy": lab["policy"]["request_id"], "seed": True})[:24],
                policy_id=lab["policy"]["request_id"],
                source="deterministic",
                kind="replication",
                strategy=base,
                reference=base,
                replication_of="reviewed-breakout-v1"
                if base.holding_horizon == "short"
                else "reviewed-breakout-" + base.holding_horizon + "-v2",
                mechanism="Reproduce the reviewed baseline in fresh matched accounts",
                question=(
                    "Can the baseline earn positive after-cost value in a complete new window?"
                ),
                evidence_bundle_sha256=issued["sha256"],
            )
        scores = issued["bundle"]["evidence"]["completed_trials"]
        # Rotate durable admissions across declared horizons. A slow active
        # trial keeps its fixed window and cannot be shortened by faster siblings.
        horizon = horizons[lab.get("horizon_cursor", 0) % len(horizons)]
        base = RuleSpec(holding_horizon=horizon)
        if self._family_available("range_reversion", True) and not any(
            t["contract"]["proposal"]["kind"] == "independent" and t["status"] != "preserved"
            for t in trials
        ):
            direction = -1 if scores and scores[0]["outcome"] == "economically_unsuccessful" else 1
            for n in sorted(range(5, 31), key=lambda n: (abs(n - 20), n * direction)):
                spec = RuleSpec(family="range_reversion", lookback=n, holding_horizon=horizon)
                if self.inbox.used(fingerprint(spec.model_dump())):
                    continue
                if n != 20 and not scores:
                    break
                return LabProposal(
                    request_id="proposal-"
                    + fingerprint(
                        {"policy": lab["policy"]["request_id"], "spec": spec.model_dump()}
                    )[:24],
                    policy_id=lab["policy"]["request_id"],
                    source="deterministic",
                    kind="independent",
                    strategy=spec,
                    reference=base,
                    mechanism="Test range-conditioned negative excursion instead of breakout entry",
                    question=f"Does a {n}-bar range gate at {spec.timing['feature_seconds']} "
                    "seconds per bar resolve the latest uncertainty?",
                    evidence_bundle_sha256=issued["sha256"],
                )
        # Configuration exhaustion permits an explicitly labelled replication using
        # a subsequent window, rather than rebranding inspected data as fresh proof.
        if not scores or any(t["status"] in {"reserved", "active"} for t in trials):
            return None
        latest = scores[0]
        closed = issued["bundle"]["current_inputs"]["last_closed_at"]
        if closed is None or closed <= latest["window_end"]:
            return None
        prior = self.inbox.get(latest["proposal_id"])
        spec = RuleSpec.model_validate(prior["body"]["strategy"])
        if not self._family_available(spec.family):
            return None
        return LabProposal(
            request_id="proposal-" + fingerprint({"replicate_after": latest["trial_id"]})[:24],
            policy_id=lab["policy"]["request_id"],
            source="deterministic",
            kind="replication",
            strategy=spec,
            reference=spec,
            replication_of=latest["proposal_id"],
            mechanism="Repeat a completed frozen hypothesis in a later, separately recorded window",
            question=f"Does {latest['outcome']} recur in a subsequent window? "
            "The earlier result selects this test, not its confirmation.",
            evidence_bundle_sha256=issued["sha256"],
        )

    def _state(self, now: float, phase: str, reason: str, delay: float) -> None:
        def apply(engine: Any) -> None:
            lab = engine.state["autonomous_lab"]
            finance.periods(lab, now)
            lab.update(phase=phase, reason=reason, next_action_at=now + delay)

        self.paper.state = self.paper.store.transact(now, apply)

    def _budget(self, now: float, elapsed: float | None = None) -> None:
        def apply(engine: Any) -> None:
            lab = engine.state["autonomous_lab"]
            finance.periods(lab, now)
            b = lab["budget"]
            if elapsed is None:
                # Commit conservative consumption BEFORE dispatch; crashes cannot
                # restore that hour's allowance. There is no provider spending.
                b["steps"] += 1
                b["compute_seconds"] += 1
                lab["last_work_at"] = now
            else:
                b["measured_seconds"] += elapsed
                b["compute_seconds"] += max(0, elapsed - 1)

        self.paper.state = self.paper.store.transact(now, apply)

    def step(self, now: float | None = None) -> bool:
        with self.paper.store.transaction_lock:
            try:
                self.paper.state = self.paper.store.read()
                return self._step(time.time() if now is None else now)
            except (psycopg.Error, RuntimeError, sqlite3.Error, OSError, ValueError) as exc:
                self.last_error = str(exc)[:300]
                return False

    def _step(self, now: float) -> bool:
        lab = self.paper.state.get("autonomous_lab")
        if not lab or now < lab["next_action_at"]:
            return False
        self.last_error = None
        policy = LabPolicy.model_validate(lab["policy"])
        if (
            not self.paper.running
            or self.paper.error
            or not 0 <= now - self.paper.state["last_tick"] <= 10
        ):
            self._state(
                now, "waiting", "Paper collection/health unavailable; no invented outcomes", 30
            )
            return False
        if not self.can_research():
            self._state(
                now, "waiting", "Research yielding to position management/resource guard", 30
            )
            return False
        files = (
            self.registry.path,
            self.registry.path.with_name(self.registry.path.name + "-wal"),
            self.registry.path.with_name(self.registry.path.name + "-shm"),
        )
        physical = sum(p.stat().st_size for p in files if p.exists())
        if (
            shutil.disk_usage(self.registry.path.parent).free < policy.minimum_disk_gib * 1024**3
            or physical > policy.registry_mib * 1024**2
        ):
            self._state(
                now,
                "storage_blocked",
                "Research capacity reached; retain evidence and exits",
                policy.cooldown_seconds,
            )
            return False
        b = lab["budget"]
        if b["hour"] == int(now // 3600) and (
            b["steps"] >= policy.hourly_steps
            or b["compute_seconds"] + 1 > policy.hourly_compute_seconds
        ):
            self._state(
                now,
                "budget_wait",
                "UTC hourly work/allocated-time budget exhausted",
                3600 - now % 3600,
            )
            return False
        started = time.perf_counter()
        self._budget(now)
        try:
            for pending in self.inbox.unfinished_funded():
                scored = self.paper.store.connection.execute(
                    "SELECT id FROM paper_events WHERE kind IN "
                    "('lab_trial_scored','lab_trial_retired') AND body->>'trial_id'=%s LIMIT 1",
                    (pending["trial_id"],),
                ).fetchone()
                if scored:
                    self.inbox.update(pending["request_id"], "completed", pending["trial_id"])
                    self._state(now, "recovered", "Recovered committed outcome acknowledgment", 2)
                    return True
            for t in list(lab["trials"].values()):
                if t["status"] == "active" and t.get("sealed"):
                    result: dict[str, Any] = {}
                    trial = t["id"]

                    def score(
                        engine: PaperEngine, result: dict[str, Any] = result, trial: str = trial
                    ) -> None:
                        result.update(finance.review(engine, trial))

                    self.paper.state = self.paper.store.transact(now, score)
                    self.inbox.update(t["proposal_id"], "completed", t["id"])
                    self._state(now, "scored", result["reason"], 2)
                    return True
            if lab["proposals_paused"] or self.paper.state["paused"]:
                self._state(now, "paused", "Proposals paused; management and history continue", 30)
                return False
            if load_plan(self.registry.path.parent) is not None:
                storage = storage_snapshot(self.registry.path.parent)
                if storage.get("state") != "recording" or now - storage.get("receipt_at", 0) > 30:
                    self._state(
                        now,
                        "capture_blocked",
                        "External capture unavailable; new trials paused, exits continue",
                        60,
                    )
                    return False
            queued = self.inbox.next(now)
            if queued:
                proposal = LabProposal.model_validate(queued["body"])
                if queued["status"] in {"evaluated", "blocked"}:
                    try:
                        submitted = self.submit(proposal, now)
                        if submitted["status"] == "rejected":
                            self._state(now, "rejected", submitted["reason"], 2)
                            return True
                        receipt = self.paper.store.lab_reserve(now, proposal)
                    except finance.InvalidProposal as exc:
                        self.inbox.update(proposal.request_id, "rejected", reason=str(exc))
                        self._state(now, "rejected", str(exc), 2)
                        return True
                    except (finance.AdmissionWait, InputWait) as exc:
                        self.inbox.defer(
                            proposal.request_id, str(exc), now + policy.cooldown_seconds
                        )
                        self._state(now, "proposal_wait", str(exc), 2)
                        return False
                    self.paper.state = self.paper.store.read()
                    self.inbox.update(proposal.request_id, "reserved", receipt["trial_id"])
                    self._state(now, "reserved", "Durable slot intent reserved; funding is next", 2)
                else:
                    trial_id = queued["trial_id"]
                    if trial_id not in lab["trials"]:
                        self.inbox.update(proposal.request_id, "completed", trial_id)
                        self._state(now, "observe", "Retired intent retained; no resurrection", 2)
                    else:

                        def fund(engine: PaperEngine) -> None:
                            finance.fund(engine, trial_id)

                        self.paper.state = self.paper.store.transact(now, fund)
                        status = self.paper.state["autonomous_lab"]["trials"][trial_id]["status"]
                        if status != "reserved":
                            self.inbox.update(proposal.request_id, "funded", trial_id)
                        self._state(
                            now,
                            "observe",
                            "Paired trial awaits subsequent fixed-window evidence",
                            2,
                        )
                return True
            if b["day"] == int(now // 86400) and b["trials"] >= policy.daily_trials:
                self._state(
                    now,
                    "budget_wait",
                    "UTC daily trial-creation budget exhausted",
                    86400 - now % 86400,
                )
                return False
            # A deferred job owns its retry, not the whole discovery schedule.
            # Avoid issuing/consuming a bundle when the bounded inbox is full;
            # submit also checks capacity atomically against concurrent producers.
            if self.inbox.has_capacity():
                proposed = self.propose(now)
                if proposed:
                    self.submit(proposed, now)
                    self._state(now, "evaluated", "Supported exploratory proposal evaluated", 2)
                    return True
            retry_at = self.inbox.retry_due()
            if retry_at is not None:
                self._state(
                    now,
                    "proposal_wait",
                    "Queued proposals await their recorded retry",
                    max(2, retry_at - now),
                )
                return False
            self._state(
                now,
                "observe",
                "Awaiting fixed review, capacity or new permitted evidence",
                policy.cooldown_seconds,
            )
            return False
        except (ValueError, sqlite3.Error, OSError) as exc:
            self.last_error = str(exc)[:300]
            self._state(now, "waiting", self.last_error, policy.cooldown_seconds)
            return False
        finally:
            self._budget(now, time.perf_counter() - started)

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        lab = self.paper.state.get("autonomous_lab")
        return {
            "enabled": lab is not None,
            "lab": lab,
            "slots": finance.slots(self.paper.state),
            "accounts": {
                n: {
                    **sample(a, now),
                    "protected": n in ORIGINALS or a.get("lab_protected", False),
                    "draining": bool(a.get("lab_retiring")),
                    "risk_stop_id": a.get("risk_stop_id"),
                    "rule_spec": a.get("rule_spec"),
                    "entries_paused": a.get("entries_paused", False),
                }
                for n, a in self.paper.state["accounts"].items()
                if research_account(a, n)
            },
            "inbox": self.inbox.page(),
            "last_error": self.last_error,
            "financial_authority": "Existing sole paper writer only",
            "provider_required": False,
            "qualification": "No automatic incumbent/live promotion",
        }
