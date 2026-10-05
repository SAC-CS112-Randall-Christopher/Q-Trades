"""Predeclared disposable reference/review cases; no provider or operating data."""

import asyncio
import copy
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from test_research_storage import plan_at

from trading.api import create_app
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry
from trading.local_role_model import LocalRoles
from trading.research_actors import ActorGrant, ResearchActors
from trading.research_knowledge import (
    KnowledgeDisposition,
    KnowledgeQuery,
    ResearchKnowledge,
    SourceImport,
)
from trading.research_mcp import LocalMCPClient, ResearchMCP
from trading.research_reviews import ResearchReviews, ReviewDecision, ReviewerPolicy
from trading.research_storage import ResearchStorage, save_plan
from trading.reviewer_provider import ResponsesReviewer, ReviewerCredential
from trading.role_worker import RoleWorker

TASK = "role-" + "1" * 32
OTHER = "role-" + "2" * 32
OPERATOR = {"X-Local-Operator": "1"}


def note(identity="methods-costs", **changes):
    return SourceImport(
        source_id=identity,
        title="Costs and causal evidence",
        author="Synthetic QA author",
        origin="fixture:predeclared-methods",
        rights="Owner-authored synthetic fixture; test disclosure permitted",
        text="Transaction costs reduce gross returns. Net evidence needs fills.\n\n"
        "Contrary evidence: illiquidity and nonfills can invalidate a cost estimate.",
        external_allowed=True,
        **changes,
    )


def policy(**changes):
    return ReviewerPolicy(
        model="fixture-reviewer-exact",
        project="fixture-project",
        request_cost_ceiling_usd=0.5,
        daily_cost_ceiling_usd=1.0,
        monthly_cost_ceiling_usd=10.0,
        input_usd_per_million=1.0,
        output_usd_per_million=2.0,
        price_source="fixture:synthetic-prices-not-provider-pricing",
        **changes,
    )


def task(worker, identity=TASK):
    if worker.controller is None:
        # Procedural admission only; no real paper/resource guard is qualified here.
        worker.controller = type("FixtureGuard", (), {"can_research": lambda self: True})()
    context = {
        "question": {
            "question": "Do transaction costs undermine this evidence?",
            "horizon": "short",
        }
    }
    with worker.registry.transaction():
        worker.registry.db.execute(
            "INSERT INTO role_tasks(id,created,updated,stage,status,context) "
            "VALUES(?,?,?,'complete','complete',?)",
            (identity, time.time(), time.time(), json.dumps(context)),
        )
    # Clearly procedural CP18 packet. Actual model/numerical integration is a separate row.
    worker._base_packet = lambda t: (
        "researcher",
        {
            "question": t["context"]["question"]["question"],
            "capabilities": {},
            "evidence": {"e0": {"basis": "synthetic_qa", "fact": "Two retained nonfill cases"}},
        },
    )


@pytest.fixture
def workspace(tmp_path):
    storage = ResearchStorage(plan_at(tmp_path))
    knowledge = ResearchKnowledge(storage)
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    worker = RoleWorker(registry, None)
    task(worker)
    knowledge.ingest(note())
    reviews = ResearchReviews(worker, knowledge)
    actors = ResearchActors(worker)
    mcp = ResearchMCP(actors, reviews)
    try:
        yield knowledge, worker, reviews, actors, mcp
    finally:
        registry.close()
        storage.close()


def query(**changes):
    return KnowledgeQuery(text="transaction costs", cutoff=time.time(), **changes)


def response(run, **changes):
    body = {
        "packet_sha256": run["packet_sha"],
        "summary": "The fixture supports a transaction-cost uncertainty, not profitability.",
        "findings": [
            {
                "kind": "uncertainty",
                "claim": "Nonfills limit the estimate of costs.",
                "evidence_ids": ["e0"],
                "contrary_ids": [],
                "uncertainty": "No independent empirical performance proof exists.",
                "proposed_question": "What new nonfill evidence resolves this uncertainty?",
            }
        ],
        "coverage": "Synthetic fixture only; no actual provider or market inference.",
        "next_action": "Await independent evidence and review this annotation.",
    }
    body.update(changes)
    return {
        "id": "fixture-provider-1",
        "answer": body,
        "cost_usd": 0.001,
        "usage": {"total_tokens": 100},
    }


def dispatch(reviews, run):
    with reviews.registry.transaction():
        reviews.registry.db.execute(
            "UPDATE scheduled_reviews SET state='dispatching' WHERE id=?", (run["id"],)
        )


def test_vertical_source_retrieval_packet_review_disposition_reopen(workspace):
    knowledge, worker, reviews, _, _ = workspace
    receipt = knowledge.retrieve(query())
    assert len(receipt["passages"]) == 2
    assert any("Contrary" in p["text"] for p in receipt["passages"])
    worker.knowledge = knowledge
    saved = worker.get(TASK)
    saved["context"]["knowledge"] = receipt
    role, packet = worker._packet(saved)
    assert packet["retrieval_contract"] == "source-rag-v1"
    assert set(p["citation"] for p in receipt["passages"]) <= set(packet["evidence"])
    with pytest.raises(ValueError, match="separately qualified"):
        LocalRoles.preflight(role, packet, {})
    run = reviews.reserve(TASK, "fixture:first", policy())
    dispatch(reviews, run)
    final = reviews.retain(run["id"], response(run))
    assert final["state"] == "completed" and final["cost_actual"] == 0.001
    approved = reviews.decide(
        run["id"],
        ReviewDecision(
            expected_revision=0,
            disposition="accept_annotation",
            reason="Operator independently checked the fixture sources.",
        ),
    )
    assert len(approved["decisions"]) == 1
    before = copy.deepcopy(approved["packet"])
    knowledge.ingest(
        note(expected_revision=1).model_copy(update={"text": "Later costs correction."})
    )
    assert knowledge.read("methods-costs", 1, cutoff=time.time())["original"].startswith(
        "Transaction"
    )
    assert reviews.get(run["id"])["packet"] == before
    reopened = ResearchReviews(worker, knowledge)
    assert reopened.get(run["id"])["response"] == final["response"]
    assert knowledge.receipt(receipt["id"]) == receipt
    assert reviews.validate(run["id"])["updated"] == final["updated"]


def test_import_cas_duplicates_and_source_timestamps_are_server_owned(workspace):
    knowledge, *_ = workspace
    assert knowledge.ingest(note())["duplicate"]
    old = knowledge.read("methods-costs", 1, cutoff=time.time())
    with pytest.raises(ValueError, match="changed"):
        knowledge.ingest(
            note().model_copy(update={"text": "New data with stale expected revision."})
        )
    assert knowledge.read("methods-costs", 1, cutoff=time.time()) == old
    with pytest.raises(ValueError):
        SourceImport(**(note().model_dump() | {"received_at": 0}))


def test_historical_selection_unaffected_by_future_versions_and_statistics(workspace):
    knowledge, *_ = workspace
    cutoff = time.time()
    original = knowledge.retrieve(KnowledgeQuery(text="costs", cutoff=cutoff))
    knowledge.ingest(
        note(expected_revision=1).model_copy(update={"text": "Costs costs new version."})
    )
    for i in range(8):
        knowledge.ingest(note(f"future-costs-{i}"))
    later = knowledge.retrieve(KnowledgeQuery(text="costs", cutoff=cutoff))
    assert later["passages"] == original["passages"]
    assert later["id"] == original["id"]


@pytest.mark.parametrize("restriction", ["protected", "external_allowed", "symbol", "horizon"])
def test_eligibility_before_text_and_ranking(workspace, restriction):
    knowledge, *_ = workspace
    changes = (
        {"protected": True}
        if restriction == "protected"
        else (
            {"external_allowed": False}
            if restriction == "external_allowed"
            else {"symbol": "ETHUSD"}
            if restriction == "symbol"
            else {"horizon": "long"}
        )
    )
    item = note("restricted-note").model_copy(update=changes)
    knowledge.ingest(item)
    found = knowledge.retrieve(query(symbol="BTCUSD", horizon="short"), external=True)
    assert all(p["source"] != "restricted-note" for p in found["passages"])
    assert "restricted-note" not in json.dumps(found)


def test_disposition_is_append_only_and_exclusion_removes_retrieval(workspace):
    knowledge, *_ = workspace
    original = knowledge.read("methods-costs", 1, cutoff=time.time())
    cmd = KnowledgeDisposition(
        revision=1,
        expected_state=original["disposition"]["seq"],
        state="excluded",
        reason="Operator finds the source inappropriate.",
    )
    knowledge.disposition("methods-costs", cmd)
    assert knowledge.retrieve(query())["passages"] == []
    assert (
        knowledge.read("methods-costs", 1, cutoff=time.time(), operator=True)["original"]
        == original["original"]
    )
    with pytest.raises(ValueError, match="changed"):
        knowledge.disposition("methods-costs", cmd)
    with knowledge.connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE knowledge_sources SET original=x'00'")


def test_inert_html_and_no_credential_or_oversize_ingestion(workspace):
    knowledge, *_ = workspace
    knowledge.ingest(
        note("html-fixture").model_copy(
            update={
                "format": "html",
                "text": "<p>Costs are uncertain</p><script>steal credentials</script>",
            }
        )
    )
    found = knowledge.read("html-fixture", 1, cutoff=time.time())
    assert "steal credentials" not in found["text"] and "<script>" in found["original"]
    with pytest.raises(ValueError, match="Credential"):
        knowledge.ingest(note("secret-fixture").model_copy(update={"text": "sk-proj-" + "x" * 40}))
    with pytest.raises(ValueError, match="64 KiB"):
        knowledge.ingest(note("oversize-fixture").model_copy(update={"text": "é" * 40000}))


def test_fts_rebuild_and_coherent_backup_preserve_sources_receipts(workspace):
    knowledge, *_ = workspace
    original = knowledge.retrieve(query())
    with knowledge.connection() as db:
        db.execute("DROP TABLE knowledge_fts")
    assert knowledge.reindex()["indexed_versions"] == 1
    assert knowledge.receipt(original["id"]) == original
    backup = knowledge.backup()
    with sqlite3.connect(knowledge.storage.research / backup["backup"]) as restored:
        raw = restored.execute("SELECT original FROM knowledge_sources").fetchone()[0]
        assert raw.decode() == note().text
        assert (
            json.loads(restored.execute("SELECT body FROM knowledge_receipts").fetchone()[0])
            == original
        )


def test_quota_missing_volume_and_contention_preserve_originals(workspace, monkeypatch):
    knowledge, *_ = workspace
    before = knowledge.read("methods-costs", 1, cutoff=time.time())

    def blocked(*args, **kwargs):
        raise OSError("Declared quota reached")

    with monkeypatch.context() as m:
        m.setattr(knowledge.storage, "admission", blocked)
        with pytest.raises(OSError, match="quota"):
            knowledge.ingest(note("blocked-note"))
    assert knowledge.read("methods-costs", 1, cutoff=time.time()) == before
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: knowledge.ingest(note("contended-note")), range(4)))
    assert sum(not o["duplicate"] for o in outcomes) == 1
    with monkeypatch.context() as m:
        m.setattr(knowledge.storage, "_check_volume", blocked)
        with pytest.raises(OSError):
            knowledge.retrieve(query())


def test_crash_rollback_does_not_publish_half_a_source(workspace):
    knowledge, *_ = workspace
    with pytest.raises(RuntimeError), knowledge.write(1000) as db:
        db.execute(
            "INSERT INTO knowledge_states(source,revision,at,state,reason,actor) "
            "VALUES('methods-costs',1,?,'withdrawn','interrupted','fixture')",
            (time.time(),),
        )
        raise RuntimeError("crash before commit")
    assert knowledge.retrieve(query())["passages"]


def test_occurrence_dedup_crash_before_dispatch_can_reclaim(workspace):
    knowledge, worker, reviews, *_ = workspace
    run = reviews.reserve(TASK, "fixture:crash", policy())
    successor = ResearchReviews(worker, knowledge)
    with reviews.registry.transaction():
        reviews.registry.db.execute(
            "UPDATE scheduled_reviews SET lease_until=0 WHERE id=?", (run["id"],)
        )
    recovered = successor.reserve(TASK, "fixture:crash", policy())
    assert recovered["owner"] == successor.owner
    assert recovered["packet"] == run["packet"] and recovered["id"] == run["id"]


def test_post_dispatch_crash_is_unknown_and_cannot_be_replayed(workspace):
    knowledge, worker, reviews, *_ = workspace
    run = reviews.reserve(TASK, "fixture:unknown", policy())
    dispatch(reviews, run)
    with reviews.registry.transaction():
        reviews.registry.db.execute(
            "UPDATE scheduled_reviews SET lease_until=0 WHERE id=?", (run["id"],)
        )
    successor = ResearchReviews(worker, knowledge)
    assert successor.reserve(TASK, "fixture:unknown", policy())["state"] == "unknown"
    with pytest.raises(ValueError, match="uncertain"):
        successor.reserve(TASK, "fixture:next", policy())


def test_concurrent_review_claim_has_one_identity_and_budget(workspace):
    _, _, reviews, *_ = workspace
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: reviews.reserve(TASK, "fixture:shared", policy()), range(4))
        )
    assert len({r["id"] for r in results}) == 1
    with reviews.registry.lock:
        assert reviews.registry.db.execute(
            "SELECT count(*),sum(cost_reserved) FROM scheduled_reviews"
        ).fetchone()[:] == (1, 0.5)


def test_citation_validation_original_failure_and_lost_ack_retained(workspace):
    _, _, reviews, *_ = workspace
    run = reviews.reserve(TASK, "fixture:bad-citation", policy())
    dispatch(reviews, run)
    bad = response(run)
    bad["answer"]["findings"][0]["evidence_ids"] = ["invented-credential-tool"]
    result = reviews.retain(run["id"], bad)
    assert result["state"] == "rejected" and result["response"] == bad
    assert reviews.retain(run["id"], bad)["response"] == bad
    with pytest.raises(ValueError, match="cannot be replaced"):
        reviews.retain(run["id"], response(run))


def test_completed_unchanged_evidence_is_not_new_learning(workspace):
    knowledge, _, reviews, *_ = workspace
    run = reviews.reserve(TASK, "fixture:done", policy())
    dispatch(reviews, run)
    reviews.retain(run["id"], response(run))
    with pytest.raises(ValueError, match="No changed evidence"):
        reviews.reserve(TASK, "fixture:unchanged", policy())
    assert knowledge.receipt(run["packet"]["knowledge"]["id"]) == run["packet"]["knowledge"]


def test_budget_and_disabled_policy_do_not_dispatch(workspace):
    _, _, reviews, *_ = workspace
    assert reviews.snapshot()["blocked_reasons"]
    asyncio.run(reviews.once())
    assert reviews.snapshot()["reviews"] == []
    with pytest.raises(ValueError, match="Approve data"):
        reviews.configure(policy(enabled=True), 0)
    reviews.reserve(TASK, "fixture:reserved", policy(daily_requests=1))
    with pytest.raises(ValueError):
        reviews.reserve(TASK, "fixture:budget", policy(daily_requests=1))


@pytest.mark.parametrize(
    "stamp", ["2026-03-08T09:30:00", "2026-11-01T08:30:00", "2026-11-02T22:00:00"]
)
def test_daily_occurrence_uses_denver_calendar_and_one_catchup(stamp):
    now = datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("UTC")).timestamp()
    occurrence, next_due = ResearchReviews.occurrence(policy(), now)
    assert next_due > now
    local = datetime.fromtimestamp(next_due, ZoneInfo("America/Denver"))
    assert local.hour == 8 and local.date().isoformat() > occurrence


def test_mcp_cp22_scope_revocation_and_no_arbitrary_tools(workspace):
    _, worker, reviews, actors, mcp = workspace
    task(worker, OTHER)
    run = reviews.reserve(TASK, "fixture:mcp", policy())
    granted = actors.grant(
        ActorGrant(actor="fixture-client", tasks=[TASK], processing_location="synthetic local QA")
    )
    token = granted["token"]
    assert (
        mcp.rpc(
            token,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        )["result"]["protocolVersion"]
        == "2025-11-25"
    )
    delivered = mcp.call(token, "review_get_packet", {"review": run["id"]})
    assert json.loads(delivered["content"][0]["text"])["sha256"] == run["packet_sha"]
    with pytest.raises(ValueError):
        mcp.call(token, "execute_sql", {"review": run["id"]})
    with pytest.raises(ValueError):
        mcp.call(token, "knowledge_search", {"review": run["id"], "query": "costs", "cutoff": 0})
    actors.revoke(granted["id"])
    with pytest.raises(ValueError, match="revoked"):
        mcp.call(token, "review_get_packet", {"review": run["id"]})


def test_real_api_library_and_mcp_client_without_provider(tmp_path):
    save_plan(tmp_path, plan_at(tmp_path))
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        assert (
            client.post("/api/research/knowledge/import", json=note().model_dump()).status_code
            == 403
        )
        assert (
            client.post(
                "/api/research/knowledge/import", json=note().model_dump(), headers=OPERATOR
            ).status_code
            == 200
        )
        assert client.get("/api/research/knowledge").json()["sources"][0]["revision"] == 1
        result = client.post(
            "/api/research/knowledge/search", json=query().model_dump(), headers=OPERATOR
        )
        assert result.status_code == 200 and len(result.json()["passages"]) == 2
        assert (
            client.post(
                "/api/research/knowledge/import",
                json=note().model_dump(),
                headers=OPERATOR | {"Origin": "https://foreign.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/research/reviews/credential",
                json={"credential": "private-test-value", "unexpected": True},
                headers=OPERATOR,
            ).status_code
            == 409
        )
        worker = app.state.lab.roles
        task(worker)
        run = app.state.reviews.reserve(TASK, "fixture:api", policy())
        tested = client.post("/api/research/reviews/connection-test", headers=OPERATOR)
        assert tested.status_code == 200 and len(tested.json()["tools"]) == 4
        assert "unqualified" in tested.json()["provider"]
        grant = ResearchActors(worker).grant(
            ActorGrant(
                actor="fixture-api-client", tasks=[TASK], processing_location="synthetic local QA"
            )
        )
        assert (
            client.get(
                "/api/status", headers={"Authorization": "Bearer " + grant["token"]}
            ).status_code
            == 403
        )

        async def actual_client():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as local:
                mcp = LocalMCPClient(local, grant["token"])
                await mcp.initialize()
                return await mcp.call("review_get_packet", {"review": run["id"]})

        assert asyncio.run(actual_client())["isError"] is False
        headers = {
            "Authorization": "Bearer " + grant["token"],
            "Accept": "application/json, text/event-stream",
        }
        assert (
            client.post(
                "/api/research/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers=headers | {"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            client.post("/api/research/mcp", content=b"x" * 262145, headers=headers).status_code
            == 413
        )
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    ) as reopened:
        assert (
            reopened.get("/api/research/knowledge").json()["sources"][0]["source"]
            == "methods-costs"
        )
        assert (
            reopened.get("/api/research/reviews/results/" + run["id"]).json()["packet_sha"]
            == run["packet_sha"]
        )


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows DPAPI native case")
def test_native_dpapi_keeps_secret_out_of_file_and_revoke(tmp_path):
    credential = ReviewerCredential(tmp_path)
    secret = "synthetic-qa-credential-" + "z" * 24
    credential.save(secret)
    assert secret.encode() not in credential.path.read_bytes()
    assert credential.load() == secret and credential.configured()
    credential.revoke()
    assert not credential.configured()


def test_responses_loop_executes_real_local_mcp_and_retains_context(tmp_path, monkeypatch):
    save_plan(tmp_path, plan_at(tmp_path))
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as operator:
        operator.post("/api/research/knowledge/import", json=note().model_dump(), headers=OPERATOR)
        worker = app.state.lab.roles
        task(worker)
        reviews = app.state.reviews
        cfg = policy(
            enabled=True,
            external_data_approved=True,
            spending_approved=True,
            schedule_owner_approved=True,
            supported_profile_verified=True,
        )
        run = reviews.reserve(TASK, "fixture:responses", cfg)
        dispatch(reviews, run)
        actors = ResearchActors(worker)
        grant = actors.grant(
            ActorGrant(
                actor="fixture-responses",
                tasks=[TASK],
                processing_location="synthetic local provider transport",
            )
        )
        provider = ResponsesReviewer(tmp_path, actors, app)
        monkeypatch.setattr(provider.credential, "load", lambda: "synthetic-not-an-api-key")
        reviews.transport = provider
        reviews.configure(cfg, 0)
        calls = []

        def reply(request):
            body = json.loads(request.content)
            calls.append(body)
            assert request.url.host == "api.openai.com"
            assert body["store"] is False and body["service_tier"] == "default"
            if len(calls) == 1:
                output = [
                    {
                        "type": "function_call",
                        "call_id": "fixture-call-1",
                        "name": "knowledge_search",
                        "arguments": json.dumps(
                            {"review": run["id"], "query": "transaction costs"}
                        ),
                    }
                ]
            else:
                supplied = json.loads(body["input"][-1]["output"])
                assert len(supplied["passages"]) == 2
                answer = response(run)["answer"]
                answer["findings"][0]["evidence_ids"] = [supplied["passages"][0]["citation"]]
                answer["findings"][0]["contrary_ids"] = [supplied["passages"][1]["citation"]]
                output = [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(answer)}],
                    }
                ]
            return httpx.Response(
                200,
                json={
                    "id": f"fixture-response-{len(calls)}",
                    "model": cfg.model,
                    "status": "completed",
                    "output": output,
                    "usage": {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600},
                },
            )

        async def execute():
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://localhost"
                ) as local,
                httpx.AsyncClient(transport=httpx.MockTransport(reply)) as remote,
            ):
                return await provider._execute(
                    run, cfg, LocalMCPClient(local, grant["token"]), remote
                )

        final = reviews.retain(run["id"], asyncio.run(execute()))
        assert final["state"] == "completed" and final["usage"]["api_requests"] == 2
        assert final["usage"]["total_tokens"] == 1200
        with worker.registry.lock:
            assert (
                worker.registry.db.execute(
                    "SELECT count(*) FROM review_provider_turns WHERE response IS NOT NULL"
                ).fetchone()[0]
                == 2
            )
            assert (
                worker.registry.db.execute("SELECT count(*) FROM review_tool_reads").fetchone()[0]
                == 1
            )


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_provider_fault_retains_dispatch_and_never_automatic_resend(
    workspace, tmp_path, monkeypatch, status
):
    _, worker, reviews, actors, _ = workspace
    run = reviews.reserve(TASK, "fixture:provider-fault", policy())
    provider = ResponsesReviewer(tmp_path, actors, None)
    monkeypatch.setattr(provider.credential, "load", lambda: "synthetic-not-an-api-key")

    class MCPStub:
        async def initialize(self):
            pass

        async def rpc(self, method, params):
            from trading.research_mcp import tools

            return {"tools": tools()}

        async def call(self, name, args):
            return {
                "content": [
                    {"text": json.dumps({"packet": run["packet"], "sha256": run["packet_sha"]})}
                ]
            }

    seen = []

    async def execute():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: seen.append(r) or httpx.Response(status, headers={"retry-after": "60"})
            )
        ) as api:
            await provider._execute(run, policy(), MCPStub(), api)

    with pytest.raises(ValueError, match=f"HTTP {status}"):
        asyncio.run(execute())
    assert len(seen) == 1
    with worker.registry.lock:
        saved = worker.registry.db.execute("SELECT * FROM review_provider_turns").fetchall()
        assert len(saved) == 1 and saved[0]["response"] is None


def test_reported_usage_over_budget_is_retained_and_stops_the_provider_loop(
    workspace, tmp_path, monkeypatch
):
    _, _, reviews, actors, _ = workspace
    cfg = policy()
    run = reviews.reserve(TASK, "fixture:usage-over-budget", cfg)
    provider = ResponsesReviewer(tmp_path, actors, None)
    monkeypatch.setattr(provider.credential, "load", lambda: "synthetic-not-an-api-key")

    class MCPStub:
        async def initialize(self):
            pass

        async def rpc(self, method, params):
            from trading.research_mcp import tools

            return {"tools": tools()}

        async def call(self, name, args):
            return {
                "content": [
                    {"text": json.dumps({"packet": run["packet"], "sha256": run["packet_sha"]})}
                ]
            }

    seen = []

    def overflow(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "fixture-over-budget",
                "model": cfg.model,
                "status": "completed",
                "output": [],
                "usage": {"input_tokens": 32768, "output_tokens": 32768, "total_tokens": 65536},
            },
        )

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(overflow)) as api:
            await provider._execute(run, cfg, MCPStub(), api)

    with pytest.raises(ValueError, match="exceeds the approved"):
        asyncio.run(execute())
    retained = reviews.get(run["id"])
    assert len(seen) == 1 and retained["provider_turns"][0]["response"] is not None
    assert retained["usage"]["total_tokens"] == 65536 and retained["cost_actual"] > 0
