"""Verified saved pattern -> immutable preparation, never experiment dispatch."""

import hashlib
import json
import math
import re
import time
from collections import deque
from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading.autonomous_lab import AutonomousLab, InputWait
from trading.autonomous_spec import LabPolicy, LabProposal, RuleSpec, contract
from trading.candle_history import native_bar
from trading.candle_patterns import ZONE_HALF_WIDTH, _visit, _volume_ratio, _Zone
from trading.experiment_registry import fingerprint
from trading.pattern_scanner import VERSION as SCANNER_VERSION
from trading.pattern_scanner import PatternScanner
from trading.research_evidence import canonical, digest
from trading.research_storage import reopen_evidence

VERSION = "saved-pattern-comparison-preparation-v1"
MAX_REQUESTS = 512
MAX_REFERENCES = 16
TRAINING_ORIGINS = (
    "Native historical pattern-map disclosure",
    "Exact retained native pattern input slice, including continuing observations",
    "lab proposer disclosure",
    "Pattern comparison preparation disclosure",
)
MAPPING = {
    "version": VERSION,
    "symbol": "BTCUSD",
    "native_timeframe": "5m",
    "detector_kinds": ["resistance_breakout", "breakout_retest"],
    "strategy": "breakout-retest-v1",
    "reference": "cost-breakout-v1",
    "rule_version": "reviewed-lab-rules-v4",
    "holding_horizon": "medium",
    "limits": [
        "Saved native pivot/volume recognition motivates a distinct fixed bank hypothesis.",
        "Bank execution inputs are current closed minutes aggregated by the existing v4 owner.",
        "Native scanner candles are not substituted for execution inputs.",
        "Local contiguous recognition window does not establish complete year coverage or edge.",
        "Preparation is not submission, funding, promotion, or model authority.",
        "An original waiting preparation never automatically becomes supported.",
    ],
}


class PatternFindingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    daily_id: str = Field(pattern=r"^daily-[a-f0-9]{24}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]{4,24}$")
    timeframe: Literal["5m", "15m", "30m", "1h", "4h"]
    event_kind: Literal["patterns", "alerts"]
    event_seq: int = Field(ge=1, le=9223372036854775807)


class PatternComparisonCommand(PatternFindingSelection):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    expected_finding_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PatternComparisons:
    def __init__(self, scanner: PatternScanner, controller: AutonomousLab | None = None):
        self.scanner = scanner
        self.controller = controller
        self.registry = scanner.registry
        if controller is not None and controller.registry is not self.registry:
            raise ValueError("Comparison preparation requires the existing shared registry")
        with self.registry.lock:
            self.registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS pattern_comparison_requests(
                  request_id TEXT PRIMARY KEY, intent_sha256 TEXT NOT NULL,
                  bundle_sha256 TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS pattern_comparison_frozen
                  BEFORE UPDATE ON pattern_comparison_requests
                  BEGIN SELECT RAISE(ABORT,'Comparison preparation is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS pattern_comparison_retained
                  BEFORE DELETE ON pattern_comparison_requests
                  BEGIN SELECT RAISE(ABORT,'Comparison preparation is retained'); END;
                CREATE TABLE IF NOT EXISTS lab_bundles(
                  sha256 TEXT PRIMARY KEY, at REAL NOT NULL, body TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS lab_bundle_immutable BEFORE UPDATE ON lab_bundles
                  BEGIN SELECT RAISE(ABORT,'Issued proposer evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS lab_bundle_retained BEFORE DELETE ON lab_bundles
                  BEGIN SELECT RAISE(ABORT,'Issued proposer evidence is retained'); END;
            """)

    @staticmethod
    def _method_sources() -> dict[str, str]:
        return {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("redesign_strategy.py", "autonomous_spec.py", "rule_components.py")
        }

    def _permitted(self, windows: list[tuple[float, float]]) -> None:
        # Called under the registry transaction at publication, just as Lab bundles
        # serialize disclosure with holdout creation. Unknown origins fail closed.
        r = self.registry
        prospective = r.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='prospective_plans'"
        ).fetchone()
        for start, end in windows:
            if not all(math.isfinite(v) for v in (start, end)) or start > end:
                raise ValueError("Invalid disclosed input interval")
            overlap = r.db.execute(
                "SELECT 1 FROM evidence_windows WHERE start<=? AND end>=? "
                "AND origin NOT IN (?,?,?,?) LIMIT 1",
                (end, start, *TRAINING_ORIGINS),
            ).fetchone()
            if overlap:
                raise ValueError("Protected evaluation overlaps these research inputs")
            if (
                prospective
                and r.db.execute(
                    "SELECT 1 FROM prospective_plans WHERE start<=? AND end>=? LIMIT 1",
                    (end, start),
                ).fetchone()
            ):
                raise ValueError("Protected prospective interval overlaps these research inputs")

    def _original(self, selection: PatternFindingSelection) -> dict[str, Any]:
        with self.registry.lock:
            day = self.scanner.daily_snapshot(selection.daily_id)
            pick = next((p for p in day["picks"] if p["symbol"] == selection.symbol), None)
            if not pick or pick["basis"] != "recognized_setup":
                raise ValueError("Selected daily pick has no recognized original finding")
            evidence = next(
                (
                    e
                    for e in pick["evidence"]
                    if e["kind"] == selection.event_kind
                    and e["seq"] == selection.event_seq
                    and e["timeframe"] == selection.timeframe
                ),
                None,
            )
            if evidence is None:
                raise ValueError("Selected event is not in this immutable daily pick")
            campaign = day["campaign_id"]
            saved = self.registry.db.execute(
                "SELECT body FROM pattern_events WHERE seq=? AND campaign=? "
                "AND symbol=? AND timeframe=? AND kind=?",
                (
                    selection.event_seq,
                    campaign,
                    selection.symbol,
                    selection.timeframe,
                    selection.event_kind,
                ),
            ).fetchone()
            if not saved or json.loads(saved[0]) != evidence["body"]:
                raise ValueError("Daily finding differs from its same-scope original event")
            event = evidence["body"]
            if (
                selection.symbol != "BTCUSD"
                or selection.timeframe != "5m"
                or (event["kind"] not in MAPPING["detector_kinds"])
            ):
                raise ValueError("No reviewed comparison mapping for this original finding")
            if event.get("volume_confirmed") is not True or (
                event.get("symbol") != selection.symbol
                or event.get("timeframe") != selection.timeframe
                or event.get("financial_authority") is not False
            ):
                raise ValueError("Original finding has unavailable or contradictory identity")
            level = self.registry.db.execute(
                "SELECT body FROM pattern_levels WHERE campaign=? AND symbol=? "
                "AND timeframe=? AND identity=?",
                (campaign, selection.symbol, selection.timeframe, event["level_id"]),
            ).fetchone()
            row = self.registry.db.execute(
                "SELECT body FROM pattern_campaigns WHERE id=?", (campaign,)
            ).fetchone()
            if not level or not row:
                raise ValueError("Original level or campaign is unavailable")
            level = json.loads(level[0])
            frozen = json.loads(row[0])
            coverage = next(c for c in pick["coverage"] if c["timeframe"] == "5m")
            if (
                level["kind"] != "resistance"
                or level["price"] != event["level_price"]
                or level["first_usable_ms"] > event["bar_open_ms"]
                or coverage.get("progress_sha256") is None
                or event["bar_close_ms"] > coverage["latest_close_ms"]
                or event["observed_at"] > pick["captured_at"]
            ):
                raise ValueError("Finding was not known within its captured native cutoff")
            return {
                "selection": selection.model_dump(),
                "campaign_id": campaign,
                "daily_sha256": digest(day),
                "daily_as_of": day["as_of"],
                "captured_at": pick["captured_at"],
                "coverage": pick["coverage"],
                "original_event": event,
                "original_level": level,
                "implementation_sha256": day["implementation_sha256"],
                "storage_plan_sha256": frozen["storage_plan_sha256"],
            }

    def _native(self, finding: dict[str, Any]) -> dict[str, Any]:
        # Reproduce the exact scanner arithmetic, including nonterminating ratios.
        with localcontext(Context(prec=38, rounding=ROUND_HALF_EVEN)):
            return self._native_precise(finding)

    def _native_precise(self, finding: dict[str, Any]) -> dict[str, Any]:
        plan = self.scanner.plan
        if plan is None or digest(plan.model_dump()) != finding["storage_plan_sha256"]:
            raise ValueError("Original native archive storage identity is unavailable")
        event, level = finding["original_event"], finding["original_level"]
        references = list(dict.fromkeys(event["source_references"] + level["source_references"]))
        if not 1 <= len(references) <= MAX_REFERENCES:
            raise ValueError("Original native proof exceeds its bounded reference count")
        rows: dict[int, list[Any]] = {}
        pages: dict[int, dict[str, Any]] = {}
        windows = []
        for reference in references:
            packet = reopen_evidence(plan, reference)
            if (
                packet.get("kind") != "native_year_pattern_inputs"
                or packet.get("version") != SCANNER_VERSION
                or packet.get("campaign_id") != finding["campaign_id"]
                or packet.get("symbol") != "BTCUSD"
                or packet.get("timeframe") != "5m"
                or not isinstance(packet.get("rows"), list)
                or not 1 <= len(packet["rows"]) <= 500
            ):
                raise ValueError("Native archive packet has a different scope or bound")
            start = packet["requested_start_ms"]
            if start not in pages:
                with self.registry.lock:
                    saved = self.registry.db.execute(
                        "SELECT body FROM pattern_pages WHERE campaign=? AND symbol='BTCUSD' "
                        "AND timeframe='5m' AND start_ms=?",
                        (finding["campaign_id"], start),
                    ).fetchone()
                if not saved:
                    raise ValueError("Native archive has no immutable page manifest")
                pages[start] = json.loads(saved[0])
            page = pages[start]
            if (
                reference not in page["references"]
                or packet["requested_end_ms"] != page["requested_end_ms"]
                or packet["offset"] != page["references"].index(reference) * 500
                or packet["at"] != page["observed_at"]
            ):
                raise ValueError("Native packet differs from its exact page manifest")
            windows.append((start / 1000, (packet["requested_end_ms"] + 1) / 1000))
            for raw in packet["rows"]:
                bar = native_bar(raw, 300000)
                if not start <= bar.open_ms <= bar.close_ms <= packet["requested_end_ms"]:
                    raise ValueError("Native row is outside the immutable requested page")
                if bar.open_ms in rows and rows[bar.open_ms] != raw:
                    raise ValueError("Native duplicate candle identities disagree")
                rows[bar.open_ms] = raw
        # Read every referenced page's remaining bounded chunks to verify the
        # original page hash; don't present a prefix as full page verification.
        for start, page in pages.items():
            complete = []
            if not 1 <= len(page["references"]) <= 2:
                raise ValueError("Original native page exceeds two bounded chunks")
            for index, reference in enumerate(page["references"]):
                packet = reopen_evidence(plan, reference)
                if (
                    packet.get("kind") != "native_year_pattern_inputs"
                    or packet.get("version") != SCANNER_VERSION
                    or packet.get("campaign_id") != finding["campaign_id"]
                    or packet.get("symbol") != "BTCUSD"
                    or packet.get("timeframe") != "5m"
                    or packet.get("requested_start_ms") != start
                    or packet.get("requested_end_ms") != page["requested_end_ms"]
                    or packet.get("offset") != index * 500
                    or packet.get("at") != page["observed_at"]
                    or not isinstance(packet.get("rows"), list)
                    or not 1 <= len(packet["rows"]) <= 500
                ):
                    raise ValueError("Native page chunk identity or size differs")
                complete.extend(packet["rows"])
            if len(complete) != page["count"] or digest(complete) != page["rows_sha256"]:
                raise ValueError("Native page count or original source hash differs")
        window = [rows.get(event["bar_open_ms"] - offset * 300000) for offset in range(20, -1, -1)]
        pivot = [rows.get(level["pivot_open_ms"] + offset * 300000) for offset in range(-2, 3)]
        if any(r is None for r in window + pivot):
            raise ValueError("Relevant causal recognition window has missing native candles")
        if digest(window) != event["input_window_sha256"] or (
            digest(pivot) != level["input_window_sha256"]
        ):
            raise ValueError("Original event or pivot window source hash differs")
        bars = [native_bar(raw, 300000) for raw in window if raw is not None]
        pivots = [native_bar(raw, 300000) for raw in pivot if raw is not None]
        price = Decimal(level["price"])
        ratio = _volume_ratio(bars[-1], deque(b.volume for b in bars[:-1]))
        if (
            pivots[2].high != price
            or any(price <= b.high for b in pivots[:2] + pivots[3:])
            or pivots[-1].close_ms != level["confirmed_at_ms"]
            or level["first_usable_ms"] != pivots[-1].close_ms + 1
            or Decimal(level["low"]) != price * (1 - ZONE_HALF_WIDTH)
            or Decimal(level["high"]) != price * (1 + ZONE_HALF_WIDTH)
            or ratio is None
            or ratio < Decimal("1.5")
            or str(ratio) != event["volume_ratio"]
            or bars[-1].close_ms != event["bar_close_ms"]
        ):
            raise ValueError("Native pivot, confirmation, or volume proof contradicts finding")
        zone = _Zone(
            level["id"],
            "resistance",
            price,
            Decimal(level["low"]),
            Decimal(level["high"]),
            level["confirmed_at_ms"],
            level["pivot_open_ms"],
        )
        recognized = []
        for index in range(1, len(bars)):
            if bars[index].open_ms >= level["first_usable_ms"]:
                recognized = _visit(
                    zone, bars[index], bars[index - 1], ratio if index == 20 else None, 300000
                )
        if not any(
            all(event.get(k) == value for k, value in found.items()) for found in recognized
        ):
            raise ValueError(
                "Exact native detector predicate does not reproduce the original event"
            )
        return {
            "archive_verified": True,
            "references": references,
            "pages": [{"start_ms": start, **page} for start, page in pages.items()],
            "recognition_rows": 21,
            "pivot_rows": 5,
            "contiguous_relevant_window": True,
            "recognition_start_ms": bars[0].open_ms,
            "recognition_end_ms": bars[-1].close_ms,
            "input_window_sha256": digest(window),
            "pivot_sha256": digest(pivot),
            "disclosed_intervals": sorted(set(windows)),
            "coverage_claim": "Only exact retained pages and local recognition window verified",
        }

    def describe(self, selection: PatternFindingSelection) -> dict[str, Any]:
        finding = self._original(selection)
        # Internal verification does not return raw archived page payloads.
        finding["native_proof"] = self._native(finding)
        with self.registry.lock:
            self._permitted(finding["native_proof"]["disclosed_intervals"])
        return {
            "version": VERSION,
            "finding_sha256": digest(finding),
            "finding": finding,
            "mapping": {**MAPPING, "source_sha256": self._method_sources()},
            "financial_authority": False,
        }

    def candidate(self, now: float) -> PatternFindingSelection | None:
        """One bounded original native finding from the latest published daily capture."""
        if not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid candidate observation time")
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT body FROM pattern_daily_days ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        day = json.loads(row["body"])
        if day["generated_at"] > now:
            return None
        choices = [
            evidence
            for pick in day["picks"]
            if pick["symbol"] == "BTCUSD" and pick["basis"] == "recognized_setup"
            for evidence in pick["evidence"]
            if evidence["timeframe"] == "5m"
            and evidence["kind"] in {"patterns", "alerts"}
            and evidence["body"]["kind"] in MAPPING["detector_kinds"]
            and evidence["body"].get("volume_confirmed") is True
        ]
        if not choices:
            return None
        chosen = max(choices, key=lambda item: item["seq"])
        return PatternFindingSelection(
            daily_id=day["id"],
            symbol="BTCUSD",
            timeframe="5m",
            event_kind=chosen["kind"],
            event_seq=chosen["seq"],
        )

    def current_observation(
        self, request_id: str, now: float, *, admission: Callable[[], Any] | None = None
    ) -> dict[str, Any]:
        """Fresh matched inputs retained by the same owner; original preparation stays frozen."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", request_id):
            raise ValueError("Invalid current comparison observation identity")
        if not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid current comparison observation time")
        proposal, evaluation, windows = (
            self._evaluation(request_id, now, admission=admission)
            if admission is not None
            else self._evaluation(request_id, now)
        )
        if evaluation["status"] == "supported_exploratory_configuration":
            with self.registry.transaction():
                if admission is not None:
                    admission()
                self._permitted(windows)
                for index, (start, end) in enumerate(windows):
                    self.registry.db.execute(
                        "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,?)",
                        (
                            f"pattern-role-input:{request_id}:{index}",
                            start,
                            end,
                            "Pattern comparison preparation disclosure",
                        ),
                    )
        return {"proposal_without_bundle_digest": proposal, "evaluation": evaluation}

    def execution_inputs(self, proof: dict[str, Any], request_id: str) -> list[dict[str, Any]]:
        """Reopen the exact bounded current-input archive; metadata alone is insufficient."""
        plan = self.scanner.plan
        references = proof.get("references")
        if plan is None or not isinstance(references, list) or not 1 <= len(references) <= 2:
            raise ValueError("Saved execution input archive identity is unavailable")
        rows: list[dict[str, Any]] = []
        for reference in references:
            packet = reopen_evidence(plan, reference)
            chunk = packet.get("rows")
            if (
                packet.get("kind") != "pattern_comparison_execution_inputs"
                or packet.get("version") != VERSION
                or packet.get("request_id") != request_id
                or packet.get("offset") != len(rows)
                or packet.get("inputs_sha256") != proof["sha256"]
                or not isinstance(chunk, list)
                or not 1 <= len(chunk) <= 500
            ):
                raise ValueError("Saved execution input chunk differs from its original identity")
            rows.extend(chunk)
        if (
            not 305 <= len(rows) <= 600
            or len(rows) != proof["count"]
            or digest(rows) != proof["sha256"]
            or rows[0]["open_ms"] != proof["start_ms"]
            or rows[-1]["close_ms"] != proof["end_ms"]
        ):
            raise ValueError("Saved matched execution input proof differs")
        return rows

    def get(self, request_id: str) -> dict[str, Any] | None:
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", request_id):
            raise ValueError("Invalid comparison request identity")
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT q.*,b.body FROM pattern_comparison_requests q "
                "LEFT JOIN lab_bundles b ON b.sha256=q.bundle_sha256 WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return self._receipt(row)

    @staticmethod
    def _receipt(row: Any) -> dict[str, Any]:
        if row["body"] is None:
            raise OSError("Saved issued comparison bundle is unavailable; no new preparation")
        if len(row["body"].encode()) > 65536:
            raise ValueError("Saved preparation exceeds its original issued bundle bound")
        body: dict[str, Any] = json.loads(row["body"])
        if fingerprint(body) != row["bundle_sha256"] or (
            body["request_id"] != row["request_id"]
            or body["intent_sha256"] != row["intent_sha256"]
            or digest(body["finding"]) != body["finding_sha256"]
        ):
            raise ValueError("Saved preparation identity or immutable bundle hash differs")
        body["issued_bundle_sha256"] = row["bundle_sha256"]
        body["proposal"] = body.pop("proposal_without_bundle_digest")
        if body["proposal"] is not None:
            body["proposal"]["evidence_bundle_sha256"] = row["bundle_sha256"]
            LabProposal.model_validate(body["proposal"])
        for control in body["evaluation"].get("controls", {}).values():
            if isinstance(control, dict) and "proposal_without_bundle_digest" in control:
                control["proposal"] = control.pop("proposal_without_bundle_digest")
                control["proposal"]["evidence_bundle_sha256"] = row["bundle_sha256"]
                LabProposal.model_validate(control["proposal"])
        return body

    def page(self, before_request_id: str = "") -> dict[str, Any]:
        if before_request_id and not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", before_request_id):
            raise ValueError("Invalid saved comparison page cursor")
        with self.registry.lock:
            rows = self.registry.db.execute(
                "SELECT q.*,b.body FROM pattern_comparison_requests q LEFT JOIN "
                "lab_bundles b ON b.sha256=q.bundle_sha256 "
                "WHERE (?='' OR q.request_id<?) ORDER BY q.request_id DESC LIMIT 21",
                (before_request_id, before_request_id),
            ).fetchall()
        items = []
        for row in rows[:20]:
            original = self._receipt(row)
            items.append(
                {
                    **{
                        k: original[k]
                        for k in (
                            "request_id",
                            "finding_sha256",
                            "status",
                            "prepared_at",
                            "issued_bundle_sha256",
                        )
                    },
                    "selection": original["finding"]["selection"],
                }
            )
        return {
            "version": VERSION,
            "items": items,
            "next_before": items[-1]["request_id"] if len(rows) > 20 else None,
            "order": "Stable descending request identity, not preparation chronology",
            "financial_authority": False,
        }

    def _evaluation(
        self, request_id: str, now: float, *, admission: Callable[[], Any] | None = None
    ) -> tuple[Any, Any, list[tuple[float, float]]]:
        c = self.controller
        if admission is not None:
            admission()
        if c is None:
            return None, {"status": "waiting", "reason": "Current Lab owner unavailable"}, []
        lab = c.paper.state.get("autonomous_lab")
        if not lab:
            return None, {"status": "waiting", "reason": "No declared current Lab policy"}, []
        policy = LabPolicy.model_validate(lab["policy"])
        strategy = RuleSpec(
            version="reviewed-lab-rules-v4", family="breakout-retest-v1", holding_horizon="medium"
        )
        reference = RuleSpec(
            version="reviewed-lab-rules-v4", family="cost-breakout-v1", holding_horizon="medium"
        )
        proposal = LabProposal(
            request_id=request_id,
            policy_id=policy.request_id,
            source="deterministic",
            kind="independent",
            strategy=strategy,
            reference=reference,
            mechanism=(
                "Saved native resistance recognition motivates the fixed retest bank hypothesis"
            ),
            question=(
                "Does fixed breakout-retest improve future after-cost outcomes over cost-breakout?"
            ),
            evidence_bundle_sha256="0" * 64,
        )
        baseline_proposal = LabProposal.model_validate(
            {
                **proposal.model_dump(),
                "strategy": reference.model_dump(),
                "reference": strategy.model_dump(),
            }
        )
        controls: dict[str, Any] = {
            "candidate": contract(proposal, policy),
            "reference": contract(baseline_proposal, policy),
            "policy_sha256": fingerprint(policy.model_dump()),
        }
        for label in ("candidate", "reference"):
            item = controls[label]
            template = item.pop("proposal")
            template.pop("evidence_bundle_sha256")
            item["proposal_without_bundle_digest"] = template
        proposal_body = proposal.model_dump(exclude={"evidence_bundle_sha256"})
        if not self.scanner._allowed() or not c.can_research():
            return (
                proposal_body,
                {"status": "waiting", "reason": "Research protection wait"},
                [],
            )
        roster = self.scanner.roster(now, full=True)
        if roster["available"] is not True or not any(
            row["symbol"] == "BTCUSD" and row["eligible"] is True for row in roster["rows"]
        ):
            return (
                proposal_body,
                {"status": "waiting", "reason": "Current BTC eligibility unavailable"},
                [],
            )
        if not c.inbox.has_capacity() or c.inbox.used(fingerprint(strategy.model_dump())):
            return (
                proposal_body,
                {"status": "waiting", "reason": "Existing inbox capacity or used-rule gate"},
                [],
            )
        try:
            candidate = c.evaluate(proposal, now)
            baseline = c.evaluate(baseline_proposal, now)
        except (InputWait, ValueError) as exc:
            return proposal_body, {"status": "waiting", "reason": str(exc)}, []
        inputs = candidate.pop("inputs")
        baseline_inputs = baseline.pop("inputs")
        if inputs != baseline_inputs or not 305 <= len(inputs) <= 600:
            raise ValueError("Matched current execution inputs differ or exceed their bound")
        windows = [(inputs[0]["open_ms"] / 1000, (inputs[-1]["close_ms"] + 1) / 1000)]
        with self.registry.lock:
            self._permitted(windows)
        owner, plan = self.scanner.storage_owner, self.scanner.plan
        if owner is None or plan is None:
            raise ValueError("Existing shared archive owner is unavailable")
        packets = [
            {
                "kind": "pattern_comparison_execution_inputs",
                "version": VERSION,
                "at": now,
                "request_id": request_id,
                "offset": offset,
                "inputs_sha256": digest(inputs),
                "rows": inputs[offset : offset + 500],
            }
            for offset in range(0, len(inputs), 500)
        ]
        with owner(plan) as storage:
            if admission is not None:
                admission()
            refs = storage.append(packets, now)
            for packet, ref in zip(packets, refs, strict=True):
                if reopen_evidence(plan, ref) != packet:
                    raise ValueError("Retained current execution input proof differs")
                storage.protect(
                    ref,
                    now + plan.temporary_retention_seconds,
                    "Pattern comparison execution inputs",
                )
        proof = {
            "count": len(inputs),
            "sha256": digest(inputs),
            "references": refs,
            "cutoff": now,
            "start_ms": inputs[0]["open_ms"],
            "end_ms": inputs[-1]["close_ms"],
            "archive_verified": True,
            "owner": "Existing v4 current closed-minute execution inputs",
        }
        return (
            proposal_body,
            {
                "status": "supported_exploratory_configuration",
                "candidate": candidate,
                "reference": baseline,
                "matched_inputs": proof,
                "controls": controls,
            },
            windows,
        )

    def prepare(
        self,
        command: PatternComparisonCommand,
        now: float | None = None,
        *,
        admission: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        intent = digest(command.model_dump())
        # Recovery happens first, including after source/eligibility/policy drift.
        old = self.get(command.request_id)
        if old is not None:
            if old["intent_sha256"] != intent:
                raise ValueError("Comparison request identity cannot be rewritten")
            return old
        with self.registry.pattern_comparison_lock:
            return self._prepare_new(command, now, intent, admission)

    def _prepare_new(
        self,
        command: PatternComparisonCommand,
        now: float | None,
        intent: str,
        admission: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        old = self.get(command.request_id)
        if old is not None:
            if old["intent_sha256"] != intent:
                raise ValueError("Comparison request identity cannot be rewritten")
            return old
        if admission is not None:
            admission()
        now = time.time() if now is None else now
        if not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid preparation observation time")
        selection = PatternFindingSelection.model_validate(
            command.model_dump(exclude={"request_id", "expected_finding_sha256"})
        )
        described = self.describe(selection)
        if described["finding_sha256"] != command.expected_finding_sha256:
            raise ValueError("Original finding identity differs from the reviewed selection")
        with self.registry.lock:
            if (
                self.registry.db.execute(
                    "SELECT count(*) FROM pattern_comparison_requests"
                ).fetchone()[0]
                >= MAX_REQUESTS
            ):
                raise ValueError("Retained comparison preparation capacity reached")
            self.scanner._admission()
        c = self.controller
        policy_sha = digest(c.paper.state.get("autonomous_lab", {}).get("policy")) if c else None
        # Borrowing/appending/reopening the recorder never holds the registry lock.
        proposal, evaluation, execution_windows = (
            self._evaluation(command.request_id, now, admission=admission)
            if admission is not None
            else self._evaluation(command.request_id, now)
        )
        body = {
            "version": VERSION,
            "request_id": command.request_id,
            "intent_sha256": intent,
            "finding_sha256": described["finding_sha256"],
            "finding": described["finding"],
            "mapping": described["mapping"],
            "prepared_at": now,
            "current_policy_sha256": policy_sha,
            "status": "supported"
            if evaluation["status"] == "supported_exploratory_configuration"
            else "waiting",
            "reason": evaluation.get("reason"),
            "proposal_without_bundle_digest": proposal,
            "evaluation": evaluation,
            "financial_authority": False,
            "submitted": False,
        }
        encoded = json.dumps(body, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Comparison issued bundle exceeds existing 64KiB bound")
        bundle_sha = fingerprint(body)
        windows = described["finding"]["native_proof"]["disclosed_intervals"] + execution_windows
        with self.registry.transaction():
            if admission is not None:
                admission()
            if self._original(selection) != {
                k: v for k, v in described["finding"].items() if k != "native_proof"
            }:
                raise ValueError("Original finding changed before preparation publication")
            if self._method_sources() != described["mapping"]["source_sha256"] or (
                c and digest(c.paper.state.get("autonomous_lab", {}).get("policy")) != policy_sha
            ):
                raise ValueError("Current comparison source or policy changed during preparation")
            self.scanner._admission()
            self._permitted(windows)
            if admission is not None:
                admission()
            for index, (start, end) in enumerate(windows):
                self.registry.db.execute(
                    "INSERT INTO evidence_windows VALUES(?,?,?,?)",
                    (
                        f"pattern-comparison:{command.request_id}:{index}",
                        start,
                        end,
                        "Pattern comparison preparation disclosure",
                    ),
                )
            self.registry.db.execute(
                "INSERT INTO lab_bundles VALUES(?,?,?)", (bundle_sha, now, encoded)
            )
            self.registry.db.execute(
                "INSERT INTO pattern_comparison_requests VALUES(?,?,?)",
                (command.request_id, intent, bundle_sha),
            )
        result = self.get(command.request_id)
        assert result is not None
        if len(canonical(result).encode()) > 131072:
            raise ValueError("Comparison receipt exceeds its declared response bound")
        return result
