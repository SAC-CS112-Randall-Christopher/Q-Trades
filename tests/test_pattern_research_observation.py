"""Used-p0 read-only observations through real disposable scanner/Lab/archive owners."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from pydantic import ValidationError
from test_pattern_comparisons import build_fixture, command

from trading.autonomous_spec import LabProposal, RuleSpec
from trading.experiment_registry import fingerprint
from trading.pattern_comparisons import PatternComparisonCommand, PatternComparisons
from trading.research_evidence import digest


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    f, bridge, selection = build_fixture(tmp_path, monkeypatch)
    try:
        yield f, bridge, selection
    finally:
        f.close()


def used(f, bridge, selection):
    """The real inbox creates the marker; this fixture never reserves/funds a trial."""
    normal = bridge.prepare(command(bridge, selection, "observation-original-0001"), f.now)
    assert normal["status"] == "supported"
    accepted = bridge.controller.submit(LabProposal.model_validate(normal["proposal"]), f.now)
    assert accepted["status"] == "evaluated"
    assert bridge.controller.inbox.used(fingerprint(accepted["body"]["strategy"]))
    return normal


def inbox_rows(f):
    return [tuple(row) for row in f.registry.db.execute("SELECT * FROM lab_proposals ORDER BY seq")]


def test_readonly_used_p0_retains_actual_inputs_without_submission_proposals(fixture):
    f, bridge, selection = fixture
    original = used(f, bridge, selection)
    before, calls = inbox_rows(f), copy.deepcopy(f.calls)
    state = copy.deepcopy(f.paper.state)
    intent = command(bridge, selection, "observation-research-0002")
    receipt = bridge.prepare(intent, f.now, research_only=True)
    assert receipt["status"] == "research_only"
    assert receipt["evaluation"]["status"] == "supported_research_observation"
    assert receipt["research_only"] is True
    assert receipt["dispatch_available"] is False and "already-used" in receipt["dispatch_reason"]
    assert receipt["proposal"] is None
    assert receipt["submitted"] is False and receipt["financial_authority"] is False
    template = receipt["readonly_comparison_template"]
    assert template["strategy"] == original["proposal"]["strategy"]
    assert template["reference"] == original["proposal"]["reference"]
    assert "evidence_bundle_sha256" not in template
    assert LabProposal.model_validate(
        {**template, "evidence_bundle_sha256": receipt["issued_bundle_sha256"]}
    )
    proof = receipt["evaluation"]["matched_inputs"]
    inputs = bridge.execution_inputs(proof, intent.request_id)
    assert proof["count"] == len(inputs) == 600 and len(proof["references"]) == 2
    assert proof["sha256"] == original["evaluation"]["matched_inputs"]["sha256"]
    assert receipt["finding"] == original["finding"]
    for name in ("candidate", "reference"):
        actual = receipt["evaluation"]["controls"][name]
        previous = original["evaluation"]["controls"][name]
        assert "proposal" not in actual
        assert "evidence_bundle_sha256" not in actual["proposal_without_bundle_digest"]
        assert {k: v for k, v in actual.items() if k != "proposal_without_bundle_digest"} == {
            k: v for k, v in previous.items() if k != "proposal"
        }
    body = json.loads(
        f.registry.db.execute(
            "SELECT body FROM lab_bundles WHERE sha256=?", (receipt["issued_bundle_sha256"],)
        ).fetchone()[0]
    )
    assert body["proposal_without_bundle_digest"] is None
    assert body["readonly_comparison_template"] == template
    assert receipt["intent_sha256"] == digest(
        {"command": intent.model_dump(), "research_only": True}
    )
    assert receipt["intent_sha256"] != digest(intent.model_dump())
    assert inbox_rows(f) == before and f.paper.state == state and f.calls == calls


def test_default_intent_fields_control_hydration_and_used_gate_remain_original(fixture):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    original = bridge.prepare(intent, f.now)
    assert bridge.prepare(intent, f.now, research_only=False) == original
    assert original["intent_sha256"] == digest(intent.model_dump())
    assert set(original) == {
        "version",
        "request_id",
        "intent_sha256",
        "finding_sha256",
        "finding",
        "mapping",
        "prepared_at",
        "current_policy_sha256",
        "status",
        "reason",
        "proposal",
        "evaluation",
        "financial_authority",
        "submitted",
        "issued_bundle_sha256",
    }
    for name in ("candidate", "reference"):
        assert "proposal" in original["evaluation"]["controls"][name]
        assert "proposal_without_bundle_digest" not in original["evaluation"]["controls"][name]
    bridge.controller.submit(LabProposal.model_validate(original["proposal"]), f.now)
    waiting = bridge.prepare(command(bridge, selection, "observation-default-0002"), f.now)
    assert waiting["status"] == "waiting" and "used-rule" in waiting["reason"]
    assert "research_only" not in waiting and "readonly_comparison_template" not in waiting
    observation = bridge.current_observation("observation-default-current", f.now)
    assert set(observation) == {"proposal_without_bundle_digest", "evaluation"}
    assert observation["evaluation"]["status"] == "waiting"
    assert "used-rule" in observation["evaluation"]["reason"]


@pytest.mark.parametrize("first_mode", [False, True])
def test_exact_request_id_cannot_be_reinterpreted_between_modes(fixture, first_mode):
    f, bridge, selection = fixture
    used(f, bridge, selection)
    intent = command(bridge, selection, "observation-mode-bound-0002")
    receipt = bridge.prepare(intent, f.now, research_only=first_mode)
    with pytest.raises(ValueError, match="cannot be rewritten"):
        bridge.prepare(intent, f.now, research_only=not first_mode)
    assert bridge.get(intent.request_id) == receipt
    assert bridge.prepare(intent, f.now + 1, research_only=first_mode) == receipt


def test_research_recovery_precedes_mutable_owner_policy_input_and_used_marker(
    fixture, monkeypatch
):
    f, bridge, selection = fixture
    used(f, bridge, selection)
    intent = command(bridge, selection, "observation-recovery-0002")
    receipt = bridge.prepare(intent, f.now, research_only=True)
    before = inbox_rows(f)
    reopened = PatternComparisons(f.scanner, None)
    f.paper.history.clear()
    f.paper.state.pop("autonomous_lab")
    f.scanner.plan = None
    monkeypatch.setattr(reopened, "describe", lambda *_: pytest.fail("Recovery reread finding"))
    assert reopened.get(intent.request_id) == receipt
    assert reopened.prepare(intent, f.now + 1000, research_only=True) == receipt
    assert reopened.page()["items"][0]["status"] == "research_only"
    assert inbox_rows(f) == before
    with pytest.raises(ValueError, match="cannot be rewritten"):
        reopened.prepare(intent, f.now + 1000)


@pytest.mark.parametrize("entry", ["prepare", "current_observation", "_evaluation"])
def test_research_mode_requires_real_existing_nonrejected_used_p0(fixture, entry):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "observation-missing-used-0002")
    args = (intent, f.now) if entry == "prepare" else (intent.request_id, f.now)
    before = f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0]
    with pytest.raises(ValueError, match="existing used p0 marker"):
        getattr(bridge, entry)(*args, research_only=True)
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == before
    original = used(f, bridge, selection)
    bridge.controller.inbox.update(original["request_id"], "rejected")
    with pytest.raises(ValueError, match="existing used p0 marker"):
        getattr(bridge, entry)(*args, research_only=True)
    assert bridge.get(intent.request_id) is None


def test_current_readonly_observation_has_matched_capture_disclosure_and_no_offer(fixture):
    f, bridge, selection = fixture
    original = used(f, bridge, selection)
    before = inbox_rows(f)
    admissions = []
    observation = bridge.current_observation(
        "observation-current-research",
        f.now,
        admission=lambda: admissions.append(True),
        research_only=True,
    )
    assert len(admissions) == 3
    assert observation["evaluation"]["status"] == "supported_research_observation"
    assert observation["proposal_without_bundle_digest"] is None
    assert (
        observation["readonly_comparison_template"]["strategy"] == original["proposal"]["strategy"]
    )
    assert observation["dispatch_available"] is False and observation["research_only"] is True
    proof = observation["evaluation"]["matched_inputs"]
    assert len(bridge.execution_inputs(proof, "observation-current-research")) == 600
    assert (
        f.registry.db.execute(
            "SELECT count(*) FROM evidence_windows WHERE request_id LIKE 'pattern-role-input:%'"
        ).fetchone()[0]
        == 1
    )
    assert inbox_rows(f) == before


@pytest.mark.parametrize(
    "guard", ["history", "gap", "eligibility", "protection", "can_research", "policy", "capacity"]
)
def test_readonly_mode_preserves_current_guards_and_immutable_wait(fixture, monkeypatch, guard):
    f, bridge, selection = fixture
    used(f, bridge, selection)
    intent = command(bridge, selection, "observation-guard-0002")
    if guard == "history":
        f.paper.history["BTCUSD"] = f.paper.history["BTCUSD"][-20:]
    elif guard == "gap":
        del f.paper.history["BTCUSD"][-50]
    elif guard == "eligibility":
        f.paper.universe.scanned_at -= 121
    elif guard == "protection":
        f.paper.constrained = lambda: True
    elif guard == "can_research":
        bridge.controller.can_research = lambda: False
    elif guard == "policy":
        f.paper.state.pop("autonomous_lab")
    else:
        monkeypatch.setattr(bridge.controller.inbox, "has_capacity", lambda: False)
    before = inbox_rows(f)
    receipt = bridge.prepare(intent, f.now, research_only=True)
    assert receipt["status"] == "waiting" and receipt["evaluation"]["reason"]
    assert receipt["proposal"] is None and receipt["dispatch_available"] is False
    assert receipt["research_only"] is True and "matched_inputs" not in receipt["evaluation"]
    assert bridge.prepare(intent, f.now + 1, research_only=True) == receipt
    assert inbox_rows(f) == before


@pytest.mark.parametrize("guard", ["archive", "registry", "holdout", "prospective"])
def test_readonly_mode_preserves_storage_and_protected_evidence_refusals(
    fixture, monkeypatch, guard
):
    f, bridge, selection = fixture
    used(f, bridge, selection)
    intent = command(bridge, selection, "observation-protected-0002")
    if guard == "archive":
        f.scanner.storage_owner = None
    elif guard == "registry":

        def refuse():
            raise OSError("Protected registry headroom")

        monkeypatch.setattr(f.scanner, "_admission", refuse)
    elif guard == "holdout":
        f.registry.db.execute(
            "INSERT INTO evidence_windows VALUES('readonly-held',?,?, 'sealed holdout')",
            (f.paper.history["BTCUSD"][0].open_ms / 1000, f.now),
        )
    else:
        f.registry.db.execute("CREATE TABLE prospective_plans(start REAL,end REAL)")
        f.registry.db.execute(
            "INSERT INTO prospective_plans VALUES(?,?)",
            (f.paper.history["BTCUSD"][0].open_ms / 1000, f.now),
        )
    before = inbox_rows(f)
    with pytest.raises((ValueError, OSError)):
        bridge.prepare(intent, f.now, research_only=True)
    assert bridge.get(intent.request_id) is None and inbox_rows(f) == before


@pytest.mark.parametrize("entry", ["prepare", "current_observation"])
def test_used_marker_lost_during_archive_wait_refuses_publication(fixture, entry):
    f, bridge, selection = fixture
    original = used(f, bridge, selection)
    intent = command(bridge, selection, "observation-marker-race-0002")
    owner = f.scanner.storage_owner

    @contextmanager
    def reject_during_borrow(plan):
        with owner(plan) as store:
            bridge.controller.inbox.update(original["request_id"], "rejected")
            yield store

    f.scanner.storage_owner = reject_during_borrow
    args = (intent, f.now) if entry == "prepare" else (intent.request_id, f.now)
    with pytest.raises(ValueError, match="existing used p0 marker"):
        getattr(bridge, entry)(*args, research_only=True)
    assert bridge.get(intent.request_id) is None
    assert (
        f.registry.db.execute(
            "SELECT count(*) FROM evidence_windows WHERE request_id LIKE 'pattern-role-input:%'"
        ).fetchone()[0]
        == 0
    )


def test_concurrent_readonly_exact_intent_publishes_one_original(fixture):
    f, bridge, selection = fixture
    used(f, bridge, selection)
    intent = command(bridge, selection, "observation-concurrent-0002")
    before = inbox_rows(f)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(
            pool.map(lambda _: bridge.prepare(intent, f.now, research_only=True), range(4))
        )
    assert all(receipt == receipts[0] for receipt in receipts)
    assert (
        f.registry.db.execute(
            "SELECT count(*) FROM pattern_comparison_requests WHERE request_id=?",
            (intent.request_id,),
        ).fetchone()[0]
        == 1
    )
    assert inbox_rows(f) == before


def test_readonly_mode_is_internal_and_does_not_extend_command_schema(fixture):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    with pytest.raises(ValidationError):
        PatternComparisonCommand.model_validate({**intent.model_dump(), "research_only": True})
    for name, args in (
        ("prepare", (intent, f.now)),
        ("current_observation", (intent.request_id, f.now)),
        ("_evaluation", (intent.request_id, f.now)),
    ):
        with pytest.raises(ValueError, match="explicit boolean"):
            getattr(bridge, name)(*args, research_only=1)


def test_readonly_marker_is_exact_fixed_rule_not_an_unrelated_rule(fixture):
    f, bridge, selection = fixture
    original = bridge.prepare(command(bridge, selection), f.now)
    other = LabProposal.model_validate(
        {
            **original["proposal"],
            "reference": original["proposal"]["strategy"],
            "strategy": RuleSpec(
                version="reviewed-lab-rules-v4", family="cost-breakout-v1", holding_horizon="medium"
            ).model_dump(),
        }
    )
    assert bridge.controller.submit(other, f.now)["status"] == "evaluated"
    with pytest.raises(ValueError, match="existing used p0 marker"):
        bridge.prepare(
            command(bridge, selection, "observation-foreign-marker"), f.now, research_only=True
        )


def test_readonly_template_cannot_bypass_existing_lab_used_rule_rejection(fixture):
    f, bridge, selection = fixture
    used(f, bridge, selection)
    receipt = bridge.prepare(
        command(bridge, selection, "observation-not-submittable"), f.now, research_only=True
    )
    before, state = inbox_rows(f), copy.deepcopy(f.paper.state)
    # A deliberate separate QA submission is rejected by the unchanged inbox owner;
    # preparation above itself did not append any proposal or financial intent.
    proposal = LabProposal.model_validate(
        {
            **receipt["readonly_comparison_template"],
            "evidence_bundle_sha256": receipt["issued_bundle_sha256"],
        }
    )
    rejected = bridge.controller.submit(proposal, f.now)
    assert rejected["status"] == "rejected" and "already attempted" in rejected["reason"]
    assert inbox_rows(f)[:-1] == before and f.paper.state == state
    assert rejected["trial_id"] is None


@pytest.mark.parametrize("entry", ["prepare", "current_observation"])
def test_capacity_closes_during_archive_wait_without_publishing_supported_observation(
    fixture, monkeypatch, entry
):
    f, bridge, selection = fixture
    used(f, bridge, selection)
    intent = command(bridge, selection, "observation-capacity-race")
    owner = f.scanner.storage_owner

    @contextmanager
    def full_during_borrow(plan):
        with owner(plan) as store:
            monkeypatch.setattr(bridge.controller.inbox, "has_capacity", lambda: False)
            yield store

    f.scanner.storage_owner = full_during_borrow
    args = (intent, f.now) if entry == "prepare" else (intent.request_id, f.now)
    before = inbox_rows(f)
    with pytest.raises(ValueError, match="capacity changed"):
        getattr(bridge, entry)(*args, research_only=True)
    assert bridge.get(intent.request_id) is None and inbox_rows(f) == before


@pytest.mark.parametrize(
    "origin",
    [
        "role outcome disclosure",
        "lesson disclosure",
        "role dependency disclosure",
        "role task disclosure",
    ],
)
def test_known_role_training_overlap_is_readonly_only_without_erasing_native_gaps(fixture, origin):
    f, bridge, selection = fixture
    original = used(f, bridge, selection)
    intent = command(bridge, selection, "observation-role-training")
    native = original["finding"]["native_proof"]["disclosed_intervals"]
    start = min(native[0][0], f.paper.history["BTCUSD"][0].open_ms / 1000)
    f.registry.db.execute(
        "INSERT INTO evidence_windows VALUES('prior-role-training',?,?,?)", (start, f.now, origin)
    )
    with pytest.raises(ValueError, match="Protected"):
        bridge.describe(selection)
    with pytest.raises(ValueError, match="Protected"):
        bridge.prepare(intent, f.now)
    normal = bridge.current_observation("observation-normal-training", f.now)
    assert normal["evaluation"]["status"] == "waiting"
    assert "used-rule" in normal["evaluation"]["reason"]
    # Ordinary observation stops at used-rule, before disclosure; its guard is unchanged.
    # The explicit permitted-window check also refuses this same interval in normal mode.
    with f.registry.lock, pytest.raises(ValueError, match="Protected"):
        bridge._permitted([(start, f.now)])
    described = bridge.describe(selection, research_only=True)
    assert digest(described["finding"]) == digest(original["finding"])
    receipt = bridge.prepare(intent, f.now, research_only=True)
    assert receipt["status"] == "research_only" and receipt["finding"] == original["finding"]
    observation = bridge.current_observation(
        "observation-readonly-training", f.now, research_only=True
    )
    assert observation["evaluation"]["status"] == "supported_research_observation"
    assert (
        f.registry.db.execute(
            "SELECT start,end,origin FROM evidence_windows WHERE request_id='prior-role-training'"
        ).fetchone()["origin"]
        == origin
    )


@pytest.mark.parametrize(
    "origin",
    [
        "sealed holdout",
        "unknown role disclosure",
        "role component disclosure",
        "tool outcome disclosure",
    ],
)
def test_readonly_training_allowance_never_accepts_other_protected_origins(fixture, origin):
    f, bridge, selection = fixture
    used(f, bridge, selection)
    intent = command(bridge, selection, "observation-forbidden-origin")
    f.registry.db.execute(
        "INSERT INTO evidence_windows VALUES('other-protection',?,?,?)",
        (f.paper.history["BTCUSD"][0].open_ms / 1000, f.now, origin),
    )
    with pytest.raises(ValueError, match="Protected"):
        bridge.prepare(intent, f.now, research_only=True)
    with pytest.raises(ValueError, match="Protected"):
        bridge.current_observation("observation-forbidden-current", f.now, research_only=True)
    assert bridge.get(intent.request_id) is None
