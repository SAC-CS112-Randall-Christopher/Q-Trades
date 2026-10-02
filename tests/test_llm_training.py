"""Synthetic pipeline verification; no actual model training or blind acceptance data."""

import copy
import json
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from trading.api import create_app
from trading.config import Settings
from trading.experiment_registry import fingerprint
from trading.lab_role_contract import VERSION
from trading.llm_training import (
    MAX_INPUT_BYTES,
    Candidate,
    Example,
    candidate_from_task,
    load_jsonl,
    prepare,
    verify_bundle,
    write_bundle,
)
from trading.llm_training_eval import compare, score

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "llm_training_pilot.py"


def task(
    at=100.0, role="researcher", facts="Synthetic costs exceed the measured gross difference."
):
    stage = "review" if role == "reviewer" else "idea"
    packet = {
        "question": "What does this synthetic method check support?",
        "evidence": {"e0": {"facts": facts}},
        "capabilities": {},
    }
    answer = {
        "action": "no_change",
        "evidence_ids": ["e0"],
        "capability": None,
        "mechanism": "Retain the unchanged synthetic research method.",
        "falsification": "A new independent observation would change this question.",
        "rationale": "There is no new support for repeating an unchanged method.",
        "dependency": None,
    }
    if role == "reviewer":
        answer = {
            "action": "reject",
            "evidence_ids": ["e0"],
            "issues": ["unsupported_claim"],
            "rationale": "The claimed benefit is not supported by this synthetic evidence.",
        }
    return {
        "id": f"synthetic-task-{role}-{at}",
        "context": {
            "contract": VERSION,
            "question": {"parent": None},
            "issued": {"sha256": fingerprint(packet)},
        },
        "attempts": [
            {
                "stage": stage,
                "attempt": 1,
                "started": at,
                "finished": at + 1,
                "packet": json.dumps(packet),
                "response": json.dumps({"answer": answer}),
                "profile": {"never_export": "private-profile-placeholder"},
            }
        ],
    }


def example(at=100.0, role="researcher", facts="Synthetic first scenario overstates results."):
    original = task(at, role, facts)
    exported = candidate_from_task(original, "review" if role == "reviewer" else "idea", 1)
    return {
        "candidate": exported["candidate"],
        "review": {
            "approved": True,
            "reviewer": "Synthetic software-test author; not operator approval",
            "reviewed_at": at + 2,
            "rationale": "Procedural test fixture, not market evidence.",
            "rights_confirmed": True,
            "data_basis": "synthetic",
            "family_ids": ["synthetic-family-" + str(at)],
            "categories": ["workflow"],
            "episode_start": at - 5,
            "episode_end": at - 1,
            "target_available_at": at - 1,
            "evidence_available_at": {"e0": at - 1},
        },
        "target": exported["candidate"]["original_answer"],
    }


def corpus():
    return [
        example(100.0, facts="Synthetic first scenario overstates results."),
        example(200.0, "reviewer", "A toy instrument has no valid executable observation."),
        example(
            300.0, facts="Artificial portfolio scenario records an unchanged completed question."
        ),
    ]


def prepared(rows=None):
    return prepare(
        rows or corpus(),
        train_end=150.0,
        validation_end=250.0,
        embargo_seconds=10.0,
        protected_packets=[{"evidence": {"e0": {"facts": "Reserved unrelated test."}}}],
    )


def reseal(candidate):
    candidate["packet_sha256"] = fingerprint(candidate["packet"])
    candidate["candidate_sha256"] = fingerprint(
        {k: v for k, v in candidate.items() if k != "candidate_sha256"}
    )


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
    )


def test_export_preserves_original_bad_answer_and_never_approves():
    original = task()
    original["attempts"][0]["response"] = json.dumps({"answer": {"funding": "not permitted"}})
    before = copy.deepcopy(original)
    exported = candidate_from_task(original, "idea", 1)
    assert exported["candidate"]["original_answer"] == {"funding": "not permitted"}
    assert exported["candidate"]["packet"] == json.loads(original["attempts"][0]["packet"])
    assert exported["review"] is None and exported["target"] is None
    assert "private-profile-placeholder" not in json.dumps(exported)
    assert original == before
    with pytest.raises(ValueError):
        Example.model_validate(exported)


@pytest.mark.parametrize(
    "change",
    [
        lambda t: t["attempts"][0].update(finished=None),
        lambda t: t["attempts"][0].update(response=None),
        lambda t: t["context"].update(contract="old-contract"),
        lambda t: t.update(attempts=[]),
        lambda t: t["attempts"].append(copy.deepcopy(t["attempts"][0])),
        lambda t: t["attempts"][0].update(finished=1),
    ],
)
def test_incomplete_stale_or_ambiguous_attempt_refused(change):
    original = task()
    change(original)
    with pytest.raises(ValueError):
        candidate_from_task(original, "idea", 1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved", False),
        ("rights_confirmed", False),
        ("family_ids", []),
        ("target_available_at", 101.0),
        ("evidence_available_at", {"e0": 101.0}),
        ("evidence_available_at", {}),
        ("episode_end", 101.0),
        ("episode_start", 102.0),
        ("reviewed_at", 99.0),
        ("evidence_available_at", {"e0": float("nan")}),
    ],
)
def test_adjudication_rejects_missing_review_future_or_unavailable_facts(field, value):
    row = example()
    row["review"][field] = value
    with pytest.raises(ValueError):
        Example.model_validate(row)


def test_corrected_target_keeps_original_and_uses_current_validator():
    row = example()
    row["candidate"]["original_answer"] = {"action": "buy_now", "funding": "999"}
    reseal(row["candidate"])
    assert Example.model_validate(row).target["action"] == "no_change"
    row["target"]["evidence_ids"] = ["invented"]
    with pytest.raises(ValueError, match="evidence"):
        Example.model_validate(row)


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_answer", {"changed": True}),
        ("task_id", "another-task"),
        ("contract_sha256", "0" * 64),
        ("role", "reviewer"),
    ],
)
def test_changed_candidate_refused(field, value):
    row = example()["candidate"]
    row[field] = value
    with pytest.raises(ValueError):
        Candidate.model_validate(row)


def test_reproducible_chronological_prompt_completion_and_reopen(tmp_path):
    first = prepared()
    assert first == prepared(list(reversed(corpus())))
    assert first["manifest"]["counts"] == {"train": 1, "validation": 1, "test": 1}
    assert first["files"]["train"][0]["prompt"][0]["role"] == "system"
    assert "reviewer" not in first["files"]["train"][0]
    assert "original_answer" not in first["files"]["train"][0]
    destination = tmp_path / "private-corpus"
    manifest = write_bundle(first, destination)
    assert verify_bundle(destination) == manifest
    assert len(load_jsonl(destination / "train.jsonl")) == 1
    with pytest.raises(FileExistsError):
        write_bundle(first, destination)
    (destination / "train.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        verify_bundle(destination)


@pytest.mark.parametrize(
    "change",
    [
        lambda rows: rows.append(copy.deepcopy(rows[0])),
        lambda rows: rows[1]["review"].update(family_ids=rows[0]["review"]["family_ids"]),
        lambda rows: rows[1]["review"].update(episode_start=155.0),
    ],
)
def test_duplicate_family_and_embargo_refused(change):
    rows = corpus()
    change(rows)
    with pytest.raises(ValueError):
        prepared(rows)


def test_same_task_different_seeds_cannot_cross_splits():
    rows = corpus()
    rows[1]["candidate"]["group_ids"] = rows[0]["candidate"]["group_ids"]
    reseal(rows[1]["candidate"])
    with pytest.raises(ValueError, match="family"):
        prepared(rows)


def test_opaque_handle_renaming_does_not_hide_evidence_copy():
    rows = corpus()
    rows[1]["candidate"]["packet"]["evidence"] = {
        "renamed": rows[0]["candidate"]["packet"]["evidence"]["e0"]
    }
    rows[1]["target"]["evidence_ids"] = ["renamed"]
    rows[1]["review"]["evidence_available_at"] = {"renamed": 199.0}
    reseal(rows[1]["candidate"])
    with pytest.raises(ValueError, match="Duplicate evidence"):
        prepared(rows)


def test_near_copy_across_splits_refused():
    text = (
        "A synthetic hypothetical instrument has a missing current quote and sufficient "
        "closed bars but its comparison is still waiting for source availability."
    )
    rows = corpus()
    rows[0] = example(100.0, facts=text)
    rows[1] = example(200.0, "reviewer", text + " Extra irrelevant comment.")
    with pytest.raises(ValueError, match="Near-copy"):
        prepared(rows)


def test_current_public_qualification_packets_cannot_become_training_rows():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from llm_training_pilot import protected_packets

        packets = protected_packets()
    finally:
        sys.path.pop(0)
    rows = corpus()
    rows[0]["candidate"]["packet"] = packets[0]
    reseal(rows[0]["candidate"])
    with pytest.raises(ValueError, match="Protected"):
        prepare(
            rows,
            train_end=150.0,
            validation_end=250.0,
            embargo_seconds=10.0,
            protected_packets=packets,
        )


def test_incomplete_export_and_git_destination_refused(tmp_path):
    with pytest.raises(ValueError, match="manifest"):
        verify_bundle(tmp_path)
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="repositories"):
        write_bundle(prepared(), tmp_path / "private")


def test_jsonl_bounds_and_nonfinite_refusal(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text('{"data":NaN}\n')
    with pytest.raises(ValueError, match="row"):
        load_jsonl(path)
    path.write_text("[]\n")
    with pytest.raises(ValueError):
        load_jsonl(path)
    with path.open("wb") as stream:
        stream.truncate(MAX_INPUT_BYTES + 1)
    with pytest.raises(ValueError, match="64 MiB"):
        load_jsonl(path)


def test_cli_review_build_verify_no_model_or_database(tmp_path):
    exported = candidate_from_task(task(), "idea", 1)
    candidate_file = tmp_path / "candidate.json"
    candidate_file.write_text(json.dumps(exported))
    review_file = tmp_path / "adjudication.json"
    assert run_cli("review-template", candidate_file, review_file).returncode == 0
    adjudication = json.loads(review_file.read_text())
    assert adjudication["target"] is None and not adjudication["review"]["approved"]
    reviewed_file = tmp_path / "reviewed.jsonl"
    assert run_cli("review", candidate_file, review_file, reviewed_file).returncode == 2
    row = example(facts="Synthetic costs exceed the measured gross difference.")
    adjudication.update(review=row["review"], target=row["target"])
    review_file.write_text(json.dumps(adjudication))
    result = run_cli("review", candidate_file, review_file, reviewed_file)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(reviewed_file.read_text()), *corpus()[1:]]
    full = tmp_path / "corpus.jsonl"
    full.write_text("".join(json.dumps(r) + "\n" for r in rows))
    dest = tmp_path / "built"
    result = run_cli(
        "build", full, dest, "--train-end", 150, "--validation-end", 250, "--embargo-seconds", 10
    )
    assert result.returncode == 0, result.stderr
    assert run_cli("verify", dest).returncode == 0
    assert not (tmp_path / "role-policy.json").exists()


def test_paired_score_retains_missing_timeouts_unsafe_approvals_and_rejects_retries():
    rows = [corpus()[1]]
    c = rows[0]["candidate"]
    base = {
        "id": c["candidate_sha256"],
        "seed": 1,
        "split": "validation",
        "corpus_sha256": "1" * 64,
        "profile_sha256": "2" * 64,
        "status": "complete",
        "answer": rows[0]["target"],
        "tokens": 25,
        "wall_seconds": 1.0,
    }
    common = dict(corpus_sha256="1" * 64, split="validation", seeds=[1, 2])
    baseline = score(rows, [base], profile_sha256="2" * 64, **common)
    assert baseline["roles"]["reviewer"]["matched"] == 1
    assert baseline["roles"]["reviewer"]["requested"] == 2
    assert baseline["roles"]["reviewer"]["missing"] == 1
    unsafe = base | {
        "profile_sha256": "3" * 64,
        "answer": base["answer"] | {"action": "exploratory_paper_only", "issues": []},
    }
    candidate = score(rows, [unsafe], profile_sha256="3" * 64, **common)
    assert candidate["roles"]["reviewer"]["critical"] == 1
    assert not candidate["qualified"]
    assert compare(baseline, candidate)["delta"]["reviewer"]["critical"] == 1
    with pytest.raises(ValueError, match="Duplicate"):
        score(rows, [base, base], profile_sha256="2" * 64, **common)
    with pytest.raises(ValueError, match="different"):
        score(rows, [unsafe], profile_sha256="2" * 64, **common)
    timeout = base | {"status": "timeout", "answer": None}
    assert (
        score(rows, [timeout], profile_sha256="2" * 64, **common)["roles"]["reviewer"]["complete"]
        == 0
    )


def test_private_export_api_authorization_no_cache_and_retry(tmp_path):
    app = create_app(Settings(), tmp_path / "api-data", background=False)
    calls = []
    failure = [False]

    def export(identity, stage, attempt):
        calls.append((identity, stage, attempt))
        if failure[0]:
            raise ValueError("Original archive unavailable")
        return candidate_from_task(task(), stage, attempt)

    with TestClient(app) as client:
        app.state.lab = SimpleNamespace(roles=SimpleNamespace(training_candidate=export))
        url = "/api/lab/roles/tasks/test/training-candidate?stage=idea&attempt=1"
        assert client.get(url).status_code == 403
        headers = {"X-Local-Operator": "1"}
        assert (
            client.get(url, headers=headers | {"Origin": "https://evil.example"}).status_code == 403
        )
        response = client.get(url, headers=headers)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert response.json()["review"] is None
        assert len(calls) == 1
        failure[0] = True
        assert client.get(url, headers=headers).status_code == 409
        failure[0] = False
        assert client.get(url, headers=headers).status_code == 200
        assert (
            client.get(url.replace("stage=idea", "stage=financial"), headers=headers).status_code
            == 422
        )
        app.state.lab = None


def test_cli_requirements_only_checkout_without_editable_install():
    # -S excludes .pth/editable hooks; expose dependencies, but not project src.
    command = (
        "import runpy, sys; "
        "sys.path.append(sys.argv[1]); "
        "sys.path.insert(0, sys.argv[2]); "
        "script = sys.argv[3]; sys.argv = [script, '--help']; "
        "runpy.run_path(script, run_name='__main__')"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            command,
            sysconfig.get_path("purelib"),
            str(CLI.parent),
            str(CLI),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "review-template" in result.stdout and "compare" in result.stdout
