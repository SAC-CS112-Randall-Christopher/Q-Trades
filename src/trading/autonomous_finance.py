"""Continuous lifecycle inside the existing sole financial writer and journal."""

from copy import deepcopy
from decimal import Decimal as D
from typing import TYPE_CHECKING, Any

from trading.autonomous_spec import ORIGINALS, LabPolicy, LabProposal, RuleSpec, contract
from trading.experiment_registry import fingerprint
from trading.paper_economics import benchmark_tick, new_benchmark, sample
from trading.paper_engine import account, fresh_frame

if TYPE_CHECKING:
    from trading.paper_engine import PaperEngine


def slots(state: dict[str, Any]) -> dict[str, int]:
    lab = state.get("autonomous_lab", {})
    accounts = set(state["accounts"]) | set(ORIGINALS)
    reserved = {
        name
        for t in lab.get("trials", {}).values()
        if t["status"] == "reserved"
        for name in (t["candidate"], t["reference"])
    } - accounts
    draining = sum(bool(a.get("lab_retiring")) for a in state["accounts"].values())
    cap = lab.get("policy", {}).get("slots", 20)
    return {
        "managed": len(accounts),
        "reserved": len(reserved),
        "draining": draining,
        "used": len(accounts) + len(reserved),
        "available": max(0, cap - len(accounts) - len(reserved)),
        "capacity": cap,
        "protected_originals": 6,
    }


def start(engine: "PaperEngine", policy: LabPolicy) -> dict[str, Any]:
    prior = engine.state.get("autonomous_lab")
    digest = fingerprint(policy.model_dump())
    if prior:
        if prior["policy_sha256"] != digest:
            raise ValueError(
                "The running lab's policy is frozen; pause/control it without rewriting"
            )
        return {"status": "already_started", "policy_sha256": digest}
    if slots(engine.state)["used"] > policy.slots:
        raise ValueError("Existing protected/managed accounts exceed the declared lab capacity")
    lab = {
        "policy": policy.model_dump(),
        "policy_sha256": digest,
        "started_at": engine.now,
        "proposals_paused": False,
        "entries_paused": False,
        "trials": {},
        "sequence": 0,
        "next_action_at": engine.now,
        "phase": "observe",
        "reason": "Awaiting permitted inputs",
        "last_score_at": None,
        "last_work_at": None,
        "historical_trials": 0,
        "horizon_cursor": 0,
        "initial_hypothetical_funding": "0",
        "retired_net_usd": "0",
        "retired_count": 0,
        "budget": {
            "day": int(engine.now // 86400),
            "trials": 0,
            "hour": int(engine.now // 3600),
            "steps": 0,
            "compute_seconds": 0.0,
            "measured_seconds": 0.0,
        },
    }
    engine.state["autonomous_lab"] = lab
    engine.emit("lab_policy_started", "system", deepcopy(lab))
    return {"status": "started", "policy_sha256": digest}


def periods(lab: dict[str, Any], now: float) -> None:
    b = lab["budget"]
    day, hour = int(now // 86400), int(now // 3600)
    if day > b["day"]:
        b.update(day=day, trials=0)
    if hour > b["hour"]:
        b.update(hour=hour, steps=0, compute_seconds=0.0, measured_seconds=0.0)


class InvalidProposal(ValueError):
    """Frozen proposal cannot be admitted; another eligible job may proceed."""


class AdmissionWait(ValueError):
    """Capacity/policy wait is retryable; it grants no financial permission."""


def validate_parent(state: dict[str, Any], proposal: LabProposal) -> None:
    if proposal.kind != "variation":
        return
    parent = state["autonomous_lab"]["trials"].get(proposal.parent_trial)
    if not parent or parent["status"] != "preserved":
        raise InvalidProposal("Only a preserved promising trial can be an automatic parent")
    account_state = state["accounts"].get(parent["candidate"])
    if (
        not account_state
        or account_state.get("risk_stop_id")
        or account_state.get("fault")
        or account_state.get("lab_retiring")
    ):
        raise InvalidProposal("Parent risk/processing stop prevents automatic descendants")
    if parent["contract"]["proposal"]["strategy"] != proposal.reference.model_dump():
        raise InvalidProposal("Child reference must use its parent's frozen rules")


def reserve(engine: "PaperEngine", proposal: LabProposal) -> dict[str, Any]:
    for spec in (proposal.strategy, proposal.reference):
        if spec.entry_filter:
            synthetic = "synthetic" in engine.state.get("evidence_kind", "")
            if (spec.entry_filter.artifact["evidence_kind"] == "synthetic_qa") != synthetic:
                raise InvalidProposal("Synthetic memory cannot enter an observed-market trial")
    lab = engine.state["autonomous_lab"]
    policy = LabPolicy.model_validate(lab["policy"])
    if proposal.policy_id != policy.request_id:
        raise InvalidProposal("Proposal names another policy")
    for t in lab["trials"].values():
        if t["proposal_id"] == proposal.request_id:
            return {"status": "already_reserved", "trial_id": t["id"]}
    validate_parent(engine.state, proposal)
    if lab["proposals_paused"] or engine.state["paused"]:
        raise AdmissionWait("Operator pause prevents new lab reservations")
    periods(lab, engine.now)
    if lab["budget"]["trials"] >= policy.daily_trials:
        raise AdmissionWait("UTC daily trial-creation budget exhausted")
    used = slots(engine.state)["used"]
    if used + 2 > policy.slots:
        raise AdmissionWait("Concurrent managed/reserved capacity is full")
    family = proposal.strategy.family
    family_count = sum(
        (
            2
            if t["status"] == "reserved"
            else sum(name in engine.state["accounts"] for name in (t["candidate"], t["reference"]))
        )
        for t in lab["trials"].values()
        if t["contract"]["proposal"]["strategy"]["family"] == family
    )
    if family_count + 2 > policy.family_slots:
        raise AdmissionWait("Per-family concurrent allocation is full")
    independent = sum(
        (
            2
            if t["status"] == "reserved"
            else sum(name in engine.state["accounts"] for name in (t["candidate"], t["reference"]))
        )
        for t in lab["trials"].values()
        if t["contract"]["proposal"]["kind"] == "independent"
    )
    if proposal.kind == "variation":
        if used + 2 + max(0, policy.independent_slots - independent) > policy.slots:
            raise AdmissionWait("Capacity is reserved for independent exploration")
    lab["sequence"] += 1
    trial_id = "lab-" + fingerprint({"policy": policy.request_id, "sequence": lab["sequence"]})[:24]
    t = {
        "id": trial_id,
        "proposal_id": proposal.request_id,
        "status": "reserved",
        "candidate": trial_id + "-candidate",
        "reference": trial_id + "-reference",
        "reserved_at": engine.now,
        "contract": contract(proposal, policy),
        "branched": False,
    }
    lab["trials"][trial_id] = t
    if proposal.kind == "independent":
        lab["horizon_cursor"] = lab.get("horizon_cursor", 0) + 1
    if proposal.parent_trial:
        lab["trials"][proposal.parent_trial]["branched"] = True
    lab["historical_trials"] += 1
    lab["budget"]["trials"] += 1
    engine.emit("lab_trial_reserved", "system", deepcopy(t))
    return {"status": "reserved", "trial_id": trial_id}


def fund(engine: "PaperEngine", trial_id: str) -> dict[str, Any]:
    lab = engine.state["autonomous_lab"]
    t = lab["trials"][trial_id]
    if t["status"] != "reserved":
        return {"status": "already_funded", "trial_id": trial_id}
    if lab["proposals_paused"] or engine.state["paused"]:
        return {"status": "paused", "trial_id": trial_id}
    p = LabPolicy.model_validate(lab["policy"])
    for role, key in (("candidate", "strategy"), ("reference", "reference")):
        name = t[role]
        if name in engine.state["accounts"]:
            raise ValueError("Reservation conflicts with an existing account identity")
        spec = t["contract"]["proposal"][key]
        a = account(
            "lab-rule-" + fingerprint(spec)[:24], engine.now, p.starting_cash, p.execution_profile
        )
        a.update(
            rule_spec=deepcopy(spec),
            campaign_id="autonomous-lab",
            lab_trial=trial_id,
            lab_role=role,
            label=f"{spec['family']} Â· {role}",
            admitted_at=engine.now,
            symbols=["BTCUSD"],
            benchmark_symbols=["BTCUSD"],
            operating_daily_usd=str(
                D(p.daily_operating_usd)
                + D(spec.get("entry_filter", {}).get("marginal_daily_usd", "0"))
            ),
            entries_paused=lab["entries_paused"],
            control_version=0,
            lab_protected=False,
        )
        engine.state["accounts"][name] = a
        engine.emit(
            "lab_account_funded",
            name,
            {
                "trial_id": trial_id,
                "proposal_id": t["proposal_id"],
                "role": role,
                "amount": p.starting_cash,
                "rule_spec": spec,
                "hypothetical": True,
            },
            [
                engine.line("USD", "cash", D(p.starting_cash)),
                engine.line("USD", "fake_funding", -D(p.starting_cash)),
            ],
        )
    t.update(
        status="active",
        started_at=engine.now,
        review_at=engine.now
        + max(
            p.horizon_seconds,
            RuleSpec.model_validate(t["contract"]["proposal"]["strategy"]).timing["review"],
        ),
        covered_seconds=0.0,
        last_observation=None,
        observed_decisions=0,
        passive=new_benchmark(p.starting_cash, p.execution_profile, engine.now, ("BTCUSD",)),
    )
    lab["initial_hypothetical_funding"] = str(
        D(lab["initial_hypothetical_funding"]) + 2 * D(p.starting_cash)
    )
    engine.emit("lab_trial_funded", "system", {"trial_id": trial_id, "at": engine.now})
    return {"status": "funded", "trial_id": trial_id}


def observe(engine: "PaperEngine", frames: dict[str, Any]) -> None:
    lab = engine.state.get("autonomous_lab")
    if not lab:
        return
    for t in lab["trials"].values():
        if t["status"] != "active" or t.get("sealed"):
            continue
        a, r = (engine.state["accounts"][t[key]] for key in ("candidate", "reference"))
        frame = frames.get("BTCUSD")
        good = (
            fresh_frame(frame, engine.now)
            and frame is not None
            and frame.get("entry_allowed", True)
            and sample(a, engine.now)["fresh"]
            and sample(r, engine.now)["fresh"]
            and not a.get("fault")
            and not r.get("fault")
        )
        previous = t["last_observation"]
        if good:
            if previous is not None and 0 <= engine.now - previous <= 5:
                t["covered_seconds"] += min(engine.now, t["review_at"]) - min(
                    previous, t["review_at"]
                )
            t["last_observation"] = engine.now
        else:
            t["last_observation"] = None
        for receipt in benchmark_tick(t["passive"], frames, engine.now):
            engine.emit("lab_passive_observation", "system", {"trial_id": t["id"], **receipt})
        t["observed_decisions"] = (
            sum(
                1
                for e in engine.events
                if e["kind"] == "decision" and e["account"] == t["candidate"]
            )
            + t["observed_decisions"]
        )
        if engine.now >= t["review_at"]:
            t["sealed"] = {
                "available_at": engine.now,
                "candidate": sample(a, engine.now),
                "reference": sample(r, engine.now),
                "passive": deepcopy(t["passive"]),
                "coverage_seconds": t["covered_seconds"],
                "inputs_valid": good,
                "risk_stopped": bool(a.get("risk_stop_id") or r.get("risk_stop_id")),
            }
            engine.emit(
                "lab_window_sealed", "system", {"trial_id": t["id"], **deepcopy(t["sealed"])}
            )
    advance_retirement(engine)


def review(engine: "PaperEngine", trial_id: str) -> dict[str, Any]:
    lab = engine.state["autonomous_lab"]
    t = lab["trials"][trial_id]
    if t.get("score"):
        return dict(t["score"])
    if not t.get("sealed"):
        raise ValueError("Wait for the fixed subsequent outcome window to be observed")
    p = LabPolicy.model_validate(lab["policy"])
    window = t["sealed"]
    valid = (
        window["inputs_valid"]
        and window["coverage_seconds"] >= (t["review_at"] - t["started_at"]) * p.coverage_fraction
        and window["candidate"]["fresh"]
        and window["reference"]["fresh"]
        and window["passive"]["fresh"]
        and window["passive"]["coverage"]
    )
    elapsed = D(str(window["available_at"] - t["started_at"]))
    operating = D(p.daily_operating_usd) * elapsed / 86400
    component_costs = {
        role: D(
            t["contract"]["proposal"][key].get("entry_filter", {}).get("marginal_daily_usd", "0")
        )
        * elapsed
        / 86400
        for role, key in (("candidate", "strategy"), ("reference", "reference"))
    }
    values = {
        role: D(window[role]["equity"])
        - D(p.starting_cash)
        - operating
        - component_costs.get(role, D(0))
        for role in ("candidate", "reference", "passive")
    }
    scores = {role: str(values[role]) if valid else None for role in ("candidate", "reference")}
    passive = str(values["passive"]) if valid else None
    difference = values["candidate"] - values["reference"]
    delta = str(difference) if valid else None
    outcome, reason = (
        "inconclusive",
        "Supported window does not show a positive economic distinction",
    )
    if window["risk_stopped"]:
        outcome, reason = (
            "risk_stopped",
            "Original hard stop retained; no replenishment or risk escalation",
        )
    elif not valid:
        outcome, reason = (
            "data_blocked",
            "Fixed window lacks complete executable marks/coverage; no strategy-failure claim",
        )
    elif all(
        window[role]["flat"]
        and window[role]["closed"] == 0
        and D(window[role]["equity"]) == D(p.starting_cash)
        for role in ("candidate", "reference")
    ):
        outcome, reason = (
            "low_information",
            "Observed complete window without executed exposure in either account; "
            "declared idle operating costs remain included",
        )
    elif values["candidate"] > 0 and difference >= 0 and values["candidate"] >= values["passive"]:
        outcome, reason = (
            "promising",
            "Positive after-cost value versus cash, matched reference and full-period passive",
        )
    elif values["candidate"] < 0 or difference < 0:
        outcome, reason = (
            "economically_unsuccessful",
            "After-cost account value is negative or below the matched reference",
        )
    score = {
        "trial_id": trial_id,
        "proposal_id": t["proposal_id"],
        "outcome": outcome,
        "reason": reason,
        "available_at": engine.now,
        "window_start": t["started_at"],
        "window_end": window["available_at"],
        "coverage_seconds": window["coverage_seconds"],
        "net_after_operating_usd": scores,
        "delta_usd": delta,
        "passive_usd": passive,
        "cash_usd": str(-operating) if valid else None,
        "operating_each_usd": str(operating),
        "candidate_sample": window["candidate"],
        "reference_sample": window["reference"],
        "fees_treatment": "Executable equity already includes entry/exit/liquidation costs once",
        "dependence": (
            "Related trials and shared market windows are correlated, not independent confirmation"
        ),
        "qualification": "Exploration only; no CP7 or live promotion",
    }
    if any(t["contract"]["proposal"][key].get("entry_filter") for key in ("strategy", "reference")):
        score["component_operating_usd"] = {k: str(v) for k, v in component_costs.items()}
    t["score"] = score
    lab["last_score_at"] = engine.now
    engine.emit("lab_trial_scored", "system", deepcopy(score))
    if outcome == "promising":
        a = engine.state["accounts"][t["candidate"]]
        a["lab_protected"] = True
        t["status"] = "preserved"
        retire_account(
            engine, t["reference"], "Matched comparison completed; parent continues unchanged"
        )
    elif any(
        engine.state["accounts"].get(t[key], {}).get("lab_protected")
        for key in ("candidate", "reference")
    ):
        t.update(
            status="operator_preserved",
            retirement_reason="Review recorded; operator protection prevents automatic retirement",
        )
        engine.emit(
            "lab_retirement_blocked",
            "system",
            {"trial_id": trial_id, "reason": t["retirement_reason"]},
        )
    else:
        retire_trial(engine, trial_id, outcome + ": " + reason)
    return score


def retire_account(engine: "PaperEngine", name: str, reason: str) -> None:
    a = engine.state["accounts"].get(name)
    if a is None:
        return
    if name in ORIGINALS or not a.get("lab_trial") or a.get("lab_protected"):
        raise ValueError("Protected/original accounts cannot be retired by this lab")
    if a.get("lab_retiring"):
        return
    a.update(lab_retiring={"at": engine.now, "reason": reason}, entries_paused=True)
    for symbol, order in list(a["pending"].items()):
        if order["side"] == "buy" and not order.get("uncertain"):
            engine.cancel(name, a, symbol, "Lab retirement: stop new entries")
    engine.emit("lab_account_draining", name, {"trial_id": a["lab_trial"], "reason": reason})


def retire_trial(engine: "PaperEngine", trial_id: str, reason: str) -> None:
    t = engine.state["autonomous_lab"]["trials"][trial_id]
    for role in ("candidate", "reference"):
        a = engine.state["accounts"].get(t[role])
        if a and a.get("lab_protected"):
            raise ValueError("Unprotect the experimental parent before requesting retirement")
    t.update(status="draining", retirement_reason=reason)
    for role in ("candidate", "reference"):
        retire_account(engine, t[role], reason)
    advance_retirement(engine)


def advance_retirement(engine: "PaperEngine") -> None:
    lab = engine.state.get("autonomous_lab")
    if not lab:
        return
    for name, a in list(engine.state["accounts"].items()):
        if not a.get("lab_retiring"):
            continue
        # No tolerance: even dust and uncertain/incomplete financial state keep capacity.
        if a["positions"] or a["pending"] or a.get("fault") or a.get("execution_uncertain"):
            continue
        engine.assert_account(a)
        engine.emit(
            "lab_account_archived",
            name,
            {
                "trial_id": a["lab_trial"],
                "state": deepcopy(a),
                "reason": a["lab_retiring"]["reason"],
            },
        )
        lab["retired_net_usd"] = str(D(lab["retired_net_usd"]) + D(a["cash"]) - D(a["funding"]))
        lab["retired_count"] += 1
        del engine.state["accounts"][name]
    for trial_id, t in list(lab["trials"].items()):
        if t["status"] != "reserved" and not any(
            t[k] in engine.state["accounts"] for k in ("candidate", "reference")
        ):
            engine.emit(
                "lab_trial_retired",
                "system",
                {
                    "trial_id": trial_id,
                    "reason": t.get("retirement_reason"),
                    "score": t.get("score"),
                },
            )
            del lab["trials"][trial_id]


def control(engine: "PaperEngine", action: str, target: str | None = None) -> dict[str, Any]:
    if "autonomous_lab" not in engine.state:
        raise ValueError("Start a declared policy before controlling the lab")
    lab = engine.state["autonomous_lab"]
    if action in {"pause_proposals", "resume_proposals"}:
        lab["proposals_paused"] = action == "pause_proposals"
    elif action in {"pause_entries", "resume_entries"}:
        lab["entries_paused"] = action == "pause_entries"
        for a in engine.state["accounts"].values():
            if a.get("lab_trial"):
                a["entries_paused"] = lab["entries_paused"] or bool(a.get("lab_retiring"))
    elif action in {"protect", "unprotect"}:
        a = engine.state["accounts"].get(target or "")
        if not a or not a.get("lab_trial") or a.get("lab_retiring"):
            raise ValueError("Select an active experimental account; retirement is irreversible")
        a["lab_protected"] = action == "protect"
    elif action == "retire":
        if target not in lab["trials"]:
            raise ValueError("Select an active lab trial")
        retire_trial(engine, str(target), "Operator requested retirement")
    else:
        raise ValueError("Unsupported autonomous-lab control")
    engine.emit("lab_operator_control", "system", {"action": action, "target": target})
    return {"status": "applied", "action": action}
