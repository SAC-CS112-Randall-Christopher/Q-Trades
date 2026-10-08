"""Explicit next-method preparations through real disposable native/Lab owners."""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from pydantic import ValidationError
from test_pattern_comparisons import build_fixture, command

from trading.autonomous_spec import LabProposal
from trading.lab_role_contract import (
    PATTERN_METHOD_QUESTION_POLICY,
    PATTERN_METHODS,
    pattern_method_policy_sha,
)
from trading.pattern_comparisons import PatternComparisonCommand, PatternComparisons
from trading.research_evidence import digest


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    f, bridge, selection = build_fixture(tmp_path, monkeypatch)
    try:
        yield f, bridge, selection
    finally:
        f.close()


def mark_used(f, bridge, selection, method):
    normal = bridge.prepare(
        command(bridge, selection, f"next-used-{method}-0001"), f.now, method_id=method
    )
    assert normal["status"] == "supported"
    accepted = bridge.controller.submit(LabProposal.model_validate(normal["proposal"]), f.now)
    assert accepted["status"] == "evaluated"
    return normal


def inbox_rows(f):
    return [tuple(row) for row in f.registry.db.execute("SELECT * FROM lab_proposals ORDER BY seq")]


def test_p1_genuine_native_mapping_and_separate_matched_v4_inputs(fixture):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "next-independent-p1")
    before = copy.deepcopy(f.paper.state)
    receipt = bridge.prepare(intent, f.now, method_id="p1")
    assert receipt["status"] == "supported"
    assert receipt["method_id"] == receipt["mapping"]["method_id"] == "p1"
    assert receipt["question_policy"] == PATTERN_METHOD_QUESTION_POLICY
    assert (
        receipt["method_policy_sha256"]
        == receipt["mapping"]["method_policy_sha256"]
        == pattern_method_policy_sha()
    )
    assert receipt["intent_sha256"] == digest(
        {
            "command": intent.model_dump(),
            "method_id": "p1",
            "method_policy_sha256": pattern_method_policy_sha(),
        }
    )
    proposal = LabProposal.model_validate(receipt["proposal"])
    assert proposal.kind == "independent" and proposal.parent_trial is None
    assert proposal.parent_strategy_sha256 is None and proposal.replication_of is None
    assert proposal.strategy.family == receipt["mapping"]["strategy"] == "trend-pullback-v1"
    assert proposal.reference.family == receipt["mapping"]["reference"] == "cost-breakout-v1"
    assert proposal.strategy.version == "reviewed-lab-rules-v4"
    assert proposal.strategy.holding_horizon == proposal.reference.holding_horizon == "medium"
    assert receipt["finding"]["native_proof"]["recognition_rows"] == 21
    assert receipt["finding"]["native_proof"]["archive_verified"] is True
    proof = receipt["evaluation"]["matched_inputs"]
    assert proof["count"] == len(bridge.execution_inputs(proof, intent.request_id)) == 600
    assert (
        receipt["evaluation"]["controls"]["candidate"]["proposal"]["strategy"]
        == proposal.strategy.model_dump()
    )
    assert (
        receipt["evaluation"]["controls"]["reference"]["proposal"]["strategy"]
        == proposal.reference.model_dump()
    )
    assert f.paper.state == before and inbox_rows(f) == []
    assert receipt["financial_authority"] is False and receipt["submitted"] is False


def test_default_p0_golden_keys_intent_controls_and_explicit_argument(fixture):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "next-default-p0")
    receipt = bridge.prepare(intent, f.now)
    assert bridge.prepare(intent, f.now + 1, method_id="p0") == receipt
    assert bridge.describe(selection, method_id="p0") == bridge.describe(selection)
    assert receipt["intent_sha256"] == digest(intent.model_dump())
    assert set(receipt) == {
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
    assert "method_id" not in receipt["mapping"] and "question_policy" not in receipt["mapping"]
    assert receipt["proposal"]["strategy"]["family"] == "breakout-retest-v1"
    assert (
        receipt["proposal"]["mechanism"]
        == "Saved native resistance recognition motivates the fixed retest bank hypothesis"
    )
    mark_used(f, bridge, selection, "p0")
    readonly_intent = command(bridge, selection, "next-default-readonly")
    readonly = bridge.prepare(readonly_intent, f.now, research_only=True)
    assert readonly["intent_sha256"] == digest(
        {"command": readonly_intent.model_dump(), "research_only": True}
    )
    assert "method_id" not in readonly
    assert bridge.prepare(readonly_intent, f.now, research_only=True, method_id="p0") == readonly


@pytest.mark.parametrize("first", ["p0", "p1"])
@pytest.mark.parametrize("readonly", [False, True])
def test_same_uuid_cannot_cross_method_boundaries(fixture, first, readonly):
    f, bridge, selection = fixture
    if readonly:
        mark_used(f, bridge, selection, first)
    intent = command(bridge, selection, "next-cross-method-identity")
    original = bridge.prepare(intent, f.now, method_id=first, research_only=readonly)
    before = f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0]
    with pytest.raises(ValueError, match="cannot be rewritten"):
        bridge.prepare(
            intent, f.now, method_id="p1" if first == "p0" else "p0", research_only=readonly
        )
    assert bridge.get(intent.request_id) == original
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == before


@pytest.mark.parametrize("readonly", [False, True])
def test_p1_exact_original_recovery_precedes_current_source_and_policy(
    fixture, monkeypatch, readonly
):
    f, bridge, selection = fixture
    if readonly:
        mark_used(f, bridge, selection, "p1")
    intent = command(bridge, selection, "next-reopen-original")
    original = bridge.prepare(intent, f.now, method_id="p1", research_only=readonly)
    reopened = PatternComparisons(f.scanner, None)
    f.scanner.plan = None
    f.paper.history.clear()
    f.paper.state.pop("autonomous_lab")
    monkeypatch.setattr(
        reopened, "describe", lambda *_args, **_kwargs: pytest.fail("Recovery reread source")
    )
    assert reopened.get(intent.request_id) == original
    assert (
        reopened.prepare(intent, f.now + 86400, method_id="p1", research_only=readonly) == original
    )
    page = reopened.page()
    assert page["order"] == "Stable descending request identity, not preparation chronology"
    assert any(row["request_id"] == intent.request_id for row in page["items"])
    with pytest.raises(ValueError, match="cannot be rewritten"):
        reopened.prepare(intent, f.now, method_id="p1", research_only=not readonly)


def test_p1_wait_is_original_and_does_not_silently_become_ready(fixture, monkeypatch):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "next-p1-original-wait")
    monkeypatch.setattr(bridge.controller, "can_research", lambda: False)
    waiting = bridge.prepare(intent, f.now, method_id="p1")
    assert waiting["status"] == "waiting" and waiting["method_id"] == "p1"
    assert waiting["proposal"]["strategy"]["family"] == "trend-pullback-v1"
    monkeypatch.setattr(bridge.controller, "can_research", lambda: True)
    assert bridge.prepare(intent, f.now + 1, method_id="p1") == waiting
    observed = bridge.current_observation("next-p1-fresh-observation", f.now, method_id="p1")
    assert observed["evaluation"]["status"] == "supported_exploratory_configuration"
    assert observed["method_id"] == "p1"
    assert observed["proposal_without_bundle_digest"]["strategy"]["family"] == "trend-pullback-v1"


@pytest.mark.parametrize("entry", ["describe", "prepare", "current_observation", "_evaluation"])
def test_p1_readonly_requires_own_nonrejected_used_candidate(fixture, entry):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "next-readonly-own-marker")
    args = (
        (selection,)
        if entry == "describe"
        else (intent, f.now)
        if entry == "prepare"
        else (intent.request_id, f.now)
    )
    with pytest.raises(ValueError, match="used p1 marker"):
        getattr(bridge, entry)(*args, method_id="p1", research_only=True)
    mark_used(f, bridge, selection, "p0")
    with pytest.raises(ValueError, match="used p1 marker"):
        getattr(bridge, entry)(*args, method_id="p1", research_only=True)
    p1 = mark_used(f, bridge, selection, "p1")
    assert getattr(bridge, entry)(*args, method_id="p1", research_only=True)
    bridge.controller.inbox.update(p1["request_id"], "rejected")
    # A saved original remains immutable; fresh observation still requires a real used marker.
    if entry != "prepare":
        with pytest.raises(ValueError, match="used p1 marker"):
            getattr(bridge, entry)(*args, method_id="p1", research_only=True)


def test_p1_readonly_has_no_dispatch_proposal_or_inbox_mutation(fixture):
    f, bridge, selection = fixture
    mark_used(f, bridge, selection, "p1")
    before, state = inbox_rows(f), copy.deepcopy(f.paper.state)
    intent = command(bridge, selection, "next-readonly-p1")
    receipt = bridge.prepare(intent, f.now, method_id="p1", research_only=True)
    assert receipt["status"] == "research_only"
    assert receipt["proposal"] is None and receipt["dispatch_available"] is False
    assert "p1" in receipt["dispatch_reason"]
    assert receipt["intent_sha256"] == digest(
        {
            "command": intent.model_dump(),
            "method_id": "p1",
            "method_policy_sha256": pattern_method_policy_sha(),
            "research_only": True,
        }
    )
    assert receipt["readonly_comparison_template"]["strategy"]["family"] == "trend-pullback-v1"
    for control in receipt["evaluation"]["controls"].values():
        if isinstance(control, dict):
            assert "proposal" not in control
    observed = bridge.current_observation(
        "next-readonly-p1-current", f.now, method_id="p1", research_only=True
    )
    assert observed["evaluation"]["status"] == "supported_research_observation"
    assert (
        observed["proposal_without_bundle_digest"] is None
        and observed["dispatch_available"] is False
    )
    assert observed["readonly_comparison_template"]["strategy"]["family"] == "trend-pullback-v1"
    assert inbox_rows(f) == before and f.paper.state == state


@pytest.mark.parametrize(
    "origin",
    [
        "role outcome disclosure",
        "lesson disclosure",
        "role dependency disclosure",
        "role task disclosure",
    ],
)
def test_p1_learning_origin_overlap_preserves_intervals_and_default_p0_refusal(fixture, origin):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "next-learning-origin")
    finding = bridge.describe(selection)["finding"]
    start = min(
        finding["native_proof"]["disclosed_intervals"][0][0],
        f.paper.history["BTCUSD"][0].open_ms / 1000,
    )
    f.registry.db.execute(
        "INSERT INTO evidence_windows VALUES('preceding-role',?,?,?)", (start, f.now, origin)
    )
    with pytest.raises(ValueError, match="Protected"):
        bridge.describe(selection)
    receipt = bridge.prepare(intent, f.now, method_id="p1")
    assert receipt["status"] == "supported" and digest(receipt["finding"]) == digest(finding)
    assert tuple(
        f.registry.db.execute(
            "SELECT start,end,origin FROM evidence_windows WHERE request_id='preceding-role'"
        ).fetchone()
    ) == (start, f.now, origin)


@pytest.mark.parametrize(
    "origin",
    [
        "sealed holdout",
        "unknown role disclosure",
        "role component disclosure",
        "tool outcome disclosure",
    ],
)
@pytest.mark.parametrize("readonly", [False, True])
def test_p1_still_refuses_other_protected_origins(fixture, origin, readonly):
    f, bridge, selection = fixture
    if readonly:
        mark_used(f, bridge, selection, "p1")
    intent = command(bridge, selection, "next-protected-p1")
    f.registry.db.execute(
        "INSERT INTO evidence_windows VALUES('unknown-protection',?,?,?)",
        (f.paper.history["BTCUSD"][0].open_ms / 1000, f.now, origin),
    )
    with pytest.raises(ValueError, match="Protected"):
        bridge.prepare(intent, f.now, method_id="p1", research_only=readonly)
    with pytest.raises(ValueError, match="Protected"):
        bridge.current_observation(
            "next-protected-current", f.now, method_id="p1", research_only=readonly
        )
    assert bridge.get(intent.request_id) is None


@pytest.mark.parametrize("entry", ["prepare", "current_observation"])
def test_p1_policy_change_during_archive_refuses_publication(fixture, monkeypatch, entry):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "next-method-policy-race")
    owner = f.scanner.storage_owner

    @contextmanager
    def changed_during_borrow(plan):
        with owner(plan) as store:
            monkeypatch.setitem(PATTERN_METHODS, "p1", ("trend-pullback-v1", "range-fade"))
            yield store

    f.scanner.storage_owner = changed_during_borrow
    args = (intent, f.now) if entry == "prepare" else (intent.request_id, f.now)
    before = f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0]
    with pytest.raises(ValueError, match="method policy changed"):
        getattr(bridge, entry)(*args, method_id="p1")
    assert bridge.get(intent.request_id) is None
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == before


def test_p1_same_intent_concurrency_retains_one_original(fixture):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "next-concurrent-p1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: bridge.prepare(intent, f.now, method_id="p1"), range(2)))
    assert results[0] == results[1]
    assert (
        f.registry.db.execute(
            "SELECT count(*) FROM pattern_comparison_requests WHERE request_id=?",
            (intent.request_id,),
        ).fetchone()[0]
        == 1
    )
    assert inbox_rows(f) == []


@pytest.mark.parametrize(
    "guard", ["history", "gap", "eligibility", "protection", "can_research", "policy", "capacity"]
)
def test_p1_current_guards_retain_original_wait(fixture, monkeypatch, guard):
    f, bridge, selection = fixture
    mark_used(f, bridge, selection, "p1")
    intent = command(bridge, selection, "next-p1-current-guard")
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
    receipt = bridge.prepare(intent, f.now, method_id="p1", research_only=True)
    assert receipt["status"] == "waiting" and receipt["evaluation"]["reason"]
    assert receipt["proposal"] is None and receipt["dispatch_available"] is False
    assert "matched_inputs" not in receipt["evaluation"]
    assert bridge.prepare(intent, f.now + 1, method_id="p1", research_only=True) == receipt
    assert inbox_rows(f) == before


@pytest.mark.parametrize("guard", ["archive", "registry", "prospective"])
def test_p1_storage_and_prospective_refusals(fixture, monkeypatch, guard):
    f, bridge, selection = fixture
    mark_used(f, bridge, selection, "p1")
    intent = command(bridge, selection, "next-p1-storage-guard")
    if guard == "archive":
        f.scanner.storage_owner = None
    elif guard == "registry":

        def refuse():
            raise OSError("Protected registry headroom")

        monkeypatch.setattr(f.scanner, "_admission", refuse)
    else:
        f.registry.db.execute("CREATE TABLE prospective_plans(start REAL,end REAL)")
        f.registry.db.execute(
            "INSERT INTO prospective_plans VALUES(?,?)",
            (f.paper.history["BTCUSD"][0].open_ms / 1000, f.now),
        )
    before = inbox_rows(f)
    with pytest.raises((ValueError, OSError)):
        bridge.prepare(intent, f.now, method_id="p1", research_only=True)
    assert bridge.get(intent.request_id) is None and inbox_rows(f) == before


@pytest.mark.parametrize("entry", ["prepare", "current_observation"])
def test_p1_used_marker_lost_during_archive_refuses_publication(fixture, entry):
    f, bridge, selection = fixture
    original = mark_used(f, bridge, selection, "p1")
    intent = command(bridge, selection, "next-p1-marker-race")
    owner = f.scanner.storage_owner

    @contextmanager
    def rejected_during_borrow(plan):
        with owner(plan) as store:
            bridge.controller.inbox.update(original["request_id"], "rejected")
            yield store

    f.scanner.storage_owner = rejected_during_borrow
    args = (intent, f.now) if entry == "prepare" else (intent.request_id, f.now)
    with pytest.raises(ValueError, match="used p1 marker"):
        getattr(bridge, entry)(*args, method_id="p1", research_only=True)
    assert bridge.get(intent.request_id) is None
    assert (
        f.registry.db.execute(
            "SELECT count(*) FROM evidence_windows WHERE request_id LIKE 'pattern-role-input:%'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("method", ["p2", "", 1, None])
def test_unknown_method_refuses_without_widening_command_schema(fixture, method):
    f, bridge, selection = fixture
    intent = command(bridge, selection, "next-method-refusal")
    with pytest.raises(ValueError, match="No reviewed comparison method"):
        bridge.prepare(intent, f.now, method_id=method)
    with pytest.raises(ValidationError):
        PatternComparisonCommand.model_validate({**intent.model_dump(), "method_id": "p1"})
    assert bridge.get(intent.request_id) is None
