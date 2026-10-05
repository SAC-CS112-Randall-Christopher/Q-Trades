"""Actual-owner regressions for PR 61 review; disposable sources and stub providers."""

import asyncio
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from test_persistent_research import (
    OPERATOR,
    OTHER,
    TASK,
    dispatch,
    note,
    policy,
    response,
    task,
)
from test_persistent_research import workspace as workspace
from test_research_storage import plan_at

from trading.api import create_app
from trading.config import Settings
from trading.research_actors import ActorGrant, ResearchActors
from trading.research_knowledge import KnowledgeQuery
from trading.research_mcp import LocalMCPClient
from trading.research_reviews import ResearchReviews, ReviewNotDispatched
from trading.research_storage import save_plan
from trading.reviewer_provider import ResponsesReviewer


class RecordingTransport:
    def __init__(self):
        self.calls = []

    def configured(self):
        return True

    async def review(self, run, cfg):
        self.calls.append(run)
        return response(run)


def enable(reviews, transport=None, **changes):
    reviews.transport = transport or RecordingTransport()
    reviews.configure(
        policy(
            enabled=True,
            external_data_approved=True,
            spending_approved=True,
            schedule_owner_approved=True,
            supported_profile_verified=True,
            **changes,
        ),
        0,
    )
    return reviews.transport


def attach_prior(worker, receipt, identity=TASK):
    context = worker.get(identity)["context"] | {"knowledge": receipt}
    with worker.registry.transaction():
        worker.registry.db.execute(
            "UPDATE role_tasks SET context=? WHERE id=?", (json.dumps(context), identity)
        )


@pytest.mark.parametrize(
    "original_external,current_external,permitted",
    [(False, True, False), (True, True, True), (True, False, False)],
)
def test_original_revision_and_current_rights_guard_cached_context(
    workspace, original_external, current_external, permitted
):
    knowledge, worker, reviews, *_ = workspace
    original = note("revision-rights").model_copy(
        update={"external_allowed": original_external, "training_allowed": True}
    )
    knowledge.ingest(original)
    prior = knowledge.retrieve(
        KnowledgeQuery(text="revision-rights", match="exact_source", cutoff=time.time())
    )
    assert {p["revision"] for p in prior["passages"]} == {1}
    attach_prior(worker, prior)
    knowledge.ingest(
        original.model_copy(
            update={
                "expected_revision": 1,
                "text": "Sanitized public theory about execution uncertainty.",
                "external_allowed": current_external,
            }
        )
    )
    # External disclosure and teaching rights are independent; local evidence stays intact.
    assert knowledge.read("revision-rights", 1, cutoff=time.time())["original"] == original.text
    assert knowledge.teaching_permitted("revision-rights", 1)
    cached = knowledge.receipt(prior["id"])
    assert cached == prior
    knowledge.check_passages(cached["passages"], external=False)
    if permitted:
        knowledge.check_passages(cached["passages"], external=True)
        assert knowledge.read("revision-rights", 1, cutoff=time.time(), external=True)
        assert reviews.packet(TASK, cutoff=time.time(), external=True)["prior_knowledge"] == prior
    else:
        with pytest.raises(ValueError, match="unavailable"):
            knowledge.read("revision-rights", 1, cutoff=time.time(), external=True)
        with pytest.raises(ValueError, match="revoked"):
            knowledge.check_passages(cached["passages"], external=True)
        with pytest.raises(ValueError, match="revoked"):
            reviews.packet(TASK, cutoff=time.time(), external=True)
        with pytest.raises(ValueError, match="revoked"):
            reviews.reserve(TASK, "fixture:revision-refusal", policy())
        assert reviews.snapshot()["reviews"] == []


def test_legacy_local_only_prior_context_cannot_leave_through_mcp(workspace, monkeypatch):
    knowledge, worker, reviews, actors, mcp = workspace
    knowledge.ingest(note("legacy-local-context").model_copy(update={"external_allowed": False}))
    prior = knowledge.retrieve(
        KnowledgeQuery(text="legacy-local-context", match="exact_source", cutoff=time.time())
    )
    attach_prior(worker, prior)
    knowledge.ingest(
        note("legacy-local-context", expected_revision=1).model_copy(
            update={"text": "Sanitized externally shareable replacement theory."}
        )
    )
    # Seed the frozen packet the old admission helper allowed. No provider/network call.
    with monkeypatch.context() as legacy:
        legacy.setattr(knowledge, "check_passages", lambda *args, **kwargs: None)
        run = reviews.reserve(TASK, "fixture:legacy-permission-bug", policy())
    assert run["packet"]["prior_knowledge"] == prior
    grant = actors.grant(
        ActorGrant(
            actor="revision-rights-QA", tasks=[TASK], processing_location="synthetic local QA"
        )
    )
    for name, args in [
        ("review_get_packet", {"review": run["id"]}),
        ("review_get_result", {"review": run["id"]}),
        ("evidence_read", {"review": run["id"], "citation": "e0"}),
    ]:
        with pytest.raises(ValueError, match="revoked"):
            mcp.call(grant["token"], name, args)
    assert reviews.get(run["id"])["packet"] == run["packet"]
    assert reviews.get(run["id"])["provider_turns"] == []


def test_legacy_packet_is_refused_by_actual_responses_mcp_loop_before_http(tmp_path, monkeypatch):
    save_plan(tmp_path, plan_at(tmp_path))
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app):
        knowledge, reviews, worker = app.state.knowledge, app.state.reviews, app.state.lab.roles
        task(worker)
        knowledge.ingest(note().model_copy(update={"external_allowed": False}))
        prior = knowledge.retrieve(
            KnowledgeQuery(text="methods-costs", match="exact_source", cutoff=time.time())
        )
        attach_prior(worker, prior)
        knowledge.ingest(note(expected_revision=1).model_copy(update={"text": "Sanitized costs."}))
        with monkeypatch.context() as legacy:
            legacy.setattr(knowledge, "check_passages", lambda *args, **kwargs: None)
            run = reviews.reserve(TASK, "fixture:legacy-responses", policy())
        dispatch(reviews, run)
        actors = ResearchActors(worker)
        grant = actors.grant(
            ActorGrant(
                actor="legacy-responses-QA", tasks=[TASK], processing_location="synthetic local QA"
            )
        )
        provider = ResponsesReviewer(tmp_path, actors, app)
        calls = []

        def remote(request):
            calls.append(request)
            raise AssertionError("No legacy local-only text may reach a provider request")

        async def execute():
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://localhost"
                ) as local,
                httpx.AsyncClient(transport=httpx.MockTransport(remote)) as api,
            ):
                with pytest.raises(ReviewNotDispatched):
                    await provider._execute(
                        run, policy(), LocalMCPClient(local, grant["token"]), api
                    )

        asyncio.run(execute())
        assert calls == [] and reviews.get(run["id"])["provider_turns"] == []
        assert reviews.get(run["id"])["packet"] == run["packet"]


def test_actual_background_manual_api_overlap_preserves_dispatch(tmp_path):
    save_plan(tmp_path, plan_at(tmp_path))
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    entered, release = threading.Event(), threading.Event()

    class WaitingTransport(RecordingTransport):
        async def review(self, run, cfg):
            self.calls.append(run)
            entered.set()
            assert await asyncio.to_thread(release.wait, 5)
            return response(run)

    with TestClient(app) as client:
        reviews = app.state.reviews
        task(app.state.lab.roles)
        app.state.knowledge.ingest(note())
        transport = enable(reviews, WaitingTransport())
        assert client.portal is not None
        background = client.portal.start_task_soon(reviews.run)
        try:
            assert entered.wait(3)
            run = reviews.snapshot()["reviews"][0]
            assert run["state"] == "dispatching"
            assert client.post("/api/research/reviews/run", headers=OPERATOR).status_code == 200

            async def finish_manual():
                await asyncio.wait_for(app.state.manual_review_task, 2)

            client.portal.call(finish_manual)
            detail = client.get(f"/api/research/reviews/results/{run['id']}").json()
            assert detail["state"] == "dispatching"
            assert len(transport.calls) == 1
            refused = client.post(
                f"/api/research/reviews/results/{run['id']}/reconcile",
                headers=OPERATOR,
                json={
                    "expected_state": "unknown",
                    "action": "abandon_unknown",
                    "reason": "An active provider attempt cannot be abandoned as interrupted.",
                },
            )
            assert refused.status_code == 409
            release.set()

            async def await_completion():
                async with asyncio.timeout(3):
                    while reviews.get(run["id"])["state"] == "dispatching":
                        await asyncio.sleep(0.01)

            client.portal.call(await_completion)
            detail = client.get(f"/api/research/reviews/results/{run['id']}").json()
            assert detail["state"] == "completed"
            assert detail["response"] == response(transport.calls[0])
            assert len(transport.calls) == 1
        finally:
            release.set()
            background.cancel()


def test_same_instance_dispatch_cas_loser_does_not_finalize_winner(workspace, monkeypatch):
    _, _, reviews, *_ = workspace
    barrier = threading.Barrier(2)
    reserve = reviews.reserve

    def overlapping_reserve(*args, **kwargs):
        barrier.wait(timeout=3)
        run = reserve(*args, **kwargs)
        barrier.wait(timeout=3)
        return run

    monkeypatch.setattr(reviews, "reserve", overlapping_reserve)

    async def check():
        entered, release = asyncio.Event(), asyncio.Event()

        class WaitingTransport(RecordingTransport):
            async def review(self, run, cfg):
                self.calls.append(run)
                entered.set()
                await release.wait()
                return response(run)

        transport = enable(reviews, WaitingTransport())
        running = [asyncio.create_task(reviews.once()) for _ in range(2)]
        try:
            await asyncio.wait_for(entered.wait(), 4)
            _, pending = await asyncio.wait(running, timeout=3, return_when=asyncio.FIRST_COMPLETED)
            assert len(pending) == 1
            assert len(transport.calls) == 1
            run = transport.calls[0]
            assert reviews.get(run["id"])["state"] == "dispatching"
            release.set()
            await asyncio.wait_for(asyncio.gather(*running), 3)
            assert reviews.get(run["id"])["state"] == "completed"
            assert len(transport.calls) == 1
        finally:
            release.set()
            for invocation in running:
                invocation.cancel()
            await asyncio.gather(*running, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("interruption", ["cancellation", "timeout"])
def test_real_cancellation_and_timeout_keep_uncertain_request_reserved(workspace, interruption):
    knowledge, worker, reviews, *_ = workspace

    async def check():
        entered = asyncio.Event()

        class WaitingTransport(RecordingTransport):
            async def review(self, run, cfg):
                self.calls.append(run)
                entered.set()
                await asyncio.Future()

        transport = enable(reviews, WaitingTransport(), deadline_seconds=15)
        running = asyncio.create_task(reviews.once())
        await asyncio.wait_for(entered.wait(), 2)
        if interruption == "cancellation":
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            await asyncio.wait_for(running, 17)
        run = reviews.get(transport.calls[0]["id"])
        assert run["state"] == "unknown" and run["cost_reserved"] == 0.5
        assert run["cost_actual"] is None and run["response"] is None
        successor = ResearchReviews(worker, knowledge, transport)
        await successor.once()
        assert len(transport.calls) == 1
        assert successor.get(run["id"])["state"] == "unknown"

    asyncio.run(check())


def test_two_due_occurrences_cover_both_results_then_changed_evidence(workspace, monkeypatch):
    knowledge, worker, reviews, *_ = workspace
    clock = time.time()
    monkeypatch.setattr("trading.research_reviews.time.time", lambda: clock)
    task(worker, OTHER)
    with worker.registry.transaction():
        worker.registry.db.execute("UPDATE role_tasks SET updated=? WHERE id=?", (clock - 10, TASK))
    transport = enable(reviews)
    asyncio.run(reviews.once())
    assert [r["task"] for r in transport.calls] == [OTHER]
    clock += 86401
    asyncio.run(reviews.once())
    assert [r["task"] for r in transport.calls] == [OTHER, TASK]
    clock += 86401
    asyncio.run(reviews.once())
    for _ in range(4):
        asyncio.run(reviews.once())
    assert len(transport.calls) == 2
    assert "No changed evidence" in reviews.reason
    # Relevant new source evidence remains reviewable without replaying a paid occurrence.
    knowledge.ingest(note("changed-methods-costs"))
    asyncio.run(reviews.once())
    assert len(transport.calls) == 3
    assert len({r["occurrence"] for r in transport.calls}) == 3
    assert all(r["state"] == "completed" for r in reviews.snapshot()["reviews"])


def test_nondisclosable_newest_result_does_not_starve_older(workspace):
    knowledge, worker, reviews, *_ = workspace
    knowledge.ingest(note("blocked-latest").model_copy(update={"external_allowed": False}))
    prior = knowledge.retrieve(
        KnowledgeQuery(text="blocked-latest", match="exact_source", cutoff=time.time())
    )
    task(worker, OTHER)
    attach_prior(worker, prior, OTHER)
    transport = enable(reviews)
    asyncio.run(reviews.once())
    assert [r["task"] for r in transport.calls] == [TASK]
    assert all(r["task"] != OTHER for r in reviews.snapshot()["reviews"])


def test_selection_progress_is_bounded_and_survives_restart(workspace, monkeypatch):
    knowledge, worker, reviews, *_ = workspace
    knowledge.ingest(note("blocked-window").model_copy(update={"external_allowed": False}))
    prior = knowledge.retrieve(
        KnowledgeQuery(text="blocked-window", match="exact_source", cutoff=time.time())
    )
    # More blocked candidates than one bounded selection pass, ahead of eligible TASK.
    for n in range(40):
        identity = "role-" + f"{n + 100:032x}"
        task(worker, identity)
        attach_prior(worker, prior, identity)
    transport = enable(reviews)
    calls = []
    packet = reviews.packet

    def counted_packet(*args, **kwargs):
        calls.append(args[0])
        return packet(*args, **kwargs)

    monkeypatch.setattr(reviews, "packet", counted_packet)
    asyncio.run(reviews.once())
    assert not transport.calls and 0 < len(calls) <= 16
    assert "bounded" in reviews.reason.lower()
    # Reopen the owners, retaining only durable cursor/cache state.
    for _ in range(4):
        successor = ResearchReviews(worker, knowledge, transport)
        calls = []
        monkeypatch.setattr(successor, "packet", counted_packet)
        asyncio.run(successor.once())
        assert len(calls) <= 16
        if transport.calls:
            break
    assert [r["task"] for r in transport.calls] == [TASK]


def test_selection_does_not_scan_past_global_budget_or_provider_backoff(workspace, monkeypatch):
    _, worker, reviews, *_ = workspace
    task(worker, OTHER)
    transport = enable(reviews)
    asyncio.run(reviews.once())
    first = transport.calls[0]
    clock = first["created"] + 86401
    monkeypatch.setattr("trading.research_reviews.time.time", lambda: clock)
    packet_calls = []
    packet = reviews.packet

    def counted_packet(*args, **kwargs):
        packet_calls.append(args[0])
        return packet(*args, **kwargs)

    monkeypatch.setattr(reviews, "packet", counted_packet)
    with reviews.registry.transaction():
        reviews.registry.db.execute(
            "INSERT INTO review_provider_faults VALUES(?,0,'rate_limit',429,?)",
            (first["id"], clock + 600),
        )
    asyncio.run(reviews.once())
    assert len(transport.calls) == 1 and "backoff" in reviews.reason.lower()
    assert packet_calls == []
    clock += 601
    cfg = reviews.policy()[1]
    assert cfg is not None
    reviews.configure(cfg.model_copy(update={"monthly_cost_ceiling_usd": 1.0}), 1)
    # Preserve unknown spend; a rolling budget is a global admission boundary.
    with reviews.registry.transaction():
        reviews.registry.db.execute(
            "UPDATE scheduled_reviews SET cost_actual=0.6 WHERE id=?", (first["id"],)
        )
    asyncio.run(reviews.once())
    assert len(transport.calls) == 1 and "30-day cost budget" in reviews.reason
    assert packet_calls == []
    assert len(reviews.snapshot()["reviews"]) == 1
