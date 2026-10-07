"""Local, tools-only stdio observation of the existing installed research owner."""

import hashlib
import json
import math
import re
import sys
import time
from collections.abc import Mapping
from typing import Any, BinaryIO, Literal, get_args

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ORIGIN = "http://127.0.0.1:8780"
PROTOCOLS = {"2025-03-26", "2025-06-18", "2025-11-25"}
LINE_BYTES = 16384
HTTP_BYTES = 262144
OUTPUT_BYTES = 98304
INSTRUCTIONS = (
    "Q-Trades research oversight and bounded operator diagnostics. Saved answers, failures "
    "and evidence remain "
    "historical facts; readiness is a current prerequisite, not research quality. Tool/data "
    "waits require their existing owners and new evidence. No model dispatch, retries, "
    "financial commands, training, paid/external review or automatic tool installation. "
    "The six bounded diagnostics may write existing tool receipts; Pause only disables the "
    "existing pilot. Both use fixed operator routes, never resume or enqueue research. "
    "Unknown write acknowledgments must be reconciled without automatic POST retries. "
    "Use observed task IDs and evidence hashes for a reviewable source-work handoff."
)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HistoryArguments(Arguments):
    before: float = Field(default=0, ge=0, allow_inf_nan=False)
    before_id: str = Field(default="", max_length=100)
    search: str = Field(default="", max_length=100)


class TaskArguments(Arguments):
    task_id: str = Field(pattern=r"^role-[a-f0-9]{32}$")


class LessonArguments(Arguments):
    before: int = Field(default=0, ge=0)
    text: str = Field(default="", max_length=200)
    family: str = Field(default="", max_length=100)
    horizon: str = Field(default="", max_length=20)
    outcome: str = Field(default="", max_length=100)


DiagnosticTool = Literal[
    "input_diagnosis",
    "cost_diagnosis",
    "market_evidence",
    "cost_hurdle",
    "strategy_evidence",
    "outcome_review",
]
DIAGNOSTIC_IDS = frozenset(get_args(DiagnosticTool))


class DiagnosticArguments(Arguments):
    tool: DiagnosticTool
    symbol: str = Field(min_length=3, max_length=24, pattern=r"^[A-Z0-9]+$")
    account: str = Field(min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$")
    start: float = Field(ge=0, allow_inf_nan=False)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,64}$")


class DiagnosticResultArguments(Arguments):
    run_id: int = Field(ge=1, le=9223372036854775807)


WRITE_TOOLS = {"research_run_diagnostic", "research_pause"}


TOOLS: dict[str, tuple[type[Arguments], str, str]] = {
    "research_status": (
        HistoryArguments,
        "/api/lab/roles",
        "Observe current researcher activity/readiness and one saved-question page.",
    ),
    "research_task": (
        TaskArguments,
        "/api/lab/roles/tasks/",
        "Reopen one saved question, answers/failures, matched-rule evaluation and typed waits.",
    ),
    "research_lessons": (
        LessonArguments,
        "/api/research/lessons",
        "Read one supported-lesson page through the existing outcome-disclosure owner.",
    ),
    "research_quality": (
        Arguments,
        "/api/research/quality",
        "Observe recorded activity and explicitly unmeasured matched research/economic value.",
    ),
    "research_capabilities": (
        Arguments,
        "/api/research/tools",
        "Inspect current read-only tool descriptions; no execution or installation authority.",
    ),
    "research_run_diagnostic": (
        DiagnosticArguments,
        "/api/research/tools/run",
        "Run one of six existing bounded evidence diagnostics with explicit scope and a stable "
        "request_id. Writes a tool receipt; no model or financial command. Never auto-retry.",
    ),
    "research_diagnostic_result": (
        DiagnosticResultArguments,
        "/api/research/tools/runs/",
        "Reopen one exact saved diagnostic run_id, including retained failures; no new run.",
    ),
    "research_pause": (
        Arguments,
        "/api/lab/roles/control",
        "Pause the existing paper pilot. Does not resume, kill processes or create research. "
        "Acknowledgment is separate from child cleanup; inspect current status afterward.",
    ),
    "research_paper_trials": (
        Arguments,
        "/api/autonomous",
        "Observe existing paper Lab policy, slots, account IDs, trials and bounded proposal queue. "
        "Recorded funding/results remain exploratory; no financial or proposal commands.",
    ),
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def fields(value: Any, names: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected observed object")
    return {name: value[name] for name in names.split() if name in value}


# Explicit scientific fields only. Unknown/new payload fields require a source
# review before disclosure; dynamic evidence IDs are handled at their own boundary.
SCIENCE_KEYS = frozenset(
    "action capability evidence_ids mechanism falsification rationale dependency kind identifier "
    "purpose required_inputs acceptance_checks unsupported_basis tool_request issues "
    "request_id policy_id family holding_horizon horizon parent parent_trial strategy reference "
    "lookback entry_atr exit_atr stop_atr take_profit_atr max_hold_seconds entry_filter "
    "sha256 version arm evidence_kind normalization neighbors minimum_groups maximum_weight "
    "library_groups train_end calibration_end calibration_groups limits retained "
    "method_sha256 strategy_sha256 reference_sha256 input_sha256 detail_status input_count "
    "evaluated_at eligible supported reason status errors summary candidate baseline cash passive "
    "matched paired difference net_after_cost_usd delta_usd return_bps net_bps fees_usd "
    "fills trades closed_trades observations coverage_seconds outcome proposal_id body "
    "window_start window_end available_at maturity_start maturity_end expires_at "
    "net_after_operating_usd passive_usd cash_usd operating_each_usd fees_treatment "
    "source_basis closed_bar_sha256 closed_bars symbol cutoff start end count latest_closed_at "
    "eligible_count ineligible_count eligibility features atr spread_bps breakout range "
    "latest_close signal narrative permitted entry_eligible eligible_for_research "
    "cost_policy cost_sha256 cost_policy_sha256 fee_rate slippage_bps spread_cost_bps "
    "horizon_seconds operating_daily_usd daily_operating_usd maximum_positions "
    "claim context cause support recorded_comparisons independent_samples source_sha256 "
    "supporting_facts contrary_facts unknowns next_test reconsideration interpretation_scope "
    "selection access reads last_read selected_at task next_task novelty_sha256 "
    "requirement wait_requirement followup data_basis lesson predecessor_task "
    "mechanism_family periods train_count calibration_count comparable matched_windows "
    "complete complete_windows incomplete_windows required_seconds observed_seconds "
    "qualified experimental execution_mode pilot_grant_id contract contract_sha256 "
    "profile_sha256 packet_sha256 candidate_sha256 runner_sha256 question policy_sha256 "
    "wait_requirements feature financial_authority profit_required replay id "
    "method useful_completions defect_detection false_rejection evidence_correctness "
    "quality_per_budget subsequent_matched_windows net_benefit independent_support "
    "hardware_dollars supported attempts_with_counts input_tokens output_tokens "
    "unknown_attempts measured_wall_seconds basis tool security closed_bar_count observed_at "
    "scope executable_book bids asks update_id bid ask spread volume_ratio trend_up close "
    "bar_open_ms ema20_5m input_available_at timing excursion_bps modeled_hurdle_bps "
    "volume_multiple input_version risk_envelope exit_seconds progress_seconds replication_of "
    "last_closed_at source_sha256 maximum_hold progress review feature_seconds warmup_minutes "
    "daily_operating_usd execution_profile state".split()
)
PRIVATE_PATH = re.compile(r"(?i)(?:\b[a-z]:[\\/]|\\\\)[^\s\"'<>]*")


def scientific(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        raise ValueError("Scientific record exceeds its nesting bound")
    if isinstance(value, dict):
        return {k: scientific(v, depth + 1) for k, v in value.items() if k in SCIENCE_KEYS}
    if isinstance(value, list):
        if len(value) > 128:
            raise ValueError("Scientific list exceeds its bound; use the existing detail owner")
        return [scientific(v, depth + 1) for v in value]
    if isinstance(value, str):
        return PRIVATE_PATH.sub("[private path omitted]", value)
    if value is None or type(value) in {int, bool}:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("Scientific record contains an unsupported value")


AUTHORITY_FIELDS = "question_policy grant_id grant_sha profile_sha contract_version contract_sha"
CONTROL_FIELDS = (
    "volume_multiple holding_horizon exit_seconds progress_seconds stop_atr input_version"
)


def selection_authority(value: Any) -> dict[str, Any]:
    """Disclose the recorded six public identities, never a grant/profile payload."""
    result = fields(value, AUTHORITY_FIELDS)
    if len(result) != 6 or any(
        not isinstance(v, str) or not v or len(v) > 128 for v in result.values()
    ):
        raise ValueError("Recorded selection authority is incomplete or invalid")
    for key in ("grant_sha", "profile_sha", "contract_sha"):
        if re.fullmatch(r"[a-f0-9]{64}", result[key]) is None:
            raise ValueError("Recorded selection authority identity is invalid")
    for key in ("question_policy", "grant_id", "contract_version"):
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result[key]) is None:
            raise ValueError("Recorded selection authority identifier is invalid")
    return {key: scientific(v) for key, v in result.items()}


def question_selection(value: Any) -> dict[str, Any]:
    result = flat(
        value,
        "method horizon source_sha source_start source_end source_count source_basis "
        "strategy_sha reference_sha scope_sha selection_sha prior_selection "
        "excursion_bps modeled_hurdle_bps reason falsification",
    )
    for key in (
        "source_sha",
        "strategy_sha",
        "reference_sha",
        "scope_sha",
        "selection_sha",
        "prior_selection",
    ):
        if (
            key in result
            and result[key] is not None
            and (
                not isinstance(result[key], str)
                or re.fullmatch(r"[a-f0-9]{64}", result[key]) is None
            )
        ):
            raise ValueError("Recorded selection evidence identity is invalid")
    if "source_count" in result and (
        type(result["source_count"]) is not int or result["source_count"] < 0
    ):
        raise ValueError("Recorded selection source count is invalid")
    for key in ("source_start", "source_end", "excursion_bps", "modeled_hurdle_bps"):
        if key in result and type(result[key]) not in {int, float}:
            raise ValueError("Recorded selection measurement is invalid")
    if "authority" in value:
        result["authority"] = selection_authority(value["authority"])
    if "lesson" in value:
        result["lesson"] = None if value["lesson"] is None else flat(value["lesson"], "id sha256")
    if "limitations" in value:
        limitations = value["limitations"]
        if (
            not isinstance(limitations, list)
            or len(limitations) > 8
            or any(not isinstance(item, str) for item in limitations)
        ):
            raise ValueError("Recorded selection limitations exceed their bound")
        result["limitations"] = scientific(limitations)
    return result


def fixed_comparison(value: Any) -> dict[str, Any]:
    """Project verified recorded controls; this is not the private issued packet."""
    value = fields(value, "strategy reference strategy_sha256 reference_sha256")
    result: dict[str, Any] = {"basis": "recorded_catalog"}
    for arm in ("strategy", "reference"):
        original = value.get(arm)
        expected = value.get(arm + "_sha256")
        # Catalog identities use the registry's original JSON spacing, unlike
        # this observer's compact fetched-payload digest. No engine import.
        recorded_sha = hashlib.sha256(
            json.dumps(original, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        if not isinstance(original, dict) or expected != recorded_sha:
            raise ValueError("Recorded comparison identity is unavailable or invalid")
        controls = flat(original, CONTROL_FIELDS)
        if len(controls) != 6:
            raise ValueError("Recorded comparison controls are incomplete")
        result[arm] = controls
        result[arm + "_sha256"] = expected
    return result


DIAGNOSTIC_KEYS = SCIENCE_KEYS | frozenset(
    "result envelope interval snapshot account actor query cutoff revision maximum_event_id "
    "event_id event_ids total missing gaps observed coverage expected duration_seconds "
    "gross_usd gross_pnl_usd net_usd net_pnl_usd cost_usd costs slippage_usd "
    "price quantity quote_notional_usd spread round_trip_bps minimum_required_move_bps "
    "cost_hurdle_bps last_decision decision inputs_available last_tick stale error "
    "detail live book metrics charts candles candle_gaps indicators points points_omitted "
    "calculation_history_bars observed_trades best_bid best_ask spread_percent "
    "freshness input_coverage fee_assumption slippage_assumption instrument "
    "summary_state after_cost cohort gross after_cost_usd recorded_cost_usd "
    "observation_cutoff source_available_at retrieved_at facts_basis coverage_fraction "
    "receipt_limit_bytes model_tokens token_basis coverage references type "
    "diagnosis summary population measured facts hypotheses unresolved next_question rows "
    "retained_samples_inspected evaluable not_evaluable_or_unknown later_available_excluded "
    "more_retained_records total_engine_ticks source_bytes maximum_records maximum_bytes "
    "byte_basis maximum_query_seconds problem_counts problems could_evaluate original_scope "
    "original_input_eligibility original_frame_source candle_status original_book_measurements "
    "spread_depth_basis recorded_decision prior_decision decision_at_this_tick decision_meaning "
    "frame_present candle_error continuous retained_bars last_close_ms computed_at available_at "
    "ready_at rule_spec entries_paused closed_trades shown_original_events more_original_events "
    "winner_only_selection shown_cost_groups more_cost_groups gross_before_recorded_fees_usd "
    "recorded_fees_usd net_closed_pnl_usd net_basis gross_basis whole_account account_totals_basis "
    "accounting_at closed_trade_cohort open_holdings pending_orders original_cost_groups "
    "matched_trial_comparison policy_basis market_totals account_totals comparison_basis "
    "first_opened_at queried_at has_more events body next_cursor groups more_groups maximum_groups "
    "reserved available_cash units realized unrealized net_pnl equity cash funding nav "
    "valuation_at execution_drag "
    "liquidation_fee liquidation_drag settings_version starting_capital flat closed wins "
    "valuation_issues purpose final final_at accounting_basis position pending feature_basis "
    "primary_market next_review total_cost cost exit_proceeds quantity_remaining created_at "
    "round_trip_loss_percent required_bid required_bid_move_percent fee_per_side "
    "adverse_price_per_side participation_cap price_tick position_hurdle "
    "original_cost_including_entry_fees partial_exit_net_proceeds remaining_required_net_proceeds "
    "remaining_quantity selected_symbol markets markets_omitted levels_shown trade_gaps "
    "trade_tape_limit trade_tape_scope generated_at scan omitted selected constrained "
    "open_ms close_ms open high low volume candles_stale history_scope vwap_anchor_ms "
    "ema vwap rsi strategy experiments paper_events confirmed "
    "candidate net_after_operating_usd delta_usd passive_usd cash_usd operating_each_usd "
    "candidate_sample reference_sample window_start window_end inputs_valid "
    "dependence qualification "
    "capital drawdown peak start covered_seconds coverage_seconds observed_decisions".split()
)


def diagnostic_facts(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        raise ValueError("Diagnostic record exceeds its nesting bound")
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key not in DIAGNOSTIC_KEYS:
                continue
            if key in {"open_holdings", "pending_orders", "valuation_issues"}:
                if (
                    not isinstance(item, dict)
                    or len(item) > 128
                    or any(re.fullmatch(r"[A-Z0-9]{3,24}", symbol) is None for symbol in item)
                ):
                    raise ValueError("Diagnostic market mapping is invalid")
                result[key] = {
                    symbol: diagnostic_facts(row, depth + 1) for symbol, row in item.items()
                }
            elif key == "problem_counts":
                if (
                    not isinstance(item, dict)
                    or len(item) > 128
                    or any(
                        re.fullmatch(r"[a-z0-9_]{1,96}", problem) is None
                        or type(count) is not int
                        or count < 0
                        for problem, count in item.items()
                    )
                ):
                    raise ValueError("Diagnostic problem counts are invalid")
                result[key] = item.copy()
            else:
                result[key] = diagnostic_facts(item, depth + 1)
        return result
    if isinstance(value, list):
        if len(value) > 128:
            raise ValueError("Diagnostic list exceeds its bound; use the existing detail owner")
        return [diagnostic_facts(item, depth + 1) for item in value]
    return scientific(value, depth)


def diagnostic_projection(body: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    if (
        type(body.get("id")) is not int
        or body["id"] <= 0
        or body.get("status") not in {"running", "completed", "failed", "interrupted"}
        or body.get("tool") not in DIAGNOSTIC_IDS
        or body.get("actor") != "local_operator"
    ):
        raise ValueError("Saved diagnostic receipt identity is invalid")
    query = body.get("query")
    query = decode(query.encode()) if isinstance(query, str) else query
    if "run_id" in values:
        if body["id"] != values["run_id"]:
            raise ValueError("Saved diagnostic run identity differs")
    elif (
        body.get("request_id") != values["request_id"]
        or query != {key: value for key, value in values.items() if key != "request_id"}
        or any(body.get(key) != values[key] for key in ("tool", "symbol", "account"))
    ):
        raise ValueError("Saved diagnostic request scope differs")
    result = flat(
        body,
        "id started finished tool symbol actor account status error version request_id "
        "result_sha256",
    )
    result["query"] = flat(query, "tool symbol account start") if isinstance(query, dict) else None
    error = result.get("error")
    result["error_sha256"] = digest(body["error"]) if body.get("error") is not None else None
    if isinstance(error, str) and len(error.encode()) > 2048:
        result["error"] = None
        result["error_projection_available"] = False
    raw = body.get("result")
    if raw is not None and body.get("result_sha256") != digest(raw):
        raise ValueError("Saved diagnostic result checksum differs")
    try:
        result["result"] = diagnostic_facts(raw)
        result["result_projection_available"] = True
    except (ValueError, TypeError, RecursionError):
        # The exact acknowledged receipt remains usable even when its facts need
        # the ordinary detail reader. Never retry a POST to repair presentation.
        result["result"] = None
        result["result_projection_available"] = False
    return result


def paper_trials_projection(body: dict[str, Any]) -> dict[str, Any]:
    """Observe existing Lab facts without creating accounts, funds or proposals."""
    result = flat(body, "enabled last_error provider_required qualification financial_authority")
    lab = body.get("lab")
    if not isinstance(lab, dict):
        raise ValueError("Existing paper Lab state is unavailable")
    result["lab"] = flat(
        lab,
        "phase reason entries_paused proposals_paused policy_sha256 sequence started_at "
        "last_work_at last_score_at next_action_at initial_hypothetical_funding historical_trials "
        "retired_count retired_net_usd horizon_cursor",
    )
    result["lab"]["budget"] = flat(
        lab.get("budget", {}), "day hour steps trials compute_seconds measured_seconds"
    )
    policy = lab.get("policy")
    result["lab"]["policy"] = None
    if isinstance(policy, dict):
        result["lab"]["policy"] = flat(
            policy,
            "version request_id slots family_slots independent_slots daily_trials "
            "hourly_steps hourly_compute_seconds starting_cash horizon_seconds cooldown_seconds "
            "coverage_fraction daily_operating_usd paid_usd execution_profile "
            "minimum_disk_gib registry_mib",
        )
        result["lab"]["policy"]["holding_horizons"] = scientific(policy.get("holding_horizons"))
    result["slots"] = flat(
        body.get("slots"), "managed reserved draining used available capacity protected_originals"
    )
    result["accounts"] = {}
    result["lab"]["trials"] = {}
    rule_fields = CONTROL_FIELDS + " family lookback symbol version risk_envelope"
    for key, source in (("accounts", body.get("accounts")), ("trials", lab.get("trials"))):
        if not isinstance(source, dict) or len(source) > 20:
            raise ValueError("Paper account/trial map exceeds its bounded owner scope")
        for identity, value in source.items():
            if re.fullmatch(r"[A-Za-z0-9_-]{1,96}", identity) is None or not isinstance(
                value, dict
            ):
                raise ValueError("Paper account/trial identity is invalid")
            if key == "accounts":
                saved = flat(
                    value,
                    "equity cash reserved available_cash funding units fees realized "
                    "unrealized net_pnl nav fresh valuation_at execution_drag liquidation_fee "
                    "liquidation_drag execution_profile risk_policy strategy_version "
                    "settings_version "
                    "operating_daily_usd starting_capital flat closed wins protected draining "
                    "risk_stop_id entries_paused purpose",
                )
                saved["rule_spec"] = (
                    flat(value["rule_spec"], rule_fields)
                    if value.get("rule_spec") is not None
                    else None
                )
                result["accounts"][identity] = saved
            else:
                saved = flat(
                    value,
                    "id proposal_id candidate reference status reason branched "
                    "reserved_at started_at review_at covered_seconds last_observation "
                    "observed_decisions outcome retired_at retirement_reason",
                )
                contract = value.get("contract")
                saved["contract"] = None
                if isinstance(contract, dict):
                    saved["contract"] = flat(
                        contract, "entry inputs no_trade sizing criteria qualification"
                    )
                    for field in ("costs", "evaluation", "exit", "unchanged"):
                        saved["contract"][field] = flat(
                            contract.get(field, {}),
                            "daily_usd fees funding_each profile coverage review seconds "
                            "feature_seconds "
                            "maximum_hold outcome progress protection warmup_minutes "
                            + rule_fields,
                        )
                    proposal = contract.get("proposal")
                    if not isinstance(proposal, dict):
                        raise ValueError("Recorded paper trial proposal is unavailable")
                    saved["contract"]["proposal"] = flat(
                        proposal,
                        "request_id kind mechanism question policy_id source parent_trial "
                        "parent_strategy_sha256 replication_of evidence_bundle_sha256",
                    )
                    for arm in ("strategy", "reference"):
                        saved["contract"]["proposal"][arm] = flat(proposal.get(arm), rule_fields)
                for field in ("score", "passive"):
                    if field in value:
                        saved[field] = diagnostic_facts(value[field])
                result["lab"]["trials"][identity] = saved
    inbox = body.get("inbox")
    if (
        not isinstance(inbox, dict)
        or not isinstance(inbox.get("proposals"), list)
        or len(inbox["proposals"]) > 20
    ):
        raise ValueError("Paper proposal queue is unavailable or exceeds its page bound")
    result["inbox"] = flat(inbox, "has_more next_before")
    result["inbox"]["proposals"] = [
        flat(row, "seq request_id status reason trial_id created") for row in inbox["proposals"]
    ]
    counts = inbox.get("counts", [])
    if not isinstance(counts, list) or len(counts) > 20:
        raise ValueError("Paper proposal counts exceed their bound")
    result["inbox"]["counts"] = [flat(row, "status count") for row in counts]
    return result


def task_projection(body: dict[str, Any], identity: str) -> dict[str, Any]:
    context, attempts = body.get("context"), body.get("attempts")
    if (
        body.get("id") != identity
        or not isinstance(context, dict)
        or not isinstance(attempts, list)
    ):
        raise ValueError("Saved task identity or record is unavailable")
    if len(attempts) > 32:
        raise ValueError("Saved task exceeds the bounded attempt page")
    if context.get("knowledge") is not None:
        raise ValueError("Knowledge-backed answers need their separate disclosure authority")
    result = flat(body, "id created updated stage status reason")
    result["execution"] = flat(body.get("execution", {}), "kind lease_until")
    result["contract_applicability"] = flat(
        body.get("contract_applicability", {}), "state reason recorded_contract selected_contract"
    )
    # Full knowledge contexts and private training payloads are outside this connection.
    result["context"] = scientific(
        fields(
            context,
            "contract question execution_mode pilot_grant_id experimental qualified "
            "policy_sha256 predecessor_task wait_requirements",
        )
    )
    result["context"]["question"] = flat(context.get("question", {}), "question horizon parent")
    if "selection_authority" in context:
        result["context"]["selection_authority"] = selection_authority(
            context["selection_authority"]
        )
    if "question_selection" in context:
        result["context"]["question_selection"] = question_selection(context["question_selection"])
    result["context"]["catalog"] = {
        key: scientific(value)
        for key, value in context.get("catalog", {}).items()
        if re.fullmatch(r"r[0-9]{1,2}", key)
    }
    if context.get("contract") == "reviewed-rule-role-v7":
        for key, value in result["context"]["catalog"].items():
            value["fixed_comparison"] = fixed_comparison(context["catalog"][key])
    evidence = context.get("tool_evidence", {})
    result["context"]["tool_evidence"] = scientific(evidence)
    result["context"]["tool_evidence"]["features"] = {
        key: scientific(value)
        for key, value in evidence.get("features", {}).items()
        if re.fullmatch(r"r[0-9]{1,2}", key)
    }
    result["context"]["wait_requirements"] = {
        key: scientific(value)
        for key, value in context.get("wait_requirements", {}).items()
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
    }
    result["evidence_sha256"] = digest(evidence)
    result["recorded_context_sha256"] = digest(context)
    issued_sha = context.get("issued", {}).get("sha256")
    if issued_sha is not None and (
        not isinstance(issued_sha, str) or re.fullmatch(r"[a-f0-9]{64}", issued_sha) is None
    ):
        raise ValueError("Recorded bundle identity is invalid")
    result["issued_bundle_sha256"] = issued_sha
    for key in ("proposal", "evaluation", "result"):
        result[key] = scientific(body.get(key))
        result[key + "_sha256"] = digest(body.get(key))
    result["attempts"] = []
    for attempt in attempts:
        saved = flat(
            attempt,
            "stage attempt started finished status input_tokens output_tokens "
            "measured_wall_seconds",
        )
        response = attempt.get("response")
        profile = attempt.get("profile")
        saved["profile_sha256"] = digest(profile) if profile is not None else None
        saved["response_sha256"] = digest(response) if response is not None else None
        if isinstance(response, dict):
            complete = response.get("complete")
            saved["complete"] = complete if type(complete) is bool else None
            saved["completion_field_valid"] = type(complete) is bool
            saved["answer"] = scientific(response.get("answer"))
            transport = flat(response, "status exception_type")
            saved["transport_status"] = transport.get("status")
            saved["exception_type"] = transport.get("exception_type")
        else:
            saved["complete"] = None
            saved["answer"] = None
        result["attempts"].append(saved)
    result["handoff"] = {
        "state": "implementation_review"
        if body.get("stage") == "tool_wait"
        else "evidence_wait"
        if body.get("stage") == "data_wait"
        else "inspect_saved_result",
        "authority": "Review guidance only; this tool cannot advance, retry or execute the task",
    }
    return result


def flat(value: Any, names: str) -> dict[str, Any]:
    selected = fields(value, names)
    if any(isinstance(v, (dict, list)) for v in selected.values()):
        raise ValueError("Expected scalar observation fields")
    return {k: scientific(v) for k, v in selected.items()}


def decode(raw: bytes | bytearray) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def constant(value: str) -> Any:
        raise ValueError("Non-finite JSON value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


class Observer:
    def __init__(self, client: httpx.Client):
        self.client = client
        self.initialized = False
        self.ready = False

    def get(self, path: str, params: Mapping[str, Any], deadline: float) -> dict[str, Any]:
        status, body = self.fetch("GET", path, params, deadline)
        if status >= 300:
            response = httpx.Response(status, request=httpx.Request("GET", ORIGIN + path))
            response.raise_for_status()
        return body

    def fetch(
        self, method: str, path: str, values: Mapping[str, Any], deadline: float
    ) -> tuple[int, dict[str, Any]]:
        if time.monotonic() >= deadline:
            raise ValueError("Observation deadline elapsed")
        headers = {"Accept-Encoding": "identity", "Accept": "application/json"}
        if method == "POST":
            headers["X-Local-Operator"] = "1"
            if len(json.dumps(dict(values), allow_nan=False).encode()) > 4096:
                raise ValueError("Operator request exceeds its body bound")
        with self.client.stream(
            method,
            ORIGIN + path,
            params=values if method == "GET" else None,
            json=dict(values) if method == "POST" else None,
            timeout=2,
            follow_redirects=False,
            headers=headers,
        ) as response:
            status = response.status_code
            if method == "GET":
                response.raise_for_status()
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Compressed observation refused before decoding")
            raw = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() >= deadline or len(raw) + len(chunk) > HTTP_BYTES:
                    raise ValueError("Observation response exceeds its byte/time bound")
                raw.extend(chunk)
        body = decode(raw)
        if not isinstance(body, dict):
            raise ValueError("Observed response is not an object")
        return status, body

    def operator_write(
        self, name: str, path: str, values: dict[str, Any], health: dict[str, Any], deadline: float
    ) -> dict[str, Any]:
        command = {"action": "pause"} if name == "research_pause" else values
        operation: dict[str, Any] = {
            "state": "unknown",
            "committed": None,
            "automatic_retry": False,
            "request": command,
            "child_cleanup_verified": None,
        }
        body: dict[str, Any] | None = None
        observed: dict[str, Any] | None = None
        try:
            status, body = self.fetch("POST", path, command, deadline)
            operation["http_status"] = status
            if status in {403, 409, 422, 429}:
                operation.update(state="refused", committed=False)
            elif 200 <= status < 300:
                if name == "research_run_diagnostic":
                    observed = diagnostic_projection(body, values)
                    operation.update(
                        state="committed",
                        committed=True,
                        run_id=observed["id"],
                        diagnostic_succeeded=observed["status"] == "completed",
                    )
                else:
                    observed = flat(
                        body, "enabled paper_pilot experimental execution_mode contract"
                    )
                    observed["readiness"] = flat(
                        body.get("readiness"),
                        "configured_enabled enabled ready qualified qualification_valid grant_id",
                    )
                    observed["activity"] = flat(
                        body.get("activity"),
                        "state reason checked_at pending_tools pending_data pending_outcomes "
                        "queued",
                    )
                    if observed["readiness"].get("configured_enabled") is False:
                        operation.update(state="paused", committed=True)
            # Server503 can occur after saving a receipt or disabling the pilot.
            # It is never evidence that the write did not happen.
        except (ValueError, TypeError, KeyError, RecursionError, httpx.HTTPError) as exc:
            operation["error_type"] = type(exc).__name__
        if operation["state"] == "unknown":
            operation["next_action"] = (
                "Inspect the exact saved run_id if known or existing tool history; "
                "do not auto-retry"
                if name == "research_run_diagnostic"
                else "Read current researcher status; acknowledgment does not establish "
                "child cleanup"
            )
        result = {
            "observed_at": time.time(),
            "installed_commit": health["code_commit"],
            "operation": operation,
            "observed": observed,
            "observed_payload_sha256": digest(body) if body is not None else None,
            "authority": "Existing operator diagnostic/Pause routes only; no model, finance "
            "or research enqueue",
            "projection": "Selected receipt/status facts; full fetched values are hash-bound, "
            "private data omitted",
        }
        return result

    def observe(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        model, path, _ = TOOLS[name]
        values = model.model_validate(arguments).model_dump()
        deadline = time.monotonic() + 10
        health = self.get("/api/health", {}, deadline)
        if health.get("mode") != "paper" or health.get("service") != "running":
            raise ValueError("Installed paper service identity unavailable")
        if not isinstance(health.get("code_commit"), str) or not re.fullmatch(
            r"[a-f0-9]{40}", health["code_commit"]
        ):
            raise ValueError("Installed source identity unavailable")
        if name in WRITE_TOOLS:
            return self.operator_write(name, path, values, health, deadline)
        identity = values.pop("task_id", "")
        if name == "research_diagnostic_result":
            identity = str(values["run_id"])
        if name == "research_capabilities":
            values["include_history"] = False
        body = self.get(
            path + identity, {} if name == "research_diagnostic_result" else values, deadline
        )
        if name == "research_task":
            observed = task_projection(body, identity)
        elif name == "research_diagnostic_result":
            observed = diagnostic_projection(body, values)
        elif name == "research_paper_trials":
            observed = paper_trials_projection(body)
        elif name == "research_status":
            if not isinstance(body.get("tasks"), list) or len(body["tasks"]) > 20:
                raise ValueError("Observed history page is unavailable")
            observed = flat(
                body,
                "enabled paper_pilot experimental execution_mode contract "
                "next_before next_before_id",
            )
            task_fields = "id question created updated stage status reason lease_until"
            observed["tasks"] = [flat(v, task_fields) for v in body["tasks"]]
            observed["current_task"] = (
                flat(body["current_task"], task_fields)
                if body.get("current_task") is not None
                else None
            )
            observed["activity"] = flat(
                body.get("activity"),
                "state reason checked_at pending_tools pending_data pending_outcomes queued",
            )
            observed["history"] = flat(body.get("history"), "retained archived active hot_limit")
            if "question_selection" in body:
                selected = body["question_selection"]
                observed["question_selection"] = flat(
                    selected, "policy state reason experimental task"
                )
                if "evidence" in selected:
                    observed["question_selection"]["evidence"] = (
                        None
                        if selected["evidence"] is None
                        else question_selection(selected["evidence"])
                    )
            readiness = flat(
                body.get("readiness"),
                "qualified qualification_valid ready enabled "
                "configured_enabled paper_pilot experimental mode grant_id "
                "runtime_available",
            )
            readiness["operating_admission"] = flat(
                body["readiness"].get("operating_admission", {}),
                "state checked_at next_action meaning",
            )
            profile = body["readiness"].get("profile")
            readiness["profile_sha256"] = digest(profile) if profile is not None else None
            observed["readiness"] = readiness
        elif name == "research_lessons":
            if not isinstance(body.get("lessons"), list) or len(body["lessons"]) > 20:
                raise ValueError("Observed lesson page is unavailable")
            observed = {
                "lessons": scientific(body["lessons"]),
                **flat(body, "next_before"),
            }
        elif name == "research_capabilities":
            if body.get("history_requested") is not False:
                raise ValueError("Catalog-only observation is unavailable on this API")
            observed = {
                "authority": "Read-only descriptions; no execution authority",
                "history_requested": False,
                "tools": [flat(v, "id name label description purpose") for v in body["tools"]],
            }
        else:
            observed = flat(
                body,
                "assessment attempts failed_attempts "
                "unknown_status_attempts external_attempts selection_warning",
            )
            for key in ("native_usage", "matched_research_arms", "economic_value"):
                observed[key] = scientific(body.get(key))
            observed["activity"] = flat(
                body.get("activity", {}), "queued waiting running answered done failed"
            )
        monitoring = health.get("journal_monitoring")
        journal: dict[str, Any] = (
            flat(
                monitoring,
                "available status balanced checked_at revision audit_age_seconds imbalanced_events",
            )
            if isinstance(monitoring, dict)
            else {"available": None, "status": "unavailable"}
        )
        journal["error_reported"] = (
            bool(monitoring["error"])
            if isinstance(monitoring, dict) and "error" in monitoring
            else None
        )
        return {
            "observed_at": time.time(),
            "installed_commit": health["code_commit"],
            "paper_health": {
                **flat(
                    health,
                    "paper_fresh journal_balanced journal_last_balanced paper_error_reported paper",
                ),
                "journal_monitoring": journal,
            },
            "observed_payload_sha256": digest(body),
            "observed": observed,
            "projection": "Selected scientific/status fields; private/raw payloads omitted. "
            "Hashes bind complete fetched values, not a reconstructed packet.",
            "authority": "Read-only oversight; no financial, model or task-control authority",
        }

    def rpc(self, body: Any) -> dict[str, Any] | None:
        identity = body.get("id") if isinstance(body, dict) else None

        def error(code: int, message: str) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": identity, "error": {"code": code, "message": message}}

        if (
            not isinstance(body, dict)
            or set(body) - {"id", "jsonrpc", "method", "params"}
            or (body.get("jsonrpc") != "2.0")
            or (
                "id" in body
                and (
                    type(identity) not in {str, int}
                    or isinstance(identity, str)
                    and len(identity) > 100
                )
            )
            or not isinstance(body.get("method"), str)
        ):
            identity = None
            return error(-32600, "Invalid JSON-RPC request")
        method, params = body["method"], body.get("params", {})
        if "id" not in body:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            return None  # Notifications never perform GETs or return a response.
        if not isinstance(params, dict):
            return error(-32602, "Object parameters required")
        if method == "initialize":
            client = params.get("clientInfo")
            if (
                self.initialized
                or not isinstance(params.get("protocolVersion"), str)
                or (
                    not isinstance(params.get("capabilities"), dict)
                    or not isinstance(client, dict)
                    or not isinstance(client.get("name"), str)
                    or not isinstance(client.get("version"), str)
                )
            ):
                return error(-32602, "One protocol initialization required")
            self.initialized = True
            version = params["protocolVersion"]
            result: dict[str, Any] = {
                "protocolVersion": version if version in PROTOCOLS else "2025-11-25",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "qtrades-research-observer", "version": "1.0.0"},
                "instructions": INSTRUCTIONS,
            }
        elif method == "ping":
            result = {}
        elif method not in {"tools/list", "tools/call"}:
            return error(-32601, "Method not found")
        elif not self.ready:
            return error(-32600, "Initialize and notify initialized before tool use")
        elif method == "tools/list":
            # Request metadata does not paginate or route the fixed catalog.
            # Accept null cursor as absent for compatibility; real cursors fail.
            if (
                set(params) - {"cursor", "_meta"}
                or params.get("cursor") is not None
                or "_meta" in params
                and not isinstance(params["_meta"], dict)
            ):
                return error(-32602, "Fixed tool list requires no cursor and object metadata")
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": description,
                        "inputSchema": model.model_json_schema(),
                        "annotations": {
                            "readOnlyHint": name not in WRITE_TOOLS,
                            "idempotentHint": True,
                            "destructiveHint": False,
                            "openWorldHint": False,
                        },
                    }
                    for name, (model, _, description) in TOOLS.items()
                ]
            }
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments", {})
            if (
                set(params) - {"name", "arguments", "_meta"}
                or not isinstance(name, str)
                or (name not in TOOLS or not isinstance(args, dict))
            ):
                return error(-32602, "Unknown tool or invalid arguments")
            try:
                TOOLS[name][0].model_validate(args)
            except ValidationError:
                return error(-32602, "Arguments do not match the strict tool schema")
            try:
                value = self.observe(name, args)
                text = json.dumps(value, ensure_ascii=False, allow_nan=False)
                operation = value.get("operation", {})
                result = {
                    "content": [{"type": "text", "text": text}],
                    "isError": name in WRITE_TOOLS
                    and (
                        operation.get("committed") is not True
                        or name == "research_run_diagnostic"
                        and (
                            operation.get("diagnostic_succeeded") is not True
                            or value.get("observed", {}).get("result_projection_available")
                            is not True
                        )
                    ),
                }
                wire = {"jsonrpc": "2.0", "id": identity, "result": result}
                if name in WRITE_TOOLS and (
                    len(json.dumps(result).encode()) > OUTPUT_BYTES - 256
                    or len(json.dumps(wire, ensure_ascii=False).encode()) + 1 > OUTPUT_BYTES
                ):
                    # Acknowledged writes retain their exact receipt/control identity
                    # even when escaped facts do not fit the complete MCP envelope.
                    observed = value.get("observed")
                    if isinstance(observed, dict):
                        value["observed"] = fields(
                            observed,
                            "id status tool symbol actor account request_id result_sha256 "
                            "enabled paper_pilot experimental execution_mode contract",
                        )
                        if name == "research_run_diagnostic":
                            value["observed"]["result_projection_available"] = False
                            value["observed"]["result"] = None
                        else:
                            value["observed"] = {
                                "readiness": fields(observed.get("readiness"), "configured_enabled")
                            }
                    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
                    result = {"content": [{"type": "text", "text": text}], "isError": True}
                if len(json.dumps(result).encode()) > OUTPUT_BYTES - 256:
                    raise ValueError("Projected result exceeds its output bound")
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                RecursionError,
                httpx.HTTPError,
            ) as exc:
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "state": "unavailable",
                                    "error_type": type(exc).__name__,
                                    "http_status": exc.response.status_code
                                    if isinstance(exc, httpx.HTTPStatusError)
                                    else None,
                                    "reason": "Observation failed; result remains unavailable",
                                }
                            ),
                        }
                    ],
                    "isError": True,
                }
        else:
            return error(-32601, "Method not found")
        return {"jsonrpc": "2.0", "id": identity, "result": result}


def serve(observer: Observer, source: BinaryIO, destination: BinaryIO) -> int:
    while raw := source.readline(LINE_BYTES + 1):
        if len(raw) > LINE_BYTES:
            destination.write(
                b'{"jsonrpc":"2.0","id":null,"error":'
                b'{"code":-32700,"message":"Input line exceeds its bound"}}\n'
            )
            destination.flush()
            return 1  # Do not drain an unbounded hostile line or lose framing.
        try:
            body = decode(raw)
            response = observer.rpc(body)
        except (ValueError, UnicodeError, RecursionError):
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Invalid JSON message"},
            }
        if response is not None:
            encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode()
            if len(encoded) + 1 > OUTPUT_BYTES:
                response = {
                    "jsonrpc": "2.0",
                    "id": response.get("id"),
                    "error": {"code": -32603, "message": "Response exceeds its output allowance"},
                }
                encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode()
                if len(encoded) + 1 > OUTPUT_BYTES:
                    response["id"] = None
                    encoded = json.dumps(response, allow_nan=False).encode()
            destination.write(encoded + b"\n")
            destination.flush()
    return 0


def main() -> None:
    # Client lifetime belongs to Codex's stdio process; no app/registry/model is constructed.
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        raise SystemExit(serve(Observer(client), sys.stdin.buffer, sys.stdout.buffer))


if __name__ == "__main__":
    main()
