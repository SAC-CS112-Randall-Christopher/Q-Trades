"""Local, tools-only stdio observation of the existing installed research owner."""

import hashlib
import json
import math
import re
import sys
import time
from collections.abc import Mapping
from typing import Any, BinaryIO

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ORIGIN = "http://127.0.0.1:8780"
PROTOCOLS = {"2025-03-26", "2025-06-18", "2025-11-25"}
LINE_BYTES = 16384
HTTP_BYTES = 262144
OUTPUT_BYTES = 98304
INSTRUCTIONS = (
    "Read-only Q-Trades research observation. Saved answers, failures and evidence remain "
    "historical facts; readiness is a current prerequisite, not research quality. Tool/data "
    "waits require their existing owners and new evidence. No model dispatch, retries, "
    "financial commands, training, paid/external review or automatic tool installation. "
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
    result["context"]["catalog"] = {
        key: scientific(value)
        for key, value in context.get("catalog", {}).items()
        if re.fullmatch(r"r[0-9]{1,2}", key)
    }
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
        if time.monotonic() >= deadline:
            raise ValueError("Observation deadline elapsed")
        with self.client.stream(
            "GET",
            ORIGIN + path,
            params=params,
            timeout=2,
            headers={"Accept-Encoding": "identity", "Accept": "application/json"},
        ) as response:
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Compressed observation refused before decoding")
            raw = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                if time.monotonic() >= deadline or len(raw) + len(chunk) > HTTP_BYTES:
                    raise ValueError("Observation response exceeds its byte/time bound")
                raw.extend(chunk)
        body = decode(raw)
        if not isinstance(body, dict):
            raise ValueError("Observed response is not an object")
        return body

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
        identity = values.pop("task_id", "")
        body = self.get(path + identity, values, deadline)
        if name == "research_task":
            observed = task_projection(body, identity)
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
            observed = {
                "authority": "Read-only descriptions; no execution authority",
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
            if params:
                return error(-32602, "This fixed tool list has no cursor")
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": description,
                        "inputSchema": model.model_json_schema(),
                        "annotations": {
                            "readOnlyHint": True,
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
                text = json.dumps(self.observe(name, args), ensure_ascii=False, allow_nan=False)
                result = {"content": [{"type": "text", "text": text}], "isError": False}
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
