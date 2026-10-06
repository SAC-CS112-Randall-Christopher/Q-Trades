"""Offline wire/HTTP fixtures; no app owner, operating service or model is created."""

import io
import json
import subprocess
import sys
from pathlib import Path

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


def test_wire_initialize_discovery_notifications_and_eof_have_no_http():
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
    assert all(v["annotations"]["readOnlyHint"] is True for v in tools)
    client.close()


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
    assert len(rows) == 2 and len(rows[1]["result"]["tools"]) == 5


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
