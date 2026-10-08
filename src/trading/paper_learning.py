"""Protected whole-account comparisons and explicit reversible paper incumbent roles."""

import copy
import math
import statistics
from decimal import Decimal as D
from typing import TYPE_CHECKING, Any

from trading.account_purpose import RESEARCH_EXCLUSION, require_research_account, research_account
from trading.experiment_registry import fingerprint
from trading.numerical_candidates import validate_artifact

if TYPE_CHECKING:
    from trading.paper_engine import PaperEngine

POLICY: dict[str, Any] = {
    "version": "prospective-paper-role-v1",
    "minimum_daily_blocks": 28,
    "block_seconds": 86400,
    "maximum_daily_drawdown": "0.10",
    "minimum_positive_fraction": 0.75,
    "largest_day_gain_share_max": 0.5,
    "hac_lag_days": 7,
    "selection_margin_standard_errors": 4,
    "additional_slippage_return": 0.0004,
    "report_expiry_seconds": 86400,
    "interpretation": "Conservative paper-role policy; no independent significance/live claim",
    "changes": {
        "strategy": "Frozen account role only",
        "research_memory": "Retained reports",
        "code": "Separate source review",
        "prompt": "No prompt changes",
        "AI_training": "None; numerical weights remain frozen",
    },
}


def config(a: dict[str, Any]) -> dict[str, Any]:
    return {
        k: a.get(k)
        for k in (
            "version",
            "execution_profile",
            "risk_policy",
            "starting_capital",
            "funding",
            "operating_daily_usd",
            "economics_settings_version",
            "symbols",
            "benchmark_symbols",
            *(("purpose",) if "purpose" in a else ()),
        )
    }


def drift(a: dict[str, Any]) -> list[str]:
    reasons = []
    if not research_account(a):
        reasons.append(RESEARCH_EXCLUSION)
    artifact = a.get("numerical_artifact")
    if artifact:
        try:
            validate_artifact(artifact)
            if a["version"] != "numeric-" + artifact["sha256"][:24]:
                reasons.append("Frozen account version differs from its model")
        except (ValueError, KeyError, TypeError):
            reasons.append("Frozen numerical artifact is invalid")
    if a.get("economics_settings_version", 0):
        reasons.append("Cost/settings changed after freeze; a new forward comparison is required")
    if a.get("fault") or a.get("failure_pending") or a.get("drawdown_pause"):
        reasons.append("Processing failure or latched loss stop")
    if a.get("valuation_fresh") is not True:
        reasons.append("Data or executable holding marks unavailable")
    return reasons


def matched_control(engine: "PaperEngine", candidate: str) -> dict[str, Any]:
    from trading.paper_engine import account

    a = engine.state["accounts"][candidate]
    require_research_account(a, candidate)
    if not a.get("numerical_artifact"):
        raise ValueError("Select a frozen exploratory numerical account")
    controls = engine.state.setdefault("forward_controls", {})
    if candidate in controls:
        require_research_account(engine.state["accounts"][controls[candidate]], controls[candidate])
        return {"status": "already_applied", "account": controls[candidate]}
    if len(set(engine.state["accounts"]) | {"universe-wide-v1", "universe-control-v1"}) >= 20:
        raise ValueError("Twenty-account limit reached; cannot discard history to fund a control")
    incumbent = engine.state["accounts"][
        engine.state.get("learning", {}).get("incumbent", "primary")
    ]
    require_research_account(
        incumbent, engine.state.get("learning", {}).get("incumbent", "primary")
    )
    if incumbent.get("numerical_artifact"):
        validate_artifact(incumbent["numerical_artifact"])
    name = "control-" + a["numerical_artifact"]["sha256"][:24]
    control = account(
        incumbent["version"], engine.now, a["starting_capital"], a["execution_profile"]
    )
    control.update(
        label="Matched frozen incumbent · " + a["label"],
        campaign_id="forward-control",
        symbols=copy.deepcopy(a["symbols"]),
        benchmark_symbols=copy.deepcopy(a["symbols"]),
        operating_daily_usd=a.get("operating_daily_usd"),
        admitted_at=engine.now,
        entries_paused=False,
        control_version=0,
        matched_candidate=candidate,
        frozen_incumbent_account=engine.state.get("learning", {}).get("incumbent", "primary"),
    )
    engine.state["accounts"][name] = control
    if incumbent.get("numerical_artifact"):
        control["numerical_artifact"] = copy.deepcopy(incumbent["numerical_artifact"])
    controls[candidate] = name
    cash = D(control["starting_capital"])
    engine.emit(
        "matched_control_funded",
        name,
        {
            "candidate": candidate,
            "frozen_incumbent_version": incumbent["version"],
            "amount": str(cash),
            "purpose": "Separate hypothetical control; never transfers candidate or primary money",
        },
        [engine.line("USD", "cash", cash), engine.line("USD", "fake_funding", -cash)],
    )
    return {"status": "created", "account": name}


def hac_error(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    n, mean = len(values), statistics.mean(values)
    centered = [v - mean for v in values]
    variance = sum(v * v for v in centered) / n
    for lag in range(1, min(7, n - 1) + 1):
        covariance = sum(centered[i] * centered[i - lag] for i in range(lag, n)) / n
        variance += 2 * (1 - lag / 8) * covariance
    return math.sqrt(max(0, variance) / n)


def comparison(
    state: dict[str, Any],
    candidate: str,
    windows: list[dict[str, Any]],
    now: float,
    protected_through: float,
    *,
    truncated: bool = False,
) -> dict[str, Any]:
    a = state["accounts"][candidate]
    require_research_account(a, candidate)
    control = state.get("forward_controls", {}).get(candidate)
    if control in state["accounts"]:
        require_research_account(state["accounts"][control], control)
    reasons = drift(a)
    if not a.get("numerical_artifact"):
        reasons.append("Only explicitly frozen numerical candidates enter this forward policy")
    if not control:
        reasons.append("A matched frozen incumbent control has not been funded")
    elif drift(state["accounts"][control]):
        reasons.append("Matched control has data, settings or risk drift")
    if state.get("evidence_kind") != "observed_public_feed":
        reasons.append("Synthetic or unclassified input cannot qualify prospective market evidence")
    after = max(
        a.get("admitted_at", now),
        protected_through,
        state["accounts"].get(control or "", {}).get("admitted_at", now),
    )
    selected, discarded = [], []
    for window in sorted(windows, key=lambda w: w["start"]):
        rows = window["scores"]
        c, b = rows.get(candidate), rows.get(control)
        issue = None
        if window["start"] <= after:
            issue = "Earlier or inspected window; descriptive history only"
        elif not c or not b or not c["eligible"] or not b["eligible"]:
            issue = "Missing, incomplete or ineligible whole-account pair"
        elif c["cohort"] != b["cohort"]:
            issue = "Capital, funding, fees, operating allocation or risk are unmatched"
        elif (
            c.get("strategy_version") != a["version"]
            or b.get("strategy_version") != state["accounts"][control]["version"]
        ):
            issue = "Window does not belong to these frozen versions"
        elif c.get("benchmark_symbols") != a.get("symbols"):
            issue = "Simple-exposure control does not match the declared instrument universe"
        elif D(c["max_drawdown"]) > D(POLICY["maximum_daily_drawdown"]):
            issue = "Drawdown exceeds the predeclared envelope"
        if issue:
            discarded.append({"start": window["start"], "reason": issue})
            continue
        selected.append(window)
    blocks: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for window in selected:
        if pending and abs(window["start"] - pending[-1]["end"]) > 1:
            pending = []
        pending.append(window)
        if pending[-1]["end"] - pending[0]["start"] < 86400:
            continue
        gains, relative, cash_relative, exposure_relative, stress = [], [], [], [], []
        for w in pending:
            c, b = w["scores"][candidate], w["scores"][control]
            gain = float(c["total_return"])
            gains.append(gain)
            relative.append(float(b["total_return"]))
            cash_relative.append(float(c["cash_total_return"]))
            exposure_relative.append(float(c["exposure_total_return"]))
            extra = max(0, float(c["execution_cost"])) / float(c["start_equity"]) + 0.0004
            stress.append(gain - extra)

        def compound(rows: list[float]) -> float:
            return math.prod(1 + v for v in rows) - 1

        blocks.append(
            {
                "start": pending[0]["start"],
                "end": pending[-1]["end"],
                "return": compound(gains),
                "incumbent_excess": compound(gains) - compound(relative),
                "cash_excess": compound(gains) - compound(cash_relative),
                "exposure_excess": compound(gains) - compound(exposure_relative),
                "doubled_cost_proxy": compound(stress),
            }
        )
        pending = []
    if truncated:
        reasons.append(
            "More than 512 windows exist; this bounded report cannot certify full history"
        )
    if len(blocks) < 28:
        reasons.append("Need 28 subsequent complete daily blocks, without a trade-count quota")
    values = [b["incumbent_excess"] for b in blocks]
    mean = statistics.mean(values) if values else None
    error = hac_error(values)
    if blocks:
        for field in ("incumbent_excess", "cash_excess", "exposure_excess", "doubled_cost_proxy"):
            if statistics.mean(b[field] for b in blocks) <= 0:
                reasons.append(
                    f"After-cost whole-account {field.replace('_', ' ')} is not positive"
                )
        if sum(v > 0 for v in values) / len(values) < 0.75:
            reasons.append("Advantage is not stable across daily blocks")
        positive = sum(max(0, v) for v in values)
        if positive and max(values) / positive > 0.5:
            reasons.append("One exceptional day dominates positive advantage")
        if mean is None or error is None or mean <= 4 * error:
            reasons.append(
                "Dependence/selection margin is insufficient for the frozen paper policy"
            )
    return {
        "policy": copy.deepcopy(POLICY),
        "candidate": candidate,
        "control": control,
        "compared_incumbent": state["accounts"]
        .get(control or "", {})
        .get("frozen_incumbent_account"),
        "candidate_configuration": config(a),
        "configuration_sha256": fingerprint(config(a)),
        "artifact_sha256": a.get("numerical_artifact", {}).get("sha256"),
        "created_at": now,
        "evidence_kind": state.get("evidence_kind", "unclassified"),
        "protected_through_before_report": protected_through,
        "daily_blocks": blocks,
        "matched_windows": len(selected),
        "discarded_windows": discarded,
        "mean_daily_incumbent_excess": mean,
        "hac_descriptive_error": error,
        "decision": "no_promotion" if reasons else "eligible_for_paper_designation",
        "reasons": list(dict.fromkeys(reasons)),
        "attribution": {
            "symbols": a.get("symbols"),
            "exposure": "Owned holdings and executable liquidation equity",
            "regime": "Unknown; no retrospective causal story assigned",
            "fees": "Paid fees and execution accrual included; operating costs separate",
        },
        "uncertainty": [
            "Peers and windows are correlated; no independent significance claim",
            "HAC is descriptive; four-error margin is a paper policy, not a p-value",
            "Doubled-cost proxy does not reconstruct different fill opportunities",
            "All candidate families and prior failed searches remain selection history",
        ],
        "approval_required": True,
        "live_execution": False,
    }


def report_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    """Small projection only; the original hashed receipt stays in the journal."""
    if receipt.get("storage") == "immutable-journal-v1":
        return copy.deepcopy(receipt)
    omitted = {
        "daily_blocks",
        "discarded_windows",
        "source_event_ids",
        "candidate_configuration",
        "policy",
    }
    return {
        **{k: copy.deepcopy(v) for k, v in receipt.items() if k not in omitted},
        "storage": "immutable-journal-v1",
        "daily_block_count": len(receipt.get("daily_blocks", [])),
        "discarded_window_count": len(receipt.get("discarded_windows", [])),
        "source_event_count": len(receipt.get("source_event_ids", [])),
    }


def verify_report(receipt: dict[str, Any], request_id: str, sha256: str) -> dict[str, Any]:
    if (
        receipt.get("request_id") != request_id
        or receipt.get("sha256") != sha256
        or fingerprint({k: v for k, v in receipt.items() if k != "sha256"}) != sha256
    ):
        raise ValueError("Immutable report fingerprint mismatch; no authority granted")
    return receipt


def retain_report(engine: "PaperEngine", request_id: str, report: dict[str, Any]) -> dict[str, Any]:
    learning = engine.state.setdefault(
        "learning", {"incumbent": "primary", "role_version": 0, "reports": {}, "promotions": []}
    )
    if request_id in learning["reports"]:
        old = learning["reports"][request_id]
        for event in reversed(engine.events):
            if (
                event["kind"] == "learning_report_retained"
                and event["body"].get("request_id") == request_id
            ):
                return verify_report(event["body"], request_id, old["sha256"])
        if old.get("storage") != "immutable-journal-v1":
            return verify_report(old, request_id, old["sha256"])
        raise ValueError("Load the retained report from its immutable journal for a retry")
    if len(learning["reports"]) >= 32:
        raise ValueError("32 reports retained; export history before a reviewed capacity extension")
    receipt = dict(report, request_id=request_id)
    receipt["sha256"] = fingerprint(receipt)
    learning["reports"][request_id] = report_summary(receipt)
    engine.emit("learning_report_retained", "system", copy.deepcopy(receipt))
    return receipt


def designate(
    engine: "PaperEngine",
    report_id: str,
    sha256: str,
    expected_version: int,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    learning = engine.state["learning"]
    command = {"report_id": report_id, "sha256": sha256, "expected_version": expected_version}
    if learning.get("last_designation") == command:
        require_research_account(
            engine.state["accounts"][learning["incumbent"]], learning["incumbent"]
        )
        return {"status": "already_applied", "incumbent": learning["incumbent"]}
    if learning["role_version"] != expected_version:
        raise ValueError("Paper role changed; refresh before approval")
    report = learning["reports"][report_id]
    if report["sha256"] != sha256 or report["decision"] != "eligible_for_paper_designation":
        raise ValueError("This report does not permit paper designation")
    if receipt is None:
        receipt = next(
            (
                e["body"]
                for e in reversed(engine.events)
                if e["kind"] == "learning_report_retained"
                and e["body"].get("request_id") == report_id
            ),
            None,
        )
        if receipt is None and report.get("storage") != "immutable-journal-v1":
            receipt = report
    if receipt is None:
        raise ValueError("Immutable report unavailable; no paper designation")
    report = verify_report(receipt, report_id, sha256)
    if report["decision"] != "eligible_for_paper_designation":
        raise ValueError("This immutable report does not permit paper designation")
    if report.get("compared_incumbent") != learning["incumbent"]:
        raise ValueError("Report compared a different incumbent role")
    if engine.now - report["created_at"] > 86400:
        raise ValueError("Report expired; a subsequent protected comparison is required")
    a = engine.state["accounts"][report["candidate"]]
    require_research_account(a, report["candidate"])
    if report.get("control") in engine.state["accounts"]:
        require_research_account(engine.state["accounts"][report["control"]], report["control"])
    if fingerprint(config(a)) != report["configuration_sha256"] or drift(a):
        raise ValueError("Frozen configuration, data or risk changed after the report")
    if len(learning["promotions"]) >= 8:
        raise ValueError("Eight designations retained; preserve history before extending")
    record = {
        "at": engine.now,
        "prior_incumbent": learning["incumbent"],
        "incumbent": report["candidate"],
        "report_id": report_id,
        "report_sha256": sha256,
        "approval": "Explicit local operator paper-role approval",
        "rolled_back": False,
    }
    learning["promotions"].append(record)
    learning.update(
        incumbent=report["candidate"], role_version=expected_version + 1, last_designation=command
    )
    engine.emit("paper_role_designated", "system", copy.deepcopy(record))
    return {"status": "applied", "incumbent": learning["incumbent"]}


def rollback(engine: "PaperEngine", expected_version: int) -> dict[str, Any]:
    learning = engine.state["learning"]
    if learning.get("last_rollback") == expected_version:
        require_research_account(
            engine.state["accounts"][learning["incumbent"]], learning["incumbent"]
        )
        return {"status": "already_applied", "incumbent": learning["incumbent"]}
    if learning["role_version"] != expected_version or not learning["promotions"]:
        raise ValueError("Paper role changed or has no designation to roll back")
    record = learning["promotions"][-1]
    if record["rolled_back"]:
        raise ValueError("The latest designation is already rolled back")
    require_research_account(
        engine.state["accounts"][record["prior_incumbent"]], record["prior_incumbent"]
    )
    learning.update(
        incumbent=record["prior_incumbent"],
        role_version=expected_version + 1,
        last_rollback=expected_version,
    )
    record["rolled_back"] = True
    engine.emit(
        "paper_role_rolled_back",
        "system",
        {
            "at": engine.now,
            "incumbent": learning["incumbent"],
            "report_id": record["report_id"],
            "note": "Funding, losses, positions and prior policies all remain retained",
        },
    )
    return {"status": "applied", "incumbent": learning["incumbent"]}


def snapshot(state: dict[str, Any]) -> dict[str, Any]:
    learning = state.get("learning", {})
    return {
        "incumbent": learning.get("incumbent", "primary"),
        "role_version": learning.get("role_version", 0),
        "policy": POLICY,
        "reports": [report_summary(r) for r in list(learning.get("reports", {}).values())[-10:]],
        "promotions": learning.get("promotions", []),
        "accounts": [
            {
                "account": n,
                "label": a.get("label", n),
                "version": a["version"],
                "control": state.get("forward_controls", {}).get(n),
                "drift": drift(a),
                "latest_decisions": a.get("last_decision", {}),
            }
            for n, a in state["accounts"].items()
            if research_account(a, n)
            and a.get("numerical_artifact")
            and a.get("campaign_id") == "forward-research"
        ],
        "unavailable_handoffs": [
            {
                "account": n,
                "label": a.get("label", n),
                "trial_id": a.get("lab_trial"),
                "rule_sha256": fingerprint(a["rule_spec"]),
                "state": "qualification_handoff_not_implemented",
                "reason": "Exploratory result retained; qualification handoff not implemented "
                "for this strategy type. More elapsed time cannot complete this handoff.",
            }
            for n, a in state["accounts"].items()
            if research_account(a, n)
            and a.get("rule_spec")
            and a.get("campaign_id") == "autonomous-lab"
            and a.get("lab_role") == "candidate"
            and state.get("autonomous_lab", {})
            .get("trials", {})
            .get(a.get("lab_trial"), {})
            .get("score")
            is not None
        ],
        "changes": POLICY["changes"],
        "live_execution": False,
    }
