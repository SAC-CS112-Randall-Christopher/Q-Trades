"""Disposable operator/review contracts; real Lab acceptance is separately recorded."""

import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

import pytest
from fastapi.testclient import TestClient
from test_llm_training import example, reseal, task

from trading.api import create_app
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.llm_training import Example, prepare
from trading.llm_training_preflight import preflight
from trading.role_worker import RoleWorker
from trading.storage import MonitorStore
from trading.training_bridge import TrainingBridge, compact_digest
from trading.training_workflow import (
    DatasetSelection,
    ReviewSave,
    SourceSelection,
    TrainingWorkflow,
)


def local(tmp_path):
    registry = ExperimentRegistry(tmp_path / "research.sqlite3")
    roles = RoleWorker(registry, None)
    store = MonitorStore(tmp_path / "monitor.sqlite3")
    store.record(
        "depth", "BTCUSD", "2026-09-01T00:00:00+00:00", {"test": "synthetic raw book"}, "a" * 64
    )
    return TrainingWorkflow(registry, roles, store)


def observed(workflow):
    return workflow.select(
        SourceSelection(
            kind="market_observation",
            identity="1",
            question="Which missing original evidence limits this software observation?",
            author="Synthetic fixture author",
            role="researcher",
        )
    )


def review(detail, disposition="accept"):
    origin = detail["review_template"]
    return ReviewSave(
        revision=detail["revision"],
        disposition=disposition,
        reason="A synthetic fixture checks explicit uncertainty, never actual market value.",
        lesson="Request the missing original contemporaneous evidence.",
        rights_reason="Synthetic authored software fixture; no licensed market content.",
        review=origin
        | {
            "reviewer": "Synthetic delegated fixture reviewer",
            "reviewer_kind": "delegated_semantic",
            "reviewer_authored_material": True,
            "rights_confirmed": True,
            "categories": ["justified_wait", "followup"],
        },
        target={
            "action": "request_data",
            "evidence_ids": ["e0"],
            "capability": None,
            "mechanism": "Retain the local receipt without asserting execution eligibility.",
            "falsification": "Original eligible engine input would resolve this evidence gap.",
            "rationale": "The response lacks original clock and execution eligibility checks.",
            "dependency": "Obtain original contemporaneous engine eligibility evidence.",
        },
    )


def seed_attempt(workflow, count=1, oversized=False):
    original = task()
    with workflow.registry.transaction():
        workflow.registry.db.execute(
            "INSERT INTO role_tasks(id,created,updated,stage,status,context) VALUES (?,?,?,?,?,?)",
            (original["id"], 100, 101, "idea", "no_change", json.dumps(original["context"])),
        )
        a = original["attempts"][0]
        for i in range(1, count + 1):
            response = (
                a["response"] if i == 1 and not oversized else json.dumps({"answer": "x" * 140000})
            )
            workflow.registry.db.execute(
                "INSERT INTO role_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    original["id"],
                    "idea",
                    i,
                    100,
                    101,
                    "completed",
                    "{}",
                    a["packet"],
                    response,
                    None,
                    1,
                    1,
                ),
            )
    return original["id"]


def test_selected_export_does_not_serialize_unrelated_history(tmp_path, monkeypatch):
    workflow = local(tmp_path)
    identity = seed_attempt(workflow, count=7)

    def fail(*args):
        raise AssertionError("Full task dashboard must not be used for selected export")

    monkeypatch.setattr(workflow.roles, "view", fail)
    monkeypatch.setattr(workflow.roles, "get", fail)
    selected = workflow.roles.training_candidate(identity, "idea", 1)
    assert selected["candidate"]["original_answer"]["action"] == "no_change"
    assert len(workflow.sources()["attempts"]) == 7
    with pytest.raises(ValueError, match="unavailable|exceeds|retained"):
        workflow.roles.training_candidate(identity, "idea", 2)


def test_observed_source_has_no_fabricated_question_or_answer_and_keeps_raw(tmp_path):
    workflow = local(tmp_path)
    detail = observed(workflow)
    c = detail["candidate"]
    assert c["original_answer"] is None and c["attempt"] == 0
    source = c["observed_source"]
    assert source["original_question"] is None and source["original_model_answer"] is None
    assert c["decision_at"] > source["available_at"]
    assert source["source_sha256"] == fingerprint(source["original_record"])
    assert "payload" not in c["packet"]["evidence"]["e0"]
    saved = workflow.save(detail["id"], review(detail))
    accepted = Example.model_validate(
        {"candidate": c, "review": saved["saved"]["review"], "target": saved["saved"]["target"]}
    )
    assert accepted.review.claim_scope == "interpretation"
    raw = copy.deepcopy(c)
    raw["observed_source"]["original_record"]["payload"] = {"altered": True}
    reseal(raw)
    with pytest.raises(ValueError, match="Original retained"):
        Example.model_validate(
            {
                "candidate": raw,
                "review": saved["saved"]["review"],
                "target": saved["saved"]["target"],
            }
        )


@pytest.mark.parametrize("disposition", ["draft", "pending", "exclude"])
def test_unapproved_dispositions_persist_but_do_not_admit(tmp_path, disposition):
    workflow = local(tmp_path)
    detail = observed(workflow)
    saved = workflow.save(detail["id"], review(detail, disposition))
    assert saved["revision"] == 1 and saved["saved"]["disposition"] == disposition
    from trading.training_workflow import DatasetSelection

    selection = DatasetSelection(ids=[detail["id"]], train_end=2e9, validation_end=2.1e9)
    _, problems = workflow.rows(selection)
    assert problems[0]["code"] == "unapproved_disposition"
    assert workflow.detail(detail["id"])["candidate"] == detail["candidate"]


@pytest.mark.parametrize("field", ["reviewer_kind", "reviewer_authored_material", "claim_scope"])
def test_missing_new_provenance_is_not_defaulted(tmp_path, field):
    workflow = local(tmp_path)
    detail = observed(workflow)
    value = review(detail).model_dump()
    value["review"].pop(field)
    with pytest.raises(ValueError):
        workflow.save(detail["id"], ReviewSave.model_validate(value))
    assert workflow.detail(detail["id"])["revision"] == 0


def test_observed_interpretation_cannot_be_approved_as_execution(tmp_path):
    workflow = local(tmp_path)
    detail = observed(workflow)
    draft = review(detail)
    draft.review["claim_scope"] = "original_execution"
    with pytest.raises(ValueError, match="interpretation"):
        workflow.save(detail["id"], draft)


def test_review_reopens_and_concurrent_revision_is_preserved(tmp_path):
    workflow = local(tmp_path)
    detail = observed(workflow)
    saved = workflow.save(detail["id"], review(detail, "draft"))
    assert saved["revision"] == 1
    reopened = TrainingWorkflow(workflow.registry, workflow.roles, workflow.market).detail(
        detail["id"]
    )
    assert reopened == saved
    with pytest.raises(ValueError, match="another view"):
        workflow.save(detail["id"], review(detail, "pending"))
    assert workflow.detail(detail["id"])["revision"] == 1


def test_task_aware_duplication_and_conflict_are_distinct():
    a = example()
    b = copy.deepcopy(a)
    b["candidate"]["packet"]["question"] = "Which next targeted uncertainty check is appropriate?"
    reseal(b["candidate"])
    args = dict(
        train_end=150.0,
        validation_end=250.0,
        embargo_seconds=10.0,
        protected_packets=[{"evidence": {"e0": "Unrelated public qualification fixture"}}],
        preparation_only=True,
    )
    report = preflight([a, b], **args)
    assert report["eligible"] and report["coverage"]["distinct_families"] == 1
    assert report["coverage"]["skills"]["cost_interpretation"]["examples"] == 0
    bundle = prepare([a, b], **args)
    assert len(bundle["files"]["train"]) == 2 and not bundle["files"]["test"]
    c = copy.deepcopy(a)
    c["candidate"]["task_id"] += "-duplicate"
    reseal(c["candidate"])
    c["target"] = c["target"] | {"action": "unsupported_capability"}
    report = preflight([a, c], **args)
    assert "conflicting_targets" in {p["code"] for p in report["problems"]}


def test_preflight_reports_metadata_and_unsupported_targets_together():
    bad = example()
    del bad["review"]["reviewer_kind"]
    bad["review"]["rights_confirmed"] = False
    bad["target"]["capability"] = "not-offered"
    bad["target"]["action"] = "propose_experiment"
    report = preflight(
        [bad],
        train_end=150.0,
        validation_end=250.0,
        embargo_seconds=0.0,
        protected_packets=[{"evidence": {"e0": "Unrelated fixture"}}],
        preparation_only=True,
    )
    assert {"review_metadata", "rights", "unsupported_target"} <= {
        p["code"] for p in report["problems"]
    }


def test_receipt_requires_expected_linkage_not_just_self_consistent_hash():
    expected = {
        "dataset_sha256": "a" * 64,
        "model_sha256": "b" * 64,
        "run_id": "run",
        "study_id": "study",
        "source_examples": ["original"],
    }
    cfg = {"profile": {"name": "Qwen3.5-4B"}, "lab_source_sha256": "c" * 64}
    request = {"expected": expected, "nonce": "owned"}
    receipt = {
        "format": "llm-lab-preparation-receipt-v1",
        "stage": "prepared",
        "trained": False,
        "evaluated": False,
        "nonce": "owned",
        "request_sha256": compact_digest(request),
        "profile_sha256": compact_digest(cfg["profile"]),
        "lab_source_sha256": cfg["lab_source_sha256"],
        **expected,
    }
    TrainingBridge.validate(receipt, request, cfg)
    for key in ("dataset_sha256", "model_sha256", "run_id", "study_id", "source_examples"):
        bad = receipt | {key: "different"}
        with pytest.raises(ValueError, match="linkage"):
            TrainingBridge.validate(bad, request, cfg)


def test_operator_access_scope_and_unsafe_identifiers(tmp_path):
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    with TestClient(app) as client:
        headers = {"X-Local-Operator": "1"}
        assert client.get("/api/lab/training").status_code == 403
        assert (
            client.get(
                "/api/lab/training", headers=headers | {"Origin": "https://evil.invalid"}
            ).status_code
            == 403
        )
        assert client.get("/api/lab/training", headers=headers).status_code == 200
        assert (
            client.post(
                "/api/lab/training/candidates",
                headers=headers,
                json={
                    "kind": "market_observation",
                    "identity": "file:///secret",
                    "question": "Read this unsupported external secret",
                    "author": "Test",
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/lab/training/candidates",
                headers=headers,
                json={"kind": "model_attempt", "identity": "test", "path": "C:/secret"},
            ).status_code
            == 422
        )
        assert (
            client.get("/api/lab/training/historical/unknown", headers=headers).status_code == 409
        )


def test_wrong_private_configuration_does_not_launch(tmp_path):
    config = tmp_path / "training-lab.json"
    config.write_text(json.dumps({"format": "untrusted-report"}))
    with pytest.raises(ValueError, match="Configure"):
        TrainingBridge(config).configuration()
    with pytest.raises(ValueError):
        TrainingBridge(config).reopen("../../secret")


def test_accepted_save_retry_preserves_exact_version_and_original_evidence(tmp_path):
    workflow = local(tmp_path)
    initial = observed(workflow)
    draft = review(initial)
    saved = workflow.save(initial["id"], draft)
    retried = workflow.save(initial["id"], draft)
    assert retried == saved and retried["revision"] == 1
    workflow.save(initial["id"], review(saved, "exclude"))
    frozen = workflow.detail(initial["id"], 1)
    assert frozen["historical_revision"] and frozen["current_revision"] == 2
    assert frozen["saved"] == saved["saved"]
    assert frozen["candidate"] == initial["candidate"]
    with pytest.raises(ValueError, match="unavailable"):
        workflow.detail(initial["id"], 999)


def test_failed_preparation_retries_once_without_overwriting_interrupted_attempt(
    tmp_path, monkeypatch
):
    workflow = local(tmp_path)
    detail = observed(workflow)
    workflow.save(detail["id"], review(detail))
    selection = DatasetSelection(ids=[detail["id"]], train_end=2e9, validation_end=2.1e9)
    calls = []

    def dispatch(request, bundle=None, job_id=None):
        if request["operation"] == "exposure":
            return {"problems": [], "limitations": []}, "exposure"
        calls.append(job_id)
        if len(calls) == 1:
            raise ValueError("Fixture interrupted import; no complete receipt")
        assert bundle["manifest"]["source_reviews"] == request["expected"]["source_reviews"]
        return {"study_id": request["expected"]["study_id"]}, job_id

    monkeypatch.setattr(workflow.bridge, "configuration", lambda: {"model_sha256": "b" * 64})
    monkeypatch.setattr(workflow.bridge, "dispatch", dispatch)
    failed = workflow.build(selection)
    assert failed["stage"] == "failed" and failed["attempts"][0]["stage"] == "failed"
    with pytest.raises(ValueError, match="explicit retry"):
        workflow.build(selection)
    succeeded = workflow.retry(failed["id"])
    assert succeeded["stage"] == "prepared" and len(succeeded["attempts"]) == 2
    assert succeeded["attempts"][0] == failed["attempts"][0]
    assert calls[0] != calls[1]
    monkeypatch.setattr(workflow.bridge, "reopen", lambda job: succeeded["receipt"])
    assert workflow.build(selection)["id"] == succeeded["id"]
    assert len(calls) == 2
    monkeypatch.setattr(
        workflow.bridge, "reopen", lambda job: (_ for _ in ()).throw(ValueError("Missing archive"))
    )
    unavailable = workflow.result(failed["id"])
    assert unavailable["archive_available"] is False
    assert unavailable["receipt"] == succeeded["receipt"]


def test_unavailable_lab_blocks_build_without_partial_acceptance(tmp_path):
    workflow = local(tmp_path)
    detail = observed(workflow)
    workflow.save(detail["id"], review(detail))
    selection = DatasetSelection(ids=[detail["id"]], train_end=2e9, validation_end=2.1e9)
    refused = workflow.build(selection)
    assert refused["stage"] == "refused"
    assert "lab_unavailable" in {p["code"] for p in refused["preflight"]["problems"]}
    assert not workflow.sources()["handoffs"]


def failed_handoff(tmp_path, monkeypatch):
    workflow = local(tmp_path)
    detail = observed(workflow)
    workflow.save(detail["id"], review(detail))
    selection = DatasetSelection(ids=[detail["id"]], train_end=2e9, validation_end=2.1e9)

    def dispatch(request, bundle=None, job_id=None):
        if request["operation"] == "exposure":
            return {"problems": [], "limitations": []}, "exposure"
        raise ValueError("Synthetic initial failed preparation")

    monkeypatch.setattr(workflow.bridge, "configuration", lambda: {"model_sha256": "b" * 64})
    monkeypatch.setattr(workflow.bridge, "dispatch", dispatch)
    return workflow, workflow.build(selection)


def test_independent_concurrent_retries_claim_one_attempt_before_dispatch(tmp_path, monkeypatch):
    workflow, failed = failed_handoff(tmp_path, monkeypatch)
    other = TrainingWorkflow(ExperimentRegistry(workflow.registry.path), None, workflow.market)
    barrier = threading.Barrier(2)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def dispatch(request, bundle=None, job_id=None):
        if request["operation"] == "exposure":
            return {"problems": [], "limitations": []}, "exposure"
        calls.append(job_id)
        entered.set()
        assert release.wait(5), "Synthetic bridge was not released"
        return {"study_id": failed["id"]}, job_id

    for owner in (workflow, other):
        claim = owner._claim_retry

        def overlap(state, claim=claim):
            barrier.wait(timeout=5)
            return claim(state)

        monkeypatch.setattr(owner, "_claim_retry", overlap)
        monkeypatch.setattr(owner.bridge, "dispatch", dispatch)
        monkeypatch.setattr(owner.bridge, "configuration", lambda: {"model_sha256": "b" * 64})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(owner.retry, failed["id"]) for owner in (workflow, other)]
        try:
            assert entered.wait(5)
            done, active = wait(futures, timeout=1)
            assert len(done) == len(active) == 1
            with pytest.raises(ValueError, match="bounded request window"):
                next(iter(done)).result()
            in_flight = other.result(failed["id"])
            assert in_flight["stage"] == "preparing"
            assert in_flight["attempts"][0] == failed["attempts"][0]
            assert len(in_flight["attempts"]) == 2 and len(calls) == 1
        finally:
            release.set()
        completed = next(iter(active)).result()
    assert completed["stage"] == "prepared"
    assert completed["attempts"][1]["job"] == calls[0]
    assert other.result(failed["id"])["attempts"] == completed["attempts"]


def test_initial_claim_and_attempt_commit_together_before_interrupted_dispatch(
    tmp_path, monkeypatch
):
    workflow = local(tmp_path)
    detail = observed(workflow)
    workflow.save(detail["id"], review(detail))
    selection = DatasetSelection(ids=[detail["id"]], train_end=2e9, validation_end=2.1e9)
    monkeypatch.setattr(workflow.bridge, "configuration", lambda: {"model_sha256": "b" * 64})
    monkeypatch.setattr(
        workflow.bridge, "dispatch", lambda *args: ({"problems": [], "limitations": []}, "exposure")
    )

    def stop(state, bundle, cfg):
        reopened = workflow.result(state["id"])
        assert reopened["stage"] == "preparing"
        assert reopened["attempts"] == state["attempts"] and len(state["attempts"]) == 1
        raise InterruptedError("Synthetic interruption before dispatch")

    monkeypatch.setattr(workflow, "_prepare", stop)
    with pytest.raises(InterruptedError):
        workflow.build(selection)
    handoff = workflow.sources()["handoffs"][0]
    with pytest.raises(ValueError, match="bounded request window"):
        workflow.retry(handoff["id"])


def test_legacy_empty_attempt_interruption_is_bounded_and_recovers(tmp_path, monkeypatch):
    workflow, failed = failed_handoff(tmp_path, monkeypatch)
    legacy = dict(failed, stage="preparing", attempts=[])
    with workflow.registry.transaction():
        workflow.registry.db.execute(
            "UPDATE training_handoffs SET body=?,created=? WHERE id=?",
            (json.dumps(legacy), time.time(), failed["id"]),
        )
    with pytest.raises(ValueError, match="bounded request window"):
        workflow.retry(failed["id"])
    assert workflow.result(failed["id"])["attempts"] == []
    with workflow.registry.transaction():
        workflow.registry.db.execute(
            "UPDATE training_handoffs SET created=? WHERE id=?", (time.time() - 191, failed["id"])
        )

    def dispatch(request, bundle=None, job_id=None):
        if request["operation"] == "exposure":
            return {"problems": [], "limitations": []}, "exposure"
        return {"study_id": failed["id"]}, job_id

    monkeypatch.setattr(workflow.bridge, "dispatch", dispatch)
    repaired = workflow.retry(failed["id"])
    assert repaired["stage"] == "prepared" and len(repaired["attempts"]) == 1
    assert "Legacy handoff" in repaired["recovery"]["reason"]


@pytest.mark.parametrize("newer_finished", [False, True])
@pytest.mark.parametrize("late_failure", [False, True])
def test_late_completion_preserves_newer_claim_and_entire_history(
    tmp_path, monkeypatch, late_failure, newer_finished
):
    workflow, failed = failed_handoff(tmp_path, monkeypatch)
    old = workflow._claim_retry(failed)
    older_job = old["attempts"][-1]["job"]
    old["attempts"][-1]["at"] = time.time() - 191
    with workflow.registry.transaction():
        workflow.registry.db.execute(
            "UPDATE training_handoffs SET body=? WHERE id=?", (json.dumps(old), old["id"])
        )
    newer = workflow._claim_retry(old)
    latest_job = newer["attempts"][-1]["job"]
    receipt = {"study_id": failed["id"], "run_id": latest_job}
    if newer_finished:
        workflow._finish(failed["id"], latest_job, receipt=receipt)
    if late_failure:
        final = workflow._finish(failed["id"], older_job, reason="Synthetic late failure")
    else:
        final = workflow._finish(failed["id"], older_job, receipt={"run_id": older_job})
    if newer_finished:
        assert final["stage"] == "prepared" and final["receipt"] == receipt
        assert final["job_id"] == latest_job
    else:
        assert final["stage"] == "preparing" and "receipt" not in final
    assert len(final["attempts"]) == 3
    assert final["attempts"][0] == failed["attempts"][0]
    assert final["attempts"][1]["job"] == older_job
    assert final["attempts"][1]["superseded"] and final["attempts"][1]["interrupted_at"]
    assert final["attempts"][2]["job"] == latest_job


def test_claim_rechecks_review_fingerprint_before_dispatch(tmp_path, monkeypatch):
    workflow, failed = failed_handoff(tmp_path, monkeypatch)
    identity = failed["source_examples"][0]
    workflow.save(identity, review(workflow.detail(identity), "pending"))
    with pytest.raises(ValueError, match="Reviewed selection changed"):
        workflow._claim_retry(failed)
    assert workflow.result(failed["id"])["attempts"] == failed["attempts"]


def test_bearer_access_and_oversized_review_cannot_write(tmp_path):
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/lab/training",
                headers={"X-Local-Operator": "1", "Authorization": "Bearer reader"},
            ).status_code
            == 403
        )
        response = client.post(
            "/api/lab/training/examples/unknown/review",
            headers={"X-Local-Operator": "1"},
            json={
                "revision": 0,
                "disposition": "draft",
                "lesson": "Oversized fixture",
                "reason": "x" * 400000,
                "target": {},
                "review": {},
                "rights_reason": "",
            },
        )
        assert response.status_code in {413, 422}
