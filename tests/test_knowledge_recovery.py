"""Disposable acquisition, correction outbox and scheduler recovery; no model calls."""

import asyncio
import base64
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_persistent_research import (
    TASK,
    dispatch,
    note,
    policy,
    query,
    response,
)
from test_persistent_research import workspace as workspace

from trading.knowledge_acquisition import URLImport, acquire, public_target
from trading.research_knowledge import DocumentImport, KnowledgeDisposition, ResearchKnowledge
from trading.research_reviews import ResearchReviews, ReviewDecision, ReviewReconcile
from trading.training_workflow import SourceSelection, TrainingWorkflow


def complete(reviews):
    run = reviews.reserve(TASK, "fixture:recovery", policy())
    dispatch(reviews, run)
    return reviews.retain(run["id"], response(run))


def accept():
    return ReviewDecision(
        expected_revision=0,
        disposition="accept_annotation",
        reason="Operator independently checked the cited synthetic context.",
    )


def test_revoked_receipt_cannot_disclose_at_old_cutoff(workspace):
    knowledge, _, reviews, actors, mcp = workspace
    from trading.research_actors import ActorGrant

    run = reviews.reserve(TASK, "fixture:revoked", policy())
    grant = actors.grant(
        ActorGrant(
            actor="fixture-revocation", tasks=[TASK], processing_location="synthetic local QA"
        )
    )
    original = knowledge.read("methods-costs", 1, cutoff=time.time())
    knowledge.disposition(
        "methods-costs",
        KnowledgeDisposition(
            revision=1,
            expected_state=original["disposition"]["seq"],
            state="withdrawn",
            reason="Disclosure permissions revoked by operator.",
        ),
    )
    for name, args in [
        ("review_get_packet", {"review": run["id"]}),
        (
            "evidence_read",
            {
                "review": run["id"],
                "citation": run["packet"]["knowledge"]["passages"][0]["citation"],
            },
        ),
    ]:
        with pytest.raises(ValueError):
            mcp.call(grant["token"], name, args)
    assert reviews.get(run["id"])["packet"] == run["packet"]
    assert knowledge.retrieve(query())["passages"] == []


def test_local_reference_context_cannot_bypass_external_packet_permissions(workspace):
    knowledge, worker, reviews, *_ = workspace
    knowledge.ingest(note("local-secret-theory").model_copy(update={"external_allowed": False}))
    receipt = knowledge.retrieve(query())
    with worker.registry.transaction():
        context = worker.get(TASK)["context"] | {"knowledge": receipt}
        worker.registry.db.execute(
            "UPDATE role_tasks SET context=? WHERE id=?", (json.dumps(context), TASK)
        )
    with pytest.raises(ValueError, match="revoked"):
        reviews.reserve(TASK, "fixture:local-only", policy())
    assert reviews.snapshot()["reviews"] == []


def test_prior_context_dependency_remains_revocable_when_fresh_search_omits_it(workspace):
    knowledge, worker, reviews, actors, mcp = workspace
    from trading.research_actors import ActorGrant
    from trading.research_knowledge import KnowledgeQuery

    knowledge.ingest(
        note("prior-context").model_copy(
            update={"title": "Prior assumptions", "text": "Unrelated alpha beta assumptions."}
        )
    )
    prior = knowledge.retrieve(
        KnowledgeQuery(text="prior-context", match="exact_source", cutoff=time.time())
    )
    with worker.registry.transaction():
        worker.registry.db.execute(
            "UPDATE role_tasks SET context=? WHERE id=?",
            (json.dumps(worker.get(TASK)["context"] | {"knowledge": prior}), TASK),
        )
    run = reviews.reserve(TASK, "fixture:prior-context", policy())
    assert not any(p["source"] == "prior-context" for p in run["packet"]["knowledge"]["passages"])
    assert any(p["source"] == "prior-context" for p in reviews.delivered_passages(run["id"]))
    grant = actors.grant(
        ActorGrant(actor="prior-context-QA", tasks=[TASK], processing_location="synthetic local QA")
    )
    original = knowledge.read("prior-context", 1, cutoff=time.time())
    knowledge.disposition(
        "prior-context",
        KnowledgeDisposition(
            revision=1,
            expected_state=original["disposition"]["seq"],
            state="withdrawn",
            reason="Operator revoked this original derivation source.",
        ),
    )
    for name, args in [
        ("review_get_packet", {"review": run["id"]}),
        ("evidence_read", {"review": run["id"], "citation": "e0"}),
    ]:
        with pytest.raises(ValueError, match="revoked"):
            mcp.call(grant["token"], name, args)


def test_mcp_request_budget_stops_acquisition_before_receipt_growth(workspace):
    knowledge, _, reviews, actors, mcp = workspace
    from trading.research_actors import ActorGrant

    run = reviews.reserve(TASK, "fixture:budget-search", policy())
    grant = actors.grant(
        ActorGrant(
            actor="fixture-small-budget",
            tasks=[TASK],
            requests=1,
            processing_location="synthetic local QA",
        )
    )
    mcp.call(grant["token"], "knowledge_search", {"review": run["id"], "query": "costs"})
    with knowledge.connection() as db:
        count = db.execute("SELECT count(*) FROM knowledge_receipts").fetchone()[0]
    for q in ["private phrase", "another phrase", "third phrase"]:
        with pytest.raises(ValueError, match="allowance"):
            mcp.call(grant["token"], "knowledge_search", {"review": run["id"], "query": q})
    with knowledge.connection() as db:
        assert db.execute("SELECT count(*) FROM knowledge_receipts").fetchone()[0] == count


def test_two_disposable_scheduled_occurrences_restart_and_unchanged_backoff(workspace, monkeypatch):
    knowledge, worker, reviews, *_ = workspace
    clock = time.time()
    monkeypatch.setattr("trading.research_reviews.time.time", lambda: clock)

    class Transport:
        def __init__(self):
            self.calls = []

        def configured(self):
            return True

        async def review(self, run, cfg):
            self.calls.append(run["occurrence"])
            return response(run)

    transport = Transport()
    reviews.transport = transport
    cfg = policy(
        enabled=True,
        external_data_approved=True,
        spending_approved=True,
        schedule_owner_approved=True,
        supported_profile_verified=True,
    )
    reviews.configure(cfg, 0)
    asyncio.run(reviews.once())
    assert len(transport.calls) == 1
    clock += 86401
    asyncio.run(reviews.once())
    with knowledge.connection() as db:
        baseline = db.execute("SELECT count(*) FROM knowledge_receipts").fetchone()[0]
    for _ in range(6):
        clock += 31
        asyncio.run(reviews.once())
    with knowledge.connection() as db:
        assert db.execute("SELECT count(*) FROM knowledge_receipts").fetchone()[0] == baseline
    assert len(transport.calls) == 1 and reviews.reason.startswith("No changed evidence")
    knowledge.ingest(note("new-costs-evidence"))
    successor = ResearchReviews(worker, knowledge, transport)
    asyncio.run(successor.once())
    asyncio.run(successor.once())
    assert len(transport.calls) == 2 and len(set(transport.calls)) == 2
    assert all(r["state"] == "completed" for r in successor.snapshot()["reviews"])


def test_missing_guard_cannot_admit_even_configured_procedural_reviewer(workspace):
    _, worker, reviews, *_ = workspace

    class Transport:
        def configured(self):
            return True

        async def review(self, run, cfg):
            raise AssertionError("An unavailable guard must refuse before dispatch")

    reviews.transport = Transport()
    reviews.configure(
        policy(
            enabled=True,
            external_data_approved=True,
            spending_approved=True,
            schedule_owner_approved=True,
            supported_profile_verified=True,
        ),
        0,
    )
    worker.controller = None
    asyncio.run(reviews.once())
    assert reviews.snapshot()["reviews"] == []
    assert "guard blocks" in reviews.reason


def test_known_predispatch_refusal_is_blocked_without_unknown_charge(workspace):
    _, _, reviews, *_ = workspace
    from trading.research_reviews import ReviewNotDispatched

    class Transport:
        def configured(self):
            return True

        async def review(self, run, cfg):
            raise ReviewNotDispatched("Known local credential refusal; no HTTP request")

    reviews.transport = Transport()
    reviews.configure(
        policy(
            enabled=True,
            external_data_approved=True,
            spending_approved=True,
            schedule_owner_approved=True,
            supported_profile_verified=True,
        ),
        0,
    )
    asyncio.run(reviews.once())
    run = reviews.get(reviews.snapshot()["reviews"][0]["id"])
    assert run["state"] == "blocked" and run["cost_actual"] == 0
    assert run["provider_turns"] == []
    asyncio.run(reviews.once())
    assert len(reviews.snapshot()["reviews"]) == 1


def test_derived_index_loss_retains_canonical_search_and_originals(workspace):
    knowledge, *_ = workspace
    with knowledge.write(0) as db:
        db.execute("DROP TABLE knowledge_fts")
    assert "unavailable" in knowledge.list()["index_condition"]
    assert knowledge.retrieve(query())["passages"]
    assert knowledge.read("methods-costs", 1, cutoff=time.time())["original"] == note().text
    knowledge.reindex()
    assert "available" in knowledge.list()["index_condition"]


def test_fresh_restore_rebuilds_and_preserves_original_source_receipt(workspace):
    knowledge, *_ = workspace
    receipt = knowledge.retrieve(query())
    backup = knowledge.backup()
    old = knowledge.path.read_bytes()
    restored = knowledge.restore(backup["backup"], backup["sha256"])
    snapshot = ResearchKnowledge(knowledge.storage, name=restored["library"])
    assert snapshot.receipt(receipt["id"]) == receipt
    assert snapshot.read("methods-costs", 1, cutoff=time.time())["original"] == note().text
    assert knowledge.path.read_bytes() == old
    with pytest.raises(ValueError, match="checksum"):
        knowledge.restore(backup["backup"], "0" * 64)
    with pytest.raises(ValueError, match="arbitrary"):
        knowledge.restore("../../foreign.sqlite", backup["sha256"])


def test_correction_lost_ack_restart_and_dispute_have_one_adoption(workspace, monkeypatch):
    knowledge, worker, reviews, *_ = workspace
    run = complete(reviews)
    with monkeypatch.context() as m:
        m.setattr(reviews, "continue_corrections", lambda: None)
        reviews.decide(run["id"], accept())
    reopened = ResearchReviews(worker, knowledge)
    reopened.continue_corrections()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: reopened.decide(run["id"], accept()), range(3)))
    saved = reopened.get(run["id"])
    assert len(saved["decisions"]) == 1 and saved["correction"][0]["state"] == "saved"
    source_id = saved["correction"][0]["source"]
    assert knowledge.read(source_id, 1, cutoff=time.time())["disposition"]["state"] == "accepted"
    assert any(p["source"] == source_id for p in knowledge.retrieve(query())["passages"])
    reopened.decide(
        run["id"],
        ReviewDecision(
            expected_revision=1,
            disposition="dispute",
            reason="Later independent review finds uncertainty.",
        ),
    )
    assert knowledge.read(source_id, 1, cutoff=time.time())["disposition"]["state"] == "disputed"
    assert reopened.get(run["id"])["response"] == run["response"]


def test_blocked_correction_remains_pending_then_continues(workspace, monkeypatch):
    knowledge, _, reviews, *_ = workspace
    run = complete(reviews)
    with monkeypatch.context() as m:
        m.setattr(knowledge, "ingest", lambda _: (_ for _ in ()).throw(OSError("quota")))
        pending = reviews.decide(run["id"], accept())
        assert pending["correction"][0]["state"] == "pending"
    reviews.continue_corrections()
    assert reviews.get(run["id"])["correction"][0]["state"] == "saved"


def test_legacy_annotation_metadata_is_not_rewritten_on_continuation(workspace, monkeypatch):
    knowledge, _, reviews, *_ = workspace
    run = complete(reviews)
    ingest = knowledge.ingest
    with monkeypatch.context() as old_version:
        old_version.setattr(
            knowledge,
            "ingest",
            lambda command: ingest(
                command.model_copy(
                    update={
                        "rights": "Legacy review annotation; no external or training rights"
                    }
                )
            ),
        )
        reviews.decide(run["id"], accept())
    source = reviews.get(run["id"])["correction"][0]["source"]
    original = knowledge.read(source, 1, cutoff=time.time(), operator=True)
    # Simulate a source-preserving upgrade whose new default metadata wording differs.
    with reviews.registry.transaction():
        reviews.registry.db.execute(
            "UPDATE review_corrections SET state='pending' WHERE id=?", (run["id"],)
        )
    with knowledge.connection() as db:
        count = db.execute(
            "SELECT count(*) FROM knowledge_sources WHERE source=?", (source,)
        ).fetchone()[0]
    reviews.continue_corrections()
    assert reviews.get(run["id"])["correction"][0]["state"] == "saved"
    assert knowledge.read(source, 1, cutoff=time.time(), operator=True) == original
    with knowledge.connection() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM knowledge_sources WHERE source=?", (source,)
            ).fetchone()[0]
            == count
        )


def test_supported_followup_uses_existing_durable_request_identity(workspace, monkeypatch):
    _, worker, reviews, *_ = workspace
    run = complete(reviews)
    reviews.decide(run["id"], accept())
    calls = []
    monkeypatch.setattr(worker, "enqueue", lambda q: calls.append(q.model_dump()) or {"id": TASK})
    reviews.continue_questions()
    reviews.continue_questions()
    assert len(calls) == 1 and calls[0]["request_id"].startswith("review-followup-")
    assert reviews.get(run["id"])["followups"][0]["state"] == "queued"


def test_review_to_existing_instructional_teaching_preserves_model_authorship(workspace):
    knowledge, worker, reviews, *_ = workspace
    knowledge.ingest(note(expected_revision=1).model_copy(update={"training_allowed": True}))
    run = complete(reviews)
    reviews.decide(run["id"], accept())
    worker.reviews = reviews
    teaching = TrainingWorkflow(worker.registry, worker)
    selection = SourceSelection(
        kind="review_annotation",
        identity=run["id"],
        role="reviewer",
        rights_reason="Synthetic owner-authored teaching material permitted.",
    )
    first = teaching.select(selection)
    again = teaching.select(selection)
    assert first["id"] == again["id"]
    assert first["candidate"]["source_kind"] == "instructional"
    assert "Model-assisted" in first["candidate"]["authorship"]["author"]
    assert first["candidate"]["original_answer"] is None
    assert first["candidate"]["authorship"]["empirical_performance_claim"] is False


def test_reconcile_unknown_never_refunds_or_replays(workspace):
    _, _, reviews, *_ = workspace
    run = reviews.reserve(TASK, "fixture:unknown-reconcile", policy())
    with reviews.registry.transaction():
        reviews.registry.db.execute(
            "UPDATE scheduled_reviews SET state='unknown' WHERE id=?", (run["id"],)
        )
    cmd = ReviewReconcile(
        expected_state="unknown",
        action="abandon_unknown",
        reason="Operator acknowledges unavailable external completion proof.",
    )
    first = reviews.reconcile(run["id"], cmd)
    again = reviews.reconcile(run["id"], cmd)
    assert first["state"] == "abandoned" and first["cost_reserved"] == 0.5
    assert again["reconciliations"] == first["reconciliations"]
    assert reviews.reserve(TASK, "fixture:unknown-reconcile", policy())["id"] == run["id"]


def test_reconcile_retained_provider_final_without_network(workspace):
    _, _, reviews, *_ = workspace
    run = reviews.reserve(TASK, "fixture:local-final", policy())
    original = {
        "id": "fixture-original",
        "model": policy().model,
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(response(run)["answer"])}],
            }
        ],
    }
    with reviews.registry.transaction():
        reviews.registry.db.execute(
            "UPDATE scheduled_reviews SET state='unknown' WHERE id=?", (run["id"],)
        )
        reviews.registry.db.execute(
            "INSERT INTO review_provider_turns VALUES(?,0,?,?,?)",
            (run["id"], "fixture-sha", json.dumps(original), time.time()),
        )
    result = reviews.reconcile(
        run["id"],
        ReviewReconcile(
            expected_state="unknown",
            action="validate_retained",
            reason="Operator reopens the already retained final provider response.",
        ),
    )
    assert result["state"] == "completed" and result["provider_id"] == "fixture-original"


def pdf_bytes(*, blank=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=500)
    if not blank:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        contents = DecodedStreamObject()
        contents.set_data(b"BT /F1 12 Tf 20 400 Td (Transaction costs are uncertain.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(contents)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_native_owned_pdf_source_bytes_pages_and_scanned_absence(workspace):
    knowledge, *_ = workspace
    raw = pdf_bytes()
    command = DocumentImport(
        **(
            note("native-pdf").model_dump()
            | {
                "format": "pdf",
                "document_base64": base64.b64encode(raw).decode(),
            }
        )
    )
    knowledge.ingest_document(command)
    read = knowledge.read("native-pdf", 1, cutoff=time.time())
    assert "Transaction costs" in read["text"] and read["original_bytes"] == len(raw)
    assert read["metadata"]["extraction"]["first_page"] == 1
    with knowledge.connection() as db:
        assert (
            db.execute(
                "SELECT original FROM knowledge_sources WHERE source='native-pdf'"
            ).fetchone()[0]
            == raw
        )
    with pytest.raises(ValueError, match="extraction"):
        knowledge.ingest_document(
            command.model_copy(
                update={
                    "source_id": "scanned-pdf",
                    "document_base64": base64.b64encode(pdf_bytes(blank=True)).decode(),
                }
            )
        )
    assert not any(s["source"] == "scanned-pdf" for s in knowledge.list()["sources"])


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/doc",
        "https://user:pw@example.com/doc",
        "https://example.com:444/doc",
        "https://example.com/doc?token=x",
        "file:///C:/private.txt",
        "https://127.0.0.1/doc",
    ],
)
def test_url_private_credentials_and_nonpublic_targets_refused(url):
    with pytest.raises(ValueError):
        public_target(url)


def test_url_byte_exact_no_redirect_no_compression(workspace, monkeypatch):
    knowledge, *_ = workspace
    from trading import knowledge_acquisition as module

    monkeypatch.setattr(module, "public_target", lambda _: ("example.com", "93.184.216.34"))
    payload = b"<p>Transaction costs remain uncertain.</p>"

    class Connection:
        status = 200

        def __init__(self, *args):
            self.stream = io.BytesIO(payload)

        def request(self, method, path, headers):
            assert method == "GET" and headers["Accept-Encoding"] == "identity"
            assert "Authorization" not in headers

        def getresponse(self):
            return self

        def getheader(self, key):
            return "text/html; charset=utf-8" if key == "Content-Type" else None

        def read(self, size):
            return self.stream.read(size)

        def close(self):
            pass

    monkeypatch.setattr(module, "_PinnedHTTPS", Connection)
    cmd = URLImport(
        **(
            note("url-fixture").model_dump()
            | {
                "origin": "https://example.com/doc",
                "url": "https://example.com/doc",
                "acquire_approved": True,
                "format": "html",
            }
        )
    )
    acquire(knowledge, cmd)
    assert knowledge.read("url-fixture", 1, cutoff=time.time())["original"].encode() == payload
    Connection.status = 302
    with pytest.raises(ValueError, match="redirect"):
        acquire(knowledge, cmd.model_copy(update={"source_id": "redirect-fixture"}))
