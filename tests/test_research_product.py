"""Product reads and reviewed startup; isolated owners, no actual inference."""

import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest
from test_pattern_role_worker import build_pattern_worker_fixture, rows, select
from test_peft_development import declared as declared
from test_peft_paper_pilot import pilot as pilot

from trading.lab_role_contract import PATTERN_VERSION, contract_hash, pattern_method_policy_sha
from trading.peft_profile import digest
from trading.peft_role_model import (
    PAPER_PILOT_PATTERN_METHOD_FORMAT,
    PATTERN_METHOD_QUESTION_POLICY,
    configure_paper_scope,
    local_role_transport,
    prepare_paper_scope,
)
from trading.research_notices import ResearchNotices
from trading.research_overview import SupervisedStart, snapshot, start


def automatic_pilot(pilot, monkeypatch):
    model, grant, development, *_ = pilot
    profile = development.declaration()[2] | {
        "role_contract": PATTERN_VERSION,
        "contract_sha256": contract_hash(PATTERN_VERSION),
    }
    changed = grant | {
        "format": PAPER_PILOT_PATTERN_METHOD_FORMAT,
        "enabled": False,
        "role_contract": PATTERN_VERSION,
        "question_policy": PATTERN_METHOD_QUESTION_POLICY,
        "method_policy_sha256": pattern_method_policy_sha(),
        "profile_sha256": digest(profile),
    }
    model.policy_path.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(model, "_protected", lambda: {"admitted": True})
    return model, changed


def test_overview_reads_do_not_select_dispatch_disclose_or_change_financial_state(
    tmp_path, monkeypatch
):
    f, worker, _ = build_pattern_worker_fixture(tmp_path, monkeypatch)
    task = select(f, worker)
    notices = ResearchNotices(f.registry)
    lab = SimpleNamespace(
        roles=worker, autonomous=worker.controller, notices=notices, notice_error=None
    )
    before = copy.deepcopy(f.paper.state)
    tasks, attempts = rows(worker, "role_tasks"), rows(worker, "role_attempts")
    exposures = f.registry.db.execute("SELECT * FROM evidence_windows").fetchall()
    monkeypatch.setattr(worker, "view", lambda _: pytest.fail("Overview read task detail"))
    monkeypatch.setattr(
        worker, "select_fresh_question", lambda *_: pytest.fail("Read selected work")
    )
    for _ in range(3):
        value = snapshot(lab, f.scanner)
        assert value["research"]["available"] is True
        assert value["research"]["data"]["tasks"][0]["id"] == task["id"]
        assert value["research"]["data"]["tasks"][0]["created"] == task["created"]
        assert "evidence" not in value["research"]["data"]["question_selection"]
        assert value["scope"]["available"] is False  # This fixture is not a real operating grant.
    assert rows(worker, "role_tasks") == tasks and rows(worker, "role_attempts") == attempts
    assert f.registry.db.execute("SELECT * FROM evidence_windows").fetchall() == exposures
    assert f.paper.state == before and not worker.transport.calls
    f.registry.close()


def test_component_failure_is_unavailable_without_erasing_other_owner_observations(
    tmp_path, monkeypatch
):
    f, worker, _ = build_pattern_worker_fixture(tmp_path, monkeypatch)
    select(f, worker)
    lab = SimpleNamespace(
        roles=worker,
        autonomous=worker.controller,
        notices=ResearchNotices(f.registry),
        notice_error=None,
    )

    def fail():
        raise sqlite3.OperationalError("database temporarily unavailable")

    monkeypatch.setattr(worker, "page", fail)
    value = snapshot(lab, f.scanner)
    assert value["research"]["available"] is False and value["research"]["data"] is None
    assert value["markets"]["available"] is True
    assert value["attention"]["available"] is True
    assert "database temporarily unavailable" not in json.dumps(value)
    f.registry.close()


def test_overview_retains_waiting_investigation_beyond_recent_terminal_history(
    tmp_path, monkeypatch
):
    f, worker, _ = build_pattern_worker_fixture(tmp_path, monkeypatch)
    task = select(f, worker)
    assert worker._update(task, "outcome", status="waiting", reason="Original result is not mature")
    # Metadata-only terminal-history fixture; no dispatch, proposal or financial effects.
    with f.registry.transaction():
        for i in range(24):
            f.registry.db.execute(
                "INSERT INTO role_tasks(id,created,updated,stage,status,reason,context,"
                "question_text) "
                "VALUES(?,?,?,'complete','done',NULL,'{}',?)",
                (
                    "terminal-metadata-" + str(i),
                    f.now + i + 1,
                    f.now + i + 1,
                    "Retained old decision",
                ),
            )
    lab = SimpleNamespace(
        roles=worker,
        autonomous=worker.controller,
        notices=ResearchNotices(f.registry),
        notice_error=None,
    )
    before = rows(worker, "role_tasks")
    value = snapshot(lab, f.scanner)["research"]["data"]
    assert value["current_task"] is None
    assert all(row["id"] != task["id"] for row in value["tasks"])
    assert [row["id"] for row in value["active_tasks"]] == [task["id"]]
    assert value["active_tasks"][0]["stage"] == "outcome"
    assert value["active_tasks"][0]["reason"] == "Original result is not mature"
    assert "context" not in value["active_tasks"][0]
    assert rows(worker, "role_tasks") == before and not worker.transport.calls
    f.close()


def test_reviewed_scope_preserves_original_manual_grant_and_private_paths(pilot):
    model, grant, *_ = pilot
    scope = model.reviewed_scope()
    assert scope["automatic_questions"] is False
    assert scope["model_cost_usd"] is None
    assert str(grant["development_directory"]) not in json.dumps(scope)
    with pytest.raises(ValueError, match="automatic"):
        model.start_reviewed_scope(scope["identity"], scope["control_revision"])
    assert json.loads(model.policy_path.read_text())["enabled"] is True


def test_approved_scope_resume_is_idempotent_and_reopens_with_saved_intent(pilot, monkeypatch):
    model, grant = automatic_pilot(pilot, monkeypatch)
    scope = model.reviewed_scope()
    assert scope["configured_enabled"] is False and scope["methods"] == [
        "Breakout retest",
        "Trend pullback",
    ]
    model.start_reviewed_scope(scope["identity"], scope["control_revision"])
    assert json.loads(model.policy_path.read_text()) == grant | {"enabled": True}
    original = model.policy_path.read_bytes()
    model.start_reviewed_scope(scope["identity"], scope["control_revision"])
    assert model.policy_path.read_bytes() == original
    from trading.peft_role_model import PeftPaperPilotRoles

    reopened = PeftPaperPilotRoles(model.policy_path.parent)
    assert reopened.reviewed_scope()["identity"] == scope["identity"]
    assert reopened.reviewed_scope()["configured_enabled"] is True
    model.set_enabled(False)
    assert (
        PeftPaperPilotRoles(model.policy_path.parent).reviewed_scope()["configured_enabled"]
        is False
    )


def test_changed_scope_and_closed_guard_refuse_before_activation(pilot, monkeypatch):
    model, grant = automatic_pilot(pilot, monkeypatch)
    scope = model.reviewed_scope()
    model.policy_path.write_text(
        json.dumps(grant | {"grant_id": "other-reviewed-scope"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="changed"):
        model.start_reviewed_scope(scope["identity"], scope["control_revision"])
    assert json.loads(model.policy_path.read_text())["enabled"] is False
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    monkeypatch.setattr(model, "_protected", lambda: {"admitted": False})
    with pytest.raises(ValueError, match="admission"):
        model.start_reviewed_scope(
            model.reviewed_scope()["identity"], model.reviewed_scope()["control_revision"]
        )
    assert model.policy_path.read_bytes() == json.dumps(grant).encode()


class ComparisonOwner:
    """Orchestration callback only; separate native financial tests cover the writer."""

    def __init__(self):
        self.policy = {"request_id": "saved-comparison-policy", "starting_cash": "100"}
        self.paused = True
        self.calls = []

    def snapshot(self):
        return {
            "lab": {
                "policy": self.policy,
                "proposals_paused": self.paused,
                "entries_paused": True,
                "control_revision": 0,
            },
            "slots": {"used": 6, "capacity": 20},
        }

    def control(self, action, target, **kwargs):
        self.calls.append((action, target, kwargs))
        self.paused = False


def test_partial_startup_reconciles_existing_components_without_new_policy(pilot, monkeypatch):
    model, grant = automatic_pilot(pilot, monkeypatch)
    controller = ComparisonOwner()
    lab = SimpleNamespace(roles=SimpleNamespace(transport=model), autonomous=controller)
    from trading.experiment_registry import fingerprint

    scope = model.reviewed_scope()
    command = SupervisedStart(
        scope_identity=scope["identity"],
        control_revision=scope["control_revision"],
        policy_identity=fingerprint(controller.policy),
        comparison_revision=0,
        resume_comparisons=True,
    )
    monkeypatch.setattr(model, "_protected", lambda: {"admitted": False})
    result = start(lab, command)
    assert result["components"][0]["state"] == "saved" and controller.paused is False
    assert result["components"][1]["state"] == "rejected"
    assert json.loads(model.policy_path.read_text())["enabled"] is False
    monkeypatch.setattr(model, "_protected", lambda: {"admitted": True})
    result = start(lab, command)
    assert result["components"][-1]["state"] == "saved"
    assert json.loads(model.policy_path.read_text()) == grant | {"enabled": True}
    assert controller.policy["request_id"] == "saved-comparison-policy"
    assert len(controller.calls) == 1


def test_policy_changed_or_unreviewed_pause_refuses_all_startup_effects(pilot, monkeypatch):
    model, _ = automatic_pilot(pilot, monkeypatch)
    controller = ComparisonOwner()
    lab = SimpleNamespace(roles=SimpleNamespace(transport=model), autonomous=controller)
    from trading.experiment_registry import fingerprint

    scope = model.reviewed_scope()
    command = SupervisedStart(
        scope_identity=scope["identity"],
        control_revision=scope["control_revision"],
        policy_identity=fingerprint(controller.policy),
        comparison_revision=0,
    )
    with pytest.raises(ValueError, match="paused"):
        start(lab, command)
    with pytest.raises(ValueError, match="changed"):
        start(
            lab,
            command.model_copy(update={"policy_identity": "f" * 64, "resume_comparisons": True}),
        )
    assert not controller.calls
    assert model.reviewed_scope()["configured_enabled"] is False


def test_newer_pause_wins_over_in_flight_startup_even_when_already_paused(pilot, monkeypatch):
    model, _ = automatic_pilot(pilot, monkeypatch)
    controller = ComparisonOwner()
    lab = SimpleNamespace(roles=SimpleNamespace(transport=model), autonomous=controller)
    from trading.experiment_registry import fingerprint

    scope = model.reviewed_scope()
    command = SupervisedStart(
        scope_identity=scope["identity"],
        control_revision=scope["control_revision"],
        policy_identity=fingerprint(controller.policy),
        comparison_revision=0,
        resume_comparisons=True,
    )
    original_control = controller.control

    def pause_after_comparison(*args, **kwargs):
        original_control(*args, **kwargs)
        model.set_enabled(False)  # A distinct, later user decision.

    monkeypatch.setattr(controller, "control", pause_after_comparison)
    result = start(lab, command)
    assert result["components"][-1]["state"] == "rejected"
    assert "newer research control" in result["components"][-1]["reason"]
    assert not model.reviewed_scope()["configured_enabled"]


def test_lost_model_ack_is_unconfirmed_but_saved_intent_reconciles_without_rewrite(
    pilot, monkeypatch
):
    model, _ = automatic_pilot(pilot, monkeypatch)
    controller = ComparisonOwner()
    lab = SimpleNamespace(roles=SimpleNamespace(transport=model), autonomous=controller)
    from trading.experiment_registry import fingerprint

    scope = model.reviewed_scope()
    command = SupervisedStart(
        scope_identity=scope["identity"],
        control_revision=scope["control_revision"],
        policy_identity=fingerprint(controller.policy),
        comparison_revision=0,
        resume_comparisons=True,
    )
    original = model.start_reviewed_scope

    def lose_ack(*args):
        original(*args)
        raise OSError("connection lost after saved intent")

    monkeypatch.setattr(model, "start_reviewed_scope", lose_ack)
    assert start(lab, command)["components"][-1]["state"] == "unconfirmed"
    saved = model.reviewed_scope()["control_revision"]
    monkeypatch.setattr(model, "start_reviewed_scope", original)
    assert start(lab, command)["components"][-1]["state"] == "saved"
    assert model.reviewed_scope()["control_revision"] == saved and len(controller.calls) == 1


def test_new_configuration_reuses_existing_verified_profile_and_remains_paused(declared, tmp_path):
    development, *_ = declared
    directory = tmp_path / "new-application"
    directory.mkdir()
    review = prepare_paper_scope(directory, str(development.directory))
    assert not (directory / "role-policy.json").exists()
    with pytest.raises(ValueError, match="changed"):
        configure_paper_scope(directory, str(development.directory), "f" * 64)
    receipt = configure_paper_scope(
        directory, str(development.directory), review["review_identity"]
    )
    assert receipt == {"status": "saved", "enabled": False, "requires_restart": True}
    model = local_role_transport(directory)
    assert (
        model.reviewed_scope()["automatic_questions"]
        and not model.reviewed_scope()["configured_enabled"]
    )
    revision = model.reviewed_scope()["control_revision"]
    receipt = configure_paper_scope(
        directory, str(development.directory), review["review_identity"]
    )
    assert receipt["status"] == "already_applied"
    assert model.reviewed_scope()["control_revision"] == revision
    assert not list(directory.glob("*.tmp"))


def test_setup_cannot_replace_or_extend_an_existing_permission(pilot):
    model, grant, development, *_ = pilot
    before = model.policy_path.read_bytes()
    with pytest.raises(ValueError, match="cannot replace or extend"):
        prepare_paper_scope(model.policy_path.parent, str(development.directory))
    assert model.policy_path.read_bytes() == before and model._grant() == grant


def test_expired_scope_stays_inspectable_but_never_resumes(pilot, monkeypatch):
    model, grant = automatic_pilot(pilot, monkeypatch)
    from trading.peft_role_model import PAPER_PILOT_FINITE_FORMAT

    # The validated grant helper is already exercised by the finite-owner suite.
    # This metadata test isolates the owner's real expiry refusal from validation.
    finite = grant | {
        "format": PAPER_PILOT_FINITE_FORMAT,
        "finite_test": {"not_before": 10, "expires_at": 20, "max_requests": 3},
    }
    monkeypatch.setattr(model, "_grant", lambda: finite)
    monkeypatch.setattr(
        model,
        "declaration",
        lambda: (
            None,
            None,
            {"hourly_tokens": 100, "hourly_wall_seconds": 60, "timeout_seconds": 30},
        ),
    )

    def expired(_):
        raise ValueError("Original finite paper test expired; no renewal")

    monkeypatch.setattr(model, "_finite_time", expired)
    scope = model.reviewed_scope()
    assert scope["finite_test"] == finite["finite_test"]
    assert "expired" in scope["start_refusal"]
    with pytest.raises(ValueError, match="expired"):
        model.start_reviewed_scope(scope["identity"], scope["control_revision"])
    assert model.policy_path.read_bytes() == json.dumps(grant).encode()
