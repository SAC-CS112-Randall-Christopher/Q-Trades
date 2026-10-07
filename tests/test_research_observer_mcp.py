"""Offline wire/HTTP fixtures; no app owner, operating service or model is created."""

import copy
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from trading.research_observer_mcp import (
    HTTP_BYTES,
    LINE_BYTES,
    ORIGIN,
    OUTPUT_BYTES,
    TOOLS,
    Observer,
    digest,
    scientific,
    serve,
)

TASK = "role-" + "a" * 32
HEALTH = {
    "mode": "paper",
    "service": "running",
    "code_commit": "b" * 40,
    "paper_fresh": True,
    "journal_balanced": True,
    "paper_error_reported": False,
}


def saved_task(status="waiting", stage="tool_wait"):
    answer = {
        "action": "request_tool",
        "mechanism": "Compare causal volatility regimes",
        "rationale": "The current supplied inputs do not establish a regime effect",
        "falsification": "Reject if matched after-cost outcomes agree",
        "evidence_ids": ["e2"],
        "unsupported_basis": None,
        "tool_request": {
            "kind": "analysis_tool",
            "identifier": "regime_comparison",
            "purpose": "Compare frozen regimes after executable costs",
            "required_inputs": ["Causal bars"],
            "acceptance_checks": ["Retain negative and inconclusive outcomes"],
            "private_secret": "DO_NOT_DISCLOSE",
        },
    }
    return {
        "id": TASK,
        "stage": stage,
        "status": status,
        "reason": "Retained original scientific result",
        "created": 1,
        "execution": {"kind": "unclaimed", "lease_until": None, "secret": "PRIVATE"},
        "contract_applicability": {
            "state": "different",
            "recorded_contract": "v5",
            "selected_contract": "v6",
        },
        "context": {
            "contract": "v6",
            "question": {"question": "Test the causal mechanism", "horizon": "short"},
            "execution_mode": "paper_research_pilot",
            "pilot_grant_id": "grant-v6",
            "catalog": {
                "r1": {
                    "kind": "independent",
                    "strategy": {"family": "range_reversion", "lookback": 10},
                }
            },
            "tool_evidence": {
                "closed_bar_sha256": "c" * 64,
                "source_basis": "observed_public_market",
                "features": {"r1": {"eligible": False, "atr": "1.2", "volume_ratio": "0.5"}},
            },
            "wait_requirements": {
                "new_closed_bars": {"kind": "closed_bars", "source_sha256": "c" * 64}
            },
            "training": {"heldout": "SEALED"},
            "issued": {"sha256": "d" * 64},
        },
        "proposal": None,
        "evaluation": {
            "status": "supported_exploratory_configuration",
            "input_sha256": "e" * 64,
            "input_count": 305,
            "inputs": "RAW_PRIVATE_INPUTS",
        },
        "result": answer,
        "attempts": [
            {
                "stage": "idea",
                "attempt": 1,
                "started": 2,
                "finished": 3,
                "status": "answered",
                "profile": {"private_directory": "PRIVATE"},
                "packet": "PRIVATE_PACKET",
                "response": {
                    "complete": True,
                    "answer": answer,
                    "raw_text": "PRIVATE_RUNNER_OUTPUT",
                },
            }
        ],
    }


def status():
    return {
        "enabled": True,
        "execution_mode": "paper_research_pilot",
        "contract": "v6",
        "current_task": None,
        "tasks": [
            {
                "id": TASK,
                "question": "Recorded question",
                "stage": "tool_wait",
                "private": "PRIVATE",
            }
        ],
        "activity": {"state": "waiting", "pending_tools": 1, "queued": 0},
        "history": {"retained": 1, "active": 1},
        "readiness": {
            "ready": True,
            "qualified": False,
            "qualification_valid": False,
            "configured_enabled": True,
            "grant_id": "grant-v6",
            "profile": {"private_directory": "PRIVATE"},
            "reason": "G:\\private\\raw\\file.json",
            "operating_admission": {"state": "available"},
        },
    }


def initialized(observer):
    result = observer.rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "offline-test", "version": "1"},
            },
        }
    )
    assert result["result"]["protocolVersion"] == "2025-11-25"
    assert observer.rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    return observer


def invoke(observer, name, args=None):
    return observer.rpc(
        {
            "jsonrpc": "2.0",
            "id": "request-1",
            "method": "tools/call",
            "params": {"name": name, "arguments": args or {}},
        }
    )


def observer_for(body, response=None):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert str(request.url).startswith(ORIGIN + "/api/")
        assert "authorization" not in request.headers and "x-local-operator" not in request.headers
        if request.url.path == "/api/health":
            return httpx.Response(200, json=HEALTH)
        return response(request) if response else httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    return initialized(Observer(client)), calls, client


@pytest.mark.parametrize(
    "params",
    [
        None,
        {},
        {"cursor": None},
        {"_meta": {}},
        {"_meta": {"progressToken": "catalog-1"}},
        {"cursor": None, "_meta": {"progressToken": 2}},
    ],
    ids=[
        "absent",
        "empty",
        "null-cursor-compatibility",
        "empty-metadata",
        "metadata",
        "metadata-and-null-cursor-compatibility",
    ],
)
def test_wire_initialize_discovery_notifications_and_eof_have_no_http(params):
    client = httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected GET")))
    observer = Observer(client)
    messages = [
        {"jsonrpc": "2.0", "id": 0, "method": "ping"},
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "fixture", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "research_status"}},
    ]
    if params is not None:
        messages[3]["params"] = params
    destination = io.BytesIO()
    assert (
        serve(
            observer,
            io.BytesIO(b"\n".join(json.dumps(v).encode() for v in messages) + b"\n"),
            destination,
        )
        == 0
    )
    rows = [json.loads(v) for v in destination.getvalue().splitlines()]
    assert len(rows) == 3 and rows[1]["result"]["protocolVersion"] == "2025-03-26"
    tools = rows[2]["result"]["tools"]
    assert [v["name"] for v in tools] == list(TOOLS)
    assert all(v["inputSchema"]["additionalProperties"] is False for v in tools)
    for tool in tools:
        assert tool["annotations"]["readOnlyHint"] is (
            tool["name"] not in {"research_run_diagnostic", "research_pause"}
        )
        assert tool["annotations"]["idempotentHint"] is True
    client.close()


@pytest.mark.parametrize(
    "params",
    [
        {"cursor": ""},
        {"cursor": "unknown-cursor"},
        {"cursor": False},
        {"cursor": 0},
        {"cursor": []},
        {"cursor": {}},
        {"_meta": None},
        {"_meta": []},
        {"_meta": "value"},
        {"_meta": False},
        {"unknown": None},
        {"cursor": None, "unknown": "value"},
        {"cursor": None, "_meta": None},
        {"_meta": {}, "cursor": "unknown-cursor"},
    ],
)
def test_fixed_catalog_rejects_real_cursor_unknown_fields_and_malformed_metadata(params):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected GET"))
    ) as client:
        observer = initialized(Observer(client))
        response = observer.rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": params}
        )
    assert response["error"]["code"] == -32602
    assert "result" not in response


def test_status_waiting_and_readiness_remain_distinct_with_private_values_omitted():
    observer, calls, client = observer_for(status())
    response = invoke(observer, "research_status", {"search": "negative hypothesis"})
    text = response["result"]["content"][0]["text"]
    result = json.loads(text)
    assert response["result"]["isError"] is False
    assert result["observed"]["activity"]["state"] == "waiting"
    assert result["observed"]["readiness"]["ready"] is True
    assert result["observed"]["readiness"]["qualified"] is False
    assert "PRIVATE" not in text and "private_directory" not in text and "G:" not in text
    assert len(calls) == 2 and calls[1].url.params["search"] == "negative hypothesis"
    client.close()


def selection_record():
    """Synthetic v7 record using the existing public selection metadata shape."""
    return {
        "authority": {
            "question_policy": "evidence-question-selection-v1",
            "grant_id": "synthetic-v7-grant",
            "grant_sha": "1" * 64,
            "profile_sha": "2" * 64,
            "contract_version": "reviewed-rule-role-v7",
            "contract_sha": "3" * 64,
            "private_secret": "DO_NOT_DISCLOSE",
        },
        "method": "r1",
        "horizon": "short",
        "scope_sha": "4" * 64,
        "selection_sha": "5" * 64,
        "source_sha": "6" * 64,
        "source_start": 1_800_000_000.0,
        "source_end": 1_800_025_199.999,
        "source_count": 420,
        "source_basis": "synthetic_fixture",
        "strategy_sha": "7" * 64,
        "reference_sha": "8" * 64,
        "prior_selection": None,
        "lesson": {"id": "lesson-" + "9" * 32, "sha256": "a" * 64},
        "excursion_bps": 140.0,
        "modeled_hurdle_bps": 125.0,
        "reason": "A causal entry prerequisite; not observed profit",
        "falsification": "Reject benefit without positive mature matched after-cost evidence",
        "limitations": ["Correlated source block", "Operating/inference costs remain unmeasured"],
        "raw_archive": "DO_NOT_DISCLOSE",
    }


def v7_task():
    from trading.autonomous_spec import RuleSpec
    from trading.experiment_registry import fingerprint

    body = saved_task()
    body["context"]["contract"] = "reviewed-rule-role-v7"
    body["context"]["question_selection"] = selection_record()
    body["context"]["selection_authority"] = selection_record()["authority"]
    strategy = RuleSpec(family="range_reversion").model_dump()
    reference = RuleSpec().model_dump()
    body["context"]["catalog"]["r1"] = {
        "kind": "independent",
        "strategy": strategy,
        "reference": reference,
        "strategy_sha256": fingerprint(strategy),
        "reference_sha256": fingerprint(reference),
    }
    return body


@pytest.mark.parametrize("state", ["selected", "waiting", "unavailable", "disabled"])
def test_selection_status_retains_actual_state_without_quality_or_authority_inference(state):
    body = status()
    body["contract"] = "reviewed-rule-role-v7"
    body["question_selection"] = {
        "policy": "evidence-question-selection-v1",
        "state": state,
        "reason": "Recorded source/clock wait; no dispatched model",
        "experimental": True,
        "task": TASK if state == "selected" else None,
        "evidence": selection_record() if state == "selected" else None,
        "private_secret": "DO_NOT_DISCLOSE",
    }
    original = copy.deepcopy(body)
    observer, calls, client = observer_for(body)
    try:
        result = invoke(observer, "research_status")["result"]
        text = result["content"][0]["text"]
        observed = json.loads(text)["observed"]
        selected = observed["question_selection"]
        assert result["isError"] is False and selected["state"] == state
        assert selected["reason"] == body["question_selection"]["reason"]
        assert observed["readiness"]["qualified"] is False
        if state == "selected":
            assert len(selected["evidence"]["authority"]) == 6
            assert selected["evidence"]["source_basis"] == "synthetic_fixture"
        else:
            assert selected["evidence"] is None
        assert "DO_NOT_DISCLOSE" not in text and body == original
        assert len(calls) == 2 and all(request.method == "GET" for request in calls)
    finally:
        client.close()


def test_v7_recorded_selection_and_verified_frozen_controls_preserve_original_result():
    body = v7_task()
    original = copy.deepcopy(body)
    observer, _, client = observer_for(body)
    try:
        result = invoke(observer, "research_task", {"task_id": TASK})["result"]
        text = result["content"][0]["text"]
        observed = json.loads(text)["observed"]
        assert result["isError"] is False
        authority = observed["context"]["selection_authority"]
        assert len(authority) == 6
        assert authority == observed["context"]["question_selection"]["authority"]
        selected = observed["context"]["question_selection"]
        for key in ("scope_sha", "source_sha", "selection_sha", "limitations", "lesson"):
            assert selected[key] == original["context"]["question_selection"][key]
        comparison = observed["context"]["catalog"]["r1"]["fixed_comparison"]
        assert comparison["basis"] == "recorded_catalog"
        for arm in ("strategy", "reference"):
            assert comparison[arm + "_sha256"] == body["context"]["catalog"]["r1"][arm + "_sha256"]
            assert comparison[arm]["volume_multiple"] == "2"
            assert len(comparison[arm]) == 6
        assert observed["context"]["contract"] == "reviewed-rule-role-v7"
        assert observed["contract_applicability"]["state"] == "different"
        assert observed["result"]["action"] == original["result"]["action"]
        assert observed["attempts"][0]["response_sha256"] == digest(
            original["attempts"][0]["response"]
        )
        assert observed["recorded_context_sha256"] == digest(original["context"])
        assert "DO_NOT_DISCLOSE" not in text and body == original
    finally:
        client.close()


@pytest.mark.parametrize(
    "damage",
    [
        "missing_authority",
        "invalid_authority_sha",
        "wrong_source_count",
        "excess_limitations",
        "changed_comparison",
        "missing_control",
    ],
)
def test_invalid_selection_metadata_or_comparison_never_becomes_observed_success(damage):
    from trading.experiment_registry import fingerprint

    body = v7_task()
    selection = body["context"]["question_selection"]
    comparison = body["context"]["catalog"]["r1"]
    if damage == "missing_authority":
        del selection["authority"]["grant_sha"]
    elif damage == "invalid_authority_sha":
        selection["authority"]["grant_sha"] = "invalid"
    elif damage == "wrong_source_count":
        selection["source_count"] = True
    elif damage == "excess_limitations":
        selection["limitations"] = ["Bounded"] * 9
    elif damage == "changed_comparison":
        comparison["strategy"]["volume_multiple"] = 2.0
    else:
        del comparison["strategy"]["input_version"]
        comparison["strategy_sha256"] = fingerprint(comparison["strategy"])
    observer, _, client = observer_for(body)
    try:
        assert invoke(observer, "research_task", {"task_id": TASK})["result"]["isError"] is True
    finally:
        client.close()


def test_legacy_records_have_no_inferred_selection_or_fixed_controls():
    observer, _, client = observer_for(saved_task())
    try:
        result = invoke(observer, "research_task", {"task_id": TASK})["result"]
        context = json.loads(result["content"][0]["text"])["observed"]["context"]
        assert result["isError"] is False
        assert "question_selection" not in context and "selection_authority" not in context
        assert "fixed_comparison" not in context["catalog"]["r1"]
    finally:
        client.close()


def diagnostic_command(tool="cost_hurdle"):
    return {
        "tool": tool,
        "symbol": "BTCUSD",
        "account": "primary",
        "start": 0.0,
        "request_id": "synthetic-diagnostic-0001",
    }


def diagnostic_receipt(command, *, failed=False):
    result = (
        None
        if failed
        else {
            "tool": command["tool"],
            "version": "scoped-research-tools-v3",
            "result": {
                "reason": "Synthetic evidence; no strategy-quality claim",
                "fees_usd": "0.01",
                "private_secret": "DO_NOT_DISCLOSE",
            },
        }
    )
    return {
        "id": 12,
        "started": 1,
        "finished": 2,
        "status": "failed" if failed else "completed",
        "actor": "local_operator",
        "tool": command["tool"],
        "symbol": command["symbol"],
        "account": command["account"],
        "version": "scoped-research-tools-v3",
        "request_id": command["request_id"],
        "query": json.dumps({k: v for k, v in command.items() if k != "request_id"}),
        "result": result,
        "result_sha256": digest(result) if result is not None else None,
        "error": "Synthetic missing input" if failed else None,
        "private_owner": "DO_NOT_DISCLOSE",
    }


def operator_observer(handler):
    calls = []

    def transport(request):
        calls.append(request)
        assert str(request.url).startswith(ORIGIN + "/api/")
        if request.url.path == "/api/health":
            assert request.method == "GET" and "x-local-operator" not in request.headers
            return httpx.Response(200, json=HEALTH)
        if request.method == "POST":
            assert request.headers["x-local-operator"] == "1"
            assert request.url.path in {"/api/research/tools/run", "/api/lab/roles/control"}
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(transport), trust_env=False)
    return initialized(Observer(client)), calls, client


@pytest.mark.parametrize(
    "tool",
    [
        "input_diagnosis",
        "cost_diagnosis",
        "market_evidence",
        "cost_hurdle",
        "strategy_evidence",
        "outcome_review",
    ],
)
def test_all_six_operator_diagnostics_use_exact_scope_once_and_keep_saved_identity(tool):
    command = diagnostic_command(tool)
    original = diagnostic_receipt(command)

    def handler(request):
        assert request.method == "POST" and json.loads(request.content) == command
        return httpx.Response(200, json=original)

    observer, calls, client = operator_observer(handler)
    try:
        result = invoke(observer, "research_run_diagnostic", command)["result"]
        text = result["content"][0]["text"]
        saved = json.loads(text)
        assert result["isError"] is False
        assert saved["operation"]["committed"] is True
        assert saved["operation"]["automatic_retry"] is False
        assert saved["operation"]["run_id"] == 12
        assert saved["observed"]["request_id"] == command["request_id"]
        assert saved["observed"]["result_sha256"] == original["result_sha256"]
        assert saved["observed_payload_sha256"] == digest(original)
        assert saved["observed"]["result"]["result"]["fees_usd"] == "0.01"
        assert "DO_NOT_DISCLOSE" not in text
        assert sum(request.method == "POST" for request in calls) == 1
    finally:
        client.close()


def test_failed_diagnostic_receipt_is_committed_but_does_not_become_success():
    command = diagnostic_command()
    receipt = diagnostic_receipt(command, failed=True)
    observer, calls, client = operator_observer(lambda request: httpx.Response(200, json=receipt))
    try:
        result = invoke(observer, "research_run_diagnostic", command)["result"]
        saved = json.loads(result["content"][0]["text"])
        assert result["isError"] is True and saved["operation"]["committed"] is True
        assert saved["operation"]["diagnostic_succeeded"] is False
        assert saved["observed"]["status"] == "failed" and saved["observed"]["id"] == 12
        assert saved["observed"]["error"] == receipt["error"]
        assert len(calls) == 2
    finally:
        client.close()


@pytest.mark.parametrize("status,expected", [(403, "refused"), (429, "refused"), (503, "unknown")])
def test_operator_http_failures_preserve_uncertain_commit_without_retries_or_private_text(
    status, expected
):
    observer, calls, client = operator_observer(
        lambda request: httpx.Response(status, json={"detail": "PRIVATE_DRIVER_SECRET"})
    )
    try:
        result = invoke(observer, "research_run_diagnostic", diagnostic_command())["result"]
        text = result["content"][0]["text"]
        saved = json.loads(text)
        assert result["isError"] is True and saved["operation"]["state"] == expected
        assert saved["operation"]["committed"] is (False if expected == "refused" else None)
        assert "PRIVATE_DRIVER_SECRET" not in text
        assert sum(request.method == "POST" for request in calls) == 1
    finally:
        client.close()


def test_lost_ack_is_reconciled_by_exact_get_and_explicit_repeated_id_creates_no_new_receipt(
    tmp_path,
):
    from trading.tool_journal import ToolJournal

    command = diagnostic_command()
    journal = ToolJournal(tmp_path / "synthetic-tools.sqlite3")
    lose_ack = True

    def handler(request):
        nonlocal lose_ack
        if request.method == "POST":
            values = json.loads(request.content)
            query = {key: value for key, value in values.items() if key != "request_id"}
            run_id = journal.start(
                values["tool"],
                values["symbol"],
                account=values["account"],
                request_id=values["request_id"],
                query=query,
            )
            old = journal.get(run_id)
            if old["status"] == "running":
                journal.finish(
                    run_id, {"tool": values["tool"], "result": {"reason": "Synthetic"}}, None
                )
            if lose_ack:
                lose_ack = False
                raise httpx.ReadTimeout("PRIVATE_RESPONSE_SECRET", request=request)
            return httpx.Response(200, json=journal.get(run_id))
        assert request.method == "GET" and request.url.path == "/api/research/tools/runs/1"
        assert not request.url.params and "x-local-operator" not in request.headers
        return httpx.Response(200, json=journal.get(1))

    observer, calls, client = operator_observer(handler)
    try:
        uncertain = invoke(observer, "research_run_diagnostic", command)["result"]
        value = json.loads(uncertain["content"][0]["text"])
        assert uncertain["isError"] is True and value["operation"]["committed"] is None
        assert value["operation"]["request"]["request_id"] == command["request_id"]
        assert "run_id" not in value["operation"]
        assert sum(request.method == "POST" for request in calls) == 1
        # The fixture's existing history owner reveals the saved ID; the client
        # never guesses an ID from a timeout or automatically repeats the POST.
        original = journal.get(journal.recent()["runs"][0]["id"])
        read = invoke(observer, "research_diagnostic_result", {"run_id": original["id"]})["result"]
        assert read["isError"] is False
        assert (
            json.loads(read["content"][0]["text"])["observed"]["result_sha256"]
            == original["result_sha256"]
        )
        repeated = invoke(observer, "research_run_diagnostic", command)["result"]
        assert repeated["isError"] is False
        assert journal.recent()["total"] == 1 and journal.get(1) == original
        assert sum(request.method == "POST" for request in calls) == 2
    finally:
        client.close()
        journal.close()


def test_pause_is_fixed_operator_action_with_unknown_cleanup_and_no_resume():
    body = status()
    body["enabled"] = False
    body["readiness"]["configured_enabled"] = False

    def handler(request):
        assert request.method == "POST" and json.loads(request.content) == {"action": "pause"}
        return httpx.Response(200, json=body)

    observer, calls, client = operator_observer(handler)
    try:
        result = invoke(observer, "research_pause")["result"]
        saved = json.loads(result["content"][0]["text"])
        assert result["isError"] is False and saved["operation"]["state"] == "paused"
        assert saved["operation"]["child_cleanup_verified"] is None
        assert saved["observed"]["readiness"]["qualified"] is False
        assert sum(request.method == "POST" for request in calls) == 1
        refused = invoke(observer, "research_pause", {"action": "resume"})
        assert refused["error"]["code"] == -32602 and len(calls) == 2
    finally:
        client.close()


@pytest.mark.parametrize(
    "change",
    [
        "missing_account",
        "missing_start",
        "missing_request_id",
        "bad_tool",
        "boolean_start",
        "path_account",
        "extra_url",
    ],
)
def test_operator_scope_is_strict_before_any_http(change):
    command = diagnostic_command()
    if change.startswith("missing_"):
        del command[change.removeprefix("missing_")]
    elif change == "bad_tool":
        command["tool"] = "place_order"
    elif change == "boolean_start":
        command["start"] = True
    elif change == "path_account":
        command["account"] = "../primary"
    else:
        command["url"] = "https://fixture.invalid"
    observer, calls, client = operator_observer(lambda request: pytest.fail("No HTTP permitted"))
    try:
        assert invoke(observer, "research_run_diagnostic", command)["error"]["code"] == -32602
        assert calls == []
    finally:
        client.close()


def test_escaped_full_wire_omits_facts_but_retains_one_acknowledged_receipt():
    command = diagnostic_command()
    receipt = diagnostic_receipt(command)
    receipt["result"]["result"]["reason"] = '\\"' * 18000
    receipt["result_sha256"] = digest(receipt["result"])
    assert len(json.dumps(receipt).encode()) < HTTP_BYTES
    observer, calls, client = operator_observer(lambda request: httpx.Response(200, json=receipt))
    request = {
        "jsonrpc": "2.0",
        "id": int("7" * 4000),
        "method": "tools/call",
        "params": {"name": "research_run_diagnostic", "arguments": command},
    }
    try:
        output = io.BytesIO()
        assert serve(observer, io.BytesIO(json.dumps(request).encode() + b"\n"), output) == 0
        assert len(output.getvalue()) <= OUTPUT_BYTES
        result = json.loads(output.getvalue())["result"]
        saved = json.loads(result["content"][0]["text"])
        assert result["isError"] is True
        assert saved["operation"]["committed"] is True and saved["operation"]["run_id"] == 12
        assert saved["observed"]["id"] == 12
        assert saved["observed"]["result_sha256"] == receipt["result_sha256"]
        assert saved["observed_payload_sha256"] == digest(receipt)
        assert saved["observed"]["result"] is None
        assert saved["observed"]["result_projection_available"] is False
        assert sum(call.method == "POST" for call in calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("failure", ["query", "checksum", "run_id"])
def test_mismatched_receipts_cannot_be_accepted_or_replaced_by_live_data(failure):
    command = diagnostic_command()
    receipt = diagnostic_receipt(command)
    if failure == "query":
        receipt["query"] = json.dumps({**command, "account": "unrelated"})
    elif failure == "checksum":
        receipt["result_sha256"] = "0" * 64
    else:
        receipt["id"] = 13
    observer, calls, client = operator_observer(lambda request: httpx.Response(200, json=receipt))
    try:
        name = "research_diagnostic_result" if failure == "run_id" else "research_run_diagnostic"
        values = {"run_id": 12} if failure == "run_id" else command
        result = invoke(observer, name, values)["result"]
        saved = json.loads(result["content"][0]["text"])
        assert result["isError"] is True
        if failure != "run_id":
            assert saved["operation"]["committed"] is None
            assert sum(call.method == "POST" for call in calls) == 1
        else:
            assert saved["state"] == "unavailable" and all(call.method == "GET" for call in calls)
    finally:
        client.close()


def test_pause_uncertain_ack_requires_status_read_and_does_not_retry():
    body = status()
    body["enabled"] = False
    body["readiness"]["configured_enabled"] = False

    def handler(request):
        if request.method == "POST":
            return httpx.Response(503, json={"detail": "Saved; current status unavailable"})
        assert request.url.path == "/api/lab/roles"
        return httpx.Response(200, json=body)

    observer, calls, client = operator_observer(handler)
    try:
        uncertain = invoke(observer, "research_pause")["result"]
        saved = json.loads(uncertain["content"][0]["text"])
        assert uncertain["isError"] is True and saved["operation"]["committed"] is None
        later = invoke(observer, "research_status")["result"]
        assert json.loads(later["content"][0]["text"])["observed"]["enabled"] is False
        assert sum(call.method == "POST" for call in calls) == 1
        assert saved["operation"]["child_cleanup_verified"] is None
    finally:
        client.close()


def test_small_transport_chunks_cannot_extend_operator_deadline(monkeypatch):
    import trading.research_observer_mcp as route

    clock = [0.0]
    monkeypatch.setattr(route, "time", SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 0))

    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in (b"{", b'"', b"x", b'"', b":", b"0", b"}"):
                clock[0] += 3
                yield chunk

    observer, calls, client = operator_observer(
        lambda request: httpx.Response(200, stream=Trickle())
    )
    try:
        result = invoke(observer, "research_run_diagnostic", diagnostic_command())["result"]
        saved = json.loads(result["content"][0]["text"])
        assert result["isError"] is True and saved["operation"]["committed"] is None
        assert clock[0] == 12 and sum(call.method == "POST" for call in calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("tool", ["cost_diagnosis", "input_diagnosis", "cost_hurdle"])
def test_real_diagnostic_builders_preserve_costs_coverage_and_explicit_unknowns(tool):
    from test_paper_runtime import instrument

    from trading.station import cost_hurdle
    from trading.strategy_diagnosis import cost_diagnosis, input_row

    command = diagnostic_command(tool)
    if tool == "cost_diagnosis":
        original = cost_diagnosis(
            {
                "account": "primary",
                "symbol": "BTCUSD",
                "interval": {"start": 1, "end": 2},
                "market_totals": {"trades": 3, "net_pnl": "-0.04", "fees": "0.10"},
                "account_totals": {"cash": "99.96", "net_pnl": None, "fresh": False},
                "open_holdings": {"BTCUSD": {"quantity": "0.1", "cost": "10"}},
                "pending_orders": {},
                "events": [],
                "has_more": True,
            }
        )
    elif tool == "input_diagnosis":
        row = input_row(
            {
                "at": 1000,
                "state_before": {
                    "accounts": {
                        "primary": {
                            "version": "breakout-v1",
                            "last_decision": {},
                            "execution_profile": "legacy",
                        }
                    }
                },
                "input_eligibility": {
                    "markets": {
                        "BTCUSD": {
                            "frame_present": False,
                            "reason": "no_fresh_book",
                        }
                    }
                },
                "candle_input_status": {"BTCUSD": {"continuous": False}},
            },
            "capture-v2:synthetic:1:" + "f" * 64,
            "BTCUSD",
            "primary",
            None,
        )
        original = {
            "diagnosis": "input_coverage",
            "status": "available",
            "population": {"retained_samples_inspected": 1, "total_engine_ticks": None},
            "rows": [row],
            "problem_counts": {problem: 1 for problem in row["problems"]},
            "facts": ["Synthetic original input sample"],
            "unresolved": ["Sparse retention cannot prove continuous coverage or fills"],
            "next_question": "Which recorded input boundary prevents this comparison?",
        }
    else:
        runtime = SimpleNamespace(
            quotes=lambda: {
                "markets": [
                    {
                        "symbol": "BTCUSD",
                        "state": "fresh",
                        "bid": "100",
                        "ask": "100.10",
                        "source": "binance.us-rest-fallback",
                    }
                ]
            },
            _fallback={},
            stream=SimpleNamespace(stats={}, trade_tape={}),
            metadata_at=time.time(),
            instruments={"BTCUSD": instrument("BTC")},
            state={"accounts": {"primary": {"positions": {}}}, "paused": False},
        )
        original = cost_hurdle(runtime, "BTCUSD")
    receipt = diagnostic_receipt(command)
    receipt["result"]["result"] = original
    receipt["result_sha256"] = digest(receipt["result"])
    observer, calls, client = operator_observer(lambda request: httpx.Response(200, json=receipt))
    try:
        result = invoke(observer, "research_run_diagnostic", command)["result"]
        saved = json.loads(result["content"][0]["text"])
        assert (
            result["isError"] is False and saved["observed"]["result_projection_available"] is True
        )
        facts = saved["observed"]["result"]["result"]
        if tool == "cost_diagnosis":
            assert facts["measured"]["gross_before_recorded_fees_usd"] == "0.06"
            assert facts["measured"]["recorded_fees_usd"] == "0.10"
            assert facts["measured"]["net_closed_pnl_usd"] == "-0.04"
            assert (
                facts["measured"]["closed_trade_cohort"]
                == original["measured"]["closed_trade_cohort"]
            )
            assert facts["measured"]["whole_account"]["net_pnl"] is None
            assert facts["measured"]["open_holdings"] == original["measured"]["open_holdings"]
            assert (
                facts["facts"] == original["facts"]
                and facts["unresolved"] == original["unresolved"]
            )
        elif tool == "input_diagnosis":
            assert facts["rows"][0]["problems"] == original["rows"][0]["problems"]
            assert facts["rows"][0]["could_evaluate"] is False
            assert (
                facts["rows"][0]["original_input_eligibility"] == row["original_input_eligibility"]
            )
            assert facts["population"]["total_engine_ticks"] is None
            assert facts["problem_counts"] == original["problem_counts"]
            assert facts["unresolved"] == original["unresolved"]
        else:
            assert facts["required_bid"] == original["required_bid"]
            assert facts["fee_per_side"] == original["fee_per_side"]
            assert facts["adverse_price_per_side"] == original["adverse_price_per_side"]
            assert facts["round_trip_loss_percent"] == original["round_trip_loss_percent"]
            assert facts["position_hurdle"] is None and facts["scope"] == original["scope"]
        assert sum(call.method == "POST" for call in calls) == 1
    finally:
        client.close()


def paper_trials_body():
    controls = {
        "family": "range_reversion",
        "lookback": 15,
        "symbol": "BTCUSD",
        "holding_horizon": "short",
        "volume_multiple": "2",
        "stop_atr": "1.5",
        "exit_seconds": 3600,
        "progress_seconds": 1200,
        "input_version": "closed-minute-bars-v1",
        "version": "reviewed-lab-rules-v2",
    }
    return {
        "enabled": True,
        "lab": {
            "phase": "waiting",
            "reason": "Synthetic resource guard",
            "entries_paused": False,
            "proposals_paused": False,
            "policy_sha256": "a" * 64,
            "initial_hypothetical_funding": "800.0000000000000000000",
            "budget": {"trials": 0, "compute_seconds": 0.0},
            "policy": {
                "slots": 20,
                "starting_cash": "100",
                "daily_operating_usd": "0",
                "holding_horizons": ["short", "medium", "long"],
            },
            "trials": {
                "synthetic-trial": {
                    "id": "synthetic-trial",
                    "status": "active",
                    "candidate": "synthetic-candidate",
                    "reference": "synthetic-reference",
                    "review_at": 14400,
                    "contract": {
                        "qualification": "Exploratory paper only",
                        "costs": {"funding_each": "100", "daily_usd": "0"},
                        "evaluation": {"seconds": 14400, "coverage": 0.9},
                        "exit": {"maximum_hold": 3600},
                        "unchanged": {"volume_multiple": "2"},
                        "proposal": {
                            "request_id": "synthetic-proposal",
                            "kind": "independent",
                            "strategy": controls,
                            "reference": controls | {"family": "breakout"},
                        },
                    },
                    "score": {
                        "outcome": "data_blocked",
                        "reason": "Missing coverage",
                        "dependence": "Shared trials and observations are correlated",
                        "qualification": "Exploratory paper result; no promotion",
                        "net_after_operating_usd": {"candidate": None, "reference": None},
                        "delta_usd": None,
                        "passive_usd": None,
                    },
                    "private_secret": "DO_NOT_DISCLOSE",
                }
            },
        },
        "slots": {"used": 8, "available": 12, "capacity": 20, "reserved": 0},
        "accounts": {
            "primary": {
                "funding": "100.0000000000000000000",
                "net_pnl": None,
                "fresh": False,
                "rule_spec": None,
            },
            "synthetic-candidate": {
                "funding": "100",
                "net_pnl": "-0.1234567890123456789",
                "rule_spec": controls,
            },
        },
        "inbox": {
            "proposals": [
                {
                    "request_id": "synthetic-proposal",
                    "status": "evaluated",
                    "reason": "Awaiting resource admission",
                    "trial_id": None,
                }
            ],
            "counts": [{"status": "evaluated", "count": 1}],
            "has_more": False,
            "next_before": None,
        },
        "last_error": None,
        "provider_required": False,
        "qualification": "No automatic incumbent/live promotion",
    }


def test_paper_trials_keeps_account_ids_fixed_controls_queue_and_data_blocked_scores():
    original = paper_trials_body()
    observer, calls, client = observer_for(original)
    try:
        result = invoke(observer, "research_paper_trials")["result"]
        text = result["content"][0]["text"]
        saved = json.loads(text)
        assert result["isError"] is False and len(calls) == 2
        assert calls[-1].url.path == "/api/autonomous" and calls[-1].method == "GET"
        assert "x-local-operator" not in calls[-1].headers
        observed = saved["observed"]
        assert observed["lab"]["phase"] == "waiting"
        assert observed["lab"]["initial_hypothetical_funding"] == "800.0000000000000000000"
        assert observed["accounts"]["primary"]["net_pnl"] is None
        assert observed["accounts"]["synthetic-candidate"]["net_pnl"] == "-0.1234567890123456789"
        trial = observed["lab"]["trials"]["synthetic-trial"]
        assert trial["score"] == original["lab"]["trials"]["synthetic-trial"]["score"]
        assert trial["contract"]["proposal"]["strategy"]["lookback"] == 15
        assert trial["contract"]["proposal"]["reference"]["family"] == "breakout"
        assert observed["inbox"] == original["inbox"]
        assert "DO_NOT_DISCLOSE" not in text and saved["observed_payload_sha256"] == digest(
            original
        )
    finally:
        client.close()


@pytest.mark.parametrize("bad", ["accounts", "proposals", "identity", "trial_proposal"])
def test_unbounded_or_malformed_paper_owner_maps_do_not_become_ready(bad):
    body = paper_trials_body()
    if bad == "accounts":
        body["accounts"] = {str(n): {} for n in range(21)}
    elif bad == "proposals":
        body["inbox"]["proposals"] = [{}] * 21
    elif bad == "identity":
        body["accounts"]["../private-file"] = {}
    else:
        body["lab"]["trials"]["synthetic-trial"]["contract"]["proposal"] = None
    observer, calls, client = observer_for(body)
    try:
        result = invoke(observer, "research_paper_trials")["result"]
        assert result["isError"] is True and len(calls) == 2
        assert json.loads(result["content"][0]["text"])["state"] == "unavailable"
    finally:
        client.close()


@pytest.mark.parametrize(
    "state,stage,complete",
    [
        ("waiting", "tool_wait", True),
        ("waiting", "data_wait", True),
        ("failed", "idea", False),
        ("done", "complete", True),
    ],
)
def test_saved_adverse_incomplete_and_historical_results_are_not_regraded(state, stage, complete):
    body = saved_task(state, stage)
    body["attempts"][0]["response"]["complete"] = complete
    if state == "failed":
        body["attempts"][0]["status"] = "failed"
        body["attempts"][0]["response"]["status"] = "answered"
        body["attempts"][0]["response"]["answer"]["action"] = "unsupported_capability"
        body["result"] = None
    observer, _, client = observer_for(body)
    result = invoke(observer, "research_task", {"task_id": TASK})["result"]
    text = result["content"][0]["text"]
    observed = json.loads(text)["observed"]
    assert result["isError"] is False and observed["status"] == state
    assert observed["stage"] == stage
    assert observed["contract_applicability"]["state"] == "different"
    assert observed["context"]["catalog"]["r1"]["strategy"]["family"] == "range_reversion"
    assert observed["context"]["tool_evidence"]["features"]["r1"]["eligible"] is False
    assert observed["attempts"][0]["complete"] is complete
    assert observed["attempts"][0]["status"] == ("failed" if state == "failed" else "answered")
    assert observed["attempts"][0]["response_sha256"] == digest(body["attempts"][0]["response"])
    assert all(v not in text for v in ("PRIVATE", "SEALED", "RAW_PRIVATE", "private_secret"))
    assert observed["evaluation"]["input_sha256"] == "e" * 64
    assert "inputs" not in observed["evaluation"]
    client.close()


def test_knowledge_backed_answer_is_not_disclosed_by_ordinary_role_read_scope():
    body = saved_task()
    body["context"]["knowledge"] = {"passages": "PRIVATE_LIBRARY"}
    observer, _, client = observer_for(body)
    response = invoke(observer, "research_task", {"task_id": TASK})["result"]
    assert response["isError"] is True and "PRIVATE_LIBRARY" not in json.dumps(response)
    client.close()


@pytest.mark.parametrize(
    "name,args",
    [
        ("execute_sql", {}),
        ("research_status", {"origin": "x"}),
        ("research_status", {"before": float("inf")}),
        ("research_status", {"before": True}),
        ("research_task", {"task_id": "../api/paper/orders"}),
        ("research_task", {"task_id": "https://foreign.example"}),
        ("research_lessons", {"before": True}),
        ("research_quality", {"request": "run"}),
        ("research_capabilities", {"include_history": True}),
        ("research_capabilities", {"cursor": "next"}),
        ("research_capabilities", {"origin": "https://foreign.example"}),
    ],
)
def test_unknown_commands_and_invalid_strict_arguments_never_reach_http(name, args):
    observer, calls, client = observer_for({})
    assert invoke(observer, name, args)["error"]["code"] == -32602
    assert calls == []
    client.close()


@pytest.mark.parametrize("failure", ["unavailable", "redirect", "oversize", "malformed", "shape"])
def test_transport_and_response_failures_are_explicit_without_raw_error_leaks(failure):
    def response(request):
        if failure == "unavailable":
            raise httpx.ConnectError("G:\\private\\token.json SECRET", request=request)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://foreign.example/SECRET"})
        if failure == "oversize":
            return httpx.Response(200, content=b" " * (HTTP_BYTES + 1))
        if failure == "malformed":
            return httpx.Response(200, content=b'{"private":"SECRET",')
        return httpx.Response(200, json=[])

    observer, calls, client = observer_for({}, response)
    result = invoke(observer, "research_status")["result"]
    assert result["isError"] is True and "SECRET" not in json.dumps(result)
    assert len(calls) == 2
    client.close()


def test_identity_mismatch_and_missing_task_are_not_empty_success():
    body = saved_task()
    body["id"] = "role-" + "e" * 32
    observer, _, client = observer_for(body)
    assert invoke(observer, "research_task", {"task_id": TASK})["result"]["isError"] is True
    client.close()


def test_projected_oversize_does_not_silently_truncate_original_question():
    body = saved_task()
    body["context"]["question"]["question"] = "x" * OUTPUT_BYTES
    observer, _, client = observer_for(body)
    assert invoke(observer, "research_task", {"task_id": TASK})["result"]["isError"] is True
    client.close()


@pytest.mark.parametrize("raw", [b'{"id":1,"id":2}', b'{"x":NaN}', b"\xff", b"[]"])
def test_malformed_json_and_batch_refusal_are_framed(raw):
    observer, calls, client = observer_for({})
    output = io.BytesIO()
    assert serve(observer, io.BytesIO(raw + b"\n"), output) == 0
    assert json.loads(output.getvalue())["error"]["code"] in {-32600, -32700}
    assert calls == []
    client.close()


def test_oversize_stdio_line_stops_without_drain_or_get():
    observer, calls, client = observer_for({})
    output = io.BytesIO()
    source = io.BytesIO(b"x" * (LINE_BYTES * 2))
    assert serve(observer, source, output) == 1
    assert source.tell() == LINE_BYTES + 1 and calls == []
    assert json.loads(output.getvalue())["error"]["code"] == -32700
    client.close()


@pytest.mark.parametrize(
    "name,body",
    [
        (
            "research_lessons",
            {
                "lessons": [
                    {
                        "id": "lesson-x",
                        "claim": "Recorded inconclusive outcome",
                        "context": {"family": "breakout", "data_basis": "observed_public_market"},
                        "support": {"recorded_comparisons": 1, "independent_samples": None},
                        "private_secret": "SECRET",
                    }
                ],
                "next_before": 4,
            },
        ),
        (
            "research_quality",
            {
                "assessment": "Insufficient matched qualified-role observation",
                "attempts": 1,
                "failed_attempts": 1,
                "native_usage": {"input_tokens": None, "unknown_attempts": 1},
                "matched_research_arms": [{"arm": "B", "useful_completions": None}],
                "economic_value": {"supported": False, "net_benefit": None},
                "private_secret": "SECRET",
            },
        ),
        (
            "research_capabilities",
            {
                "history_requested": False,
                "tools": [
                    {
                        "id": "cost_hurdle",
                        "name": "Calculate cost hurdle",
                        "purpose": "Explain modeled costs",
                        "private_secret": "SECRET",
                    }
                ],
                "capabilities": {"submit": {"method": "POST", "path": "/api/autonomous/proposals"}},
            },
        ),
    ],
)
def test_all_remaining_read_routes_have_scientific_scope_and_no_execution_catalog(name, body):
    observer, calls, client = observer_for(body)
    response = invoke(observer, name)["result"]
    text = response["content"][0]["text"]
    assert response["isError"] is False and "SECRET" not in text
    assert "POST" not in text and len(calls) == 2
    if name == "research_quality":
        assert json.loads(text)["observed"]["economic_value"]["net_benefit"] is None
    if name == "research_lessons":
        assert json.loads(text)["observed"]["next_before"] == 4
    if name == "research_capabilities":
        assert json.loads(text)["observed"]["history_requested"] is False
        assert str(calls[1].url) == ORIGIN + "/api/research/tools?include_history=false"
    client.close()


@pytest.mark.parametrize(
    "marker,present,available",
    [
        (False, True, True),
        (None, False, False),
        (True, True, False),
        (0, True, False),
        ("false", True, False),
        (None, True, False),
    ],
    ids=["false", "legacy-missing", "true", "integer-zero", "string", "null"],
)
def test_catalog_only_requires_literal_false_marker_without_inferred_empty_history(
    marker, present, available
):
    body = {
        "tools": [{"id": "cost_hurdle", "name": "Calculate cost hurdle"}],
        "runs": [{"id": "legacy-history-must-not-be-disclosed"}],
        "total": 7,
        "capacity": 20,
        "next_cursor": "private-history-cursor",
    }
    if present:
        body["history_requested"] = marker
    if available:
        for key in ("runs", "total", "capacity", "next_cursor"):
            body.pop(key)
    observer, calls, client = observer_for(body)
    try:
        response = invoke(observer, "research_capabilities")["result"]
        assert str(calls[1].url) == ORIGIN + "/api/research/tools?include_history=false"
        assert len(calls) == 2 and all(request.method == "GET" for request in calls)
        text = response["content"][0]["text"]
        assert response["isError"] is not available
        assert "legacy-history-must-not-be-disclosed" not in text
        assert "private-history-cursor" not in text
        if available:
            observed = json.loads(text)["observed"]
            assert observed["history_requested"] is False
            assert set(observed) == {"authority", "history_requested", "tools"}
            assert observed["tools"] == body["tools"]
        else:
            assert json.loads(text)["state"] == "unavailable"
            assert "observed" not in json.loads(text)
    finally:
        client.close()


def test_compressed_payload_is_refused_before_decoding():
    observer, _, client = observer_for(
        {},
        lambda _: httpx.Response(
            200, headers={"content-encoding": "br"}, stream=httpx.ByteStream(b"SECRET")
        ),
    )
    assert invoke(observer, "research_status")["result"]["isError"] is True
    client.close()


def test_protocol_order_unknown_modern_probe_bad_id_and_repeat_initialize_make_no_get():
    observer, calls, client = observer_for({})
    fresh = Observer(client)
    assert fresh.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["error"]["code"] == -32600
    assert (
        fresh.rpc({"jsonrpc": "2.0", "id": 1, "method": "server/discover"})["error"]["code"]
        == -32601
    )
    assert fresh.rpc({"jsonrpc": "2.0", "id": True, "method": "ping"})["error"]["code"] == -32600
    assert fresh.rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert fresh.ready is False
    assert (
        observer.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            }
        )["error"]["code"]
        == -32602
    )
    assert calls == []
    client.close()


def test_standalone_native_process_initializes_and_lists_without_package_or_operating_calls():
    path = Path(__file__).resolve().parents[1] / "src/trading/research_observer_mcp.py"
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "offline-process", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    completed = subprocess.run(
        [sys.executable, "-I", "-u", str(path)],
        input=b"\n".join(json.dumps(v).encode() for v in messages) + b"\n",
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0 and completed.stderr == b""
    rows = [json.loads(v) for v in completed.stdout.splitlines()]
    assert len(rows) == 2 and len(rows[1]["result"]["tools"]) == 9


def test_all_frozen_idea_and_review_fields_survive_the_scientific_projection():
    from trading.lab_role_contract import Idea, IdeaV6, Review

    idea = {
        "action": "unsupported_capability",
        "capability": None,
        "evidence_ids": ["e2"],
        "mechanism": "An exact unavailable mechanism",
        "falsification": "Reject by matched data",
        "rationale": "Keep the actual adverse rationale",
        "dependency": None,
    }
    v5 = Idea.model_validate(idea).model_dump()
    assert scientific(v5) == v5
    v6 = IdeaV6.model_validate(
        idea
        | {
            "unsupported_basis": {"kind": "feature", "identifier": "new_feature"},
            "tool_request": None,
        }
    ).model_dump()
    assert scientific(v6) == v6
    review = Review.model_validate(
        {
            "action": "reject",
            "evidence_ids": ["e0"],
            "issues": ["unsupported_claim"],
            "rationale": "The exact original negative review",
        }
    ).model_dump()
    assert scientific(review) == review


def test_current_audit_unavailable_does_not_reuse_last_completed_balance(monkeypatch):
    health = HEALTH | {
        "journal_balanced": None,
        "journal_last_balanced": True,
        "journal_monitoring": {
            "available": False,
            "status": "unavailable",
            "balanced": None,
            "checked_at": 123,
            "audit_age_seconds": 9,
            "revision": 4,
            "error": "G:\\private\\audit.json SECRET",
            "projection": "PRIVATE_FINANCIAL_PAYLOAD",
        },
    }
    monkeypatch.setitem(HEALTH, "journal_balanced", health["journal_balanced"])
    monkeypatch.setitem(HEALTH, "journal_last_balanced", True)
    monkeypatch.setitem(HEALTH, "journal_monitoring", health["journal_monitoring"])
    observer, _, client = observer_for(status())
    response = invoke(observer, "research_status")["result"]
    text = response["content"][0]["text"]
    observed = json.loads(text)["paper_health"]
    assert response["isError"] is False
    assert observed["journal_balanced"] is None and observed["journal_last_balanced"] is True
    assert observed["journal_monitoring"]["available"] is False
    assert observed["journal_monitoring"]["balanced"] is None
    assert observed["journal_monitoring"]["audit_age_seconds"] == 9
    assert observed["journal_monitoring"]["error_reported"] is True
    assert "SECRET" not in text and "PRIVATE_FINANCIAL_PAYLOAD" not in text
    client.close()


@pytest.mark.parametrize("identity", ["😀" * 100, int("7" * 4000)], ids=["unicode", "integer"])
def test_complete_stdio_response_envelope_honors_output_cap_with_long_valid_ids(
    monkeypatch, identity
):
    observer, calls, client = observer_for({})
    # Near-cap valid tool result: its id/envelope must also fit the declared line allowance.
    monkeypatch.setattr(observer, "observe", lambda *_: {"value": "x" * (OUTPUT_BYTES - 400)})
    request = {
        "jsonrpc": "2.0",
        "id": identity,
        "method": "tools/call",
        "params": {"name": "research_quality", "arguments": {}},
    }
    output = io.BytesIO()
    assert serve(observer, io.BytesIO(json.dumps(request).encode() + b"\n"), output) == 0
    assert len(output.getvalue()) <= OUTPUT_BYTES
    parsed = json.loads(output.getvalue())
    assert parsed["id"] == identity and parsed["error"]["code"] == -32603
    assert calls == []
    client.close()


def test_absent_audit_error_observation_remains_unknown(monkeypatch):
    monkeypatch.setitem(HEALTH, "journal_monitoring", {"available": False})
    observer, _, client = observer_for(status())
    response = invoke(observer, "research_status")["result"]
    observed = json.loads(response["content"][0]["text"])["paper_health"]
    assert observed["journal_monitoring"]["error_reported"] is None
    client.close()
