"""Successor contract software fixtures; no model or qualification calls."""

import copy

import pytest

from trading.lab_role_contract import (
    CAPABILITY_VERSION,
    TOOL_REQUEST_VERSION,
    VERSION,
    Idea,
    IdeaV6,
    Review,
    contract_hash,
    packet_json,
    prompt,
    schema,
    validate,
)

V5_HASH = "71f90342b3781819e690cf9bb8890a750e97a34b3818fb1a8d04b2324682b7f5"
V6_HASH = "cb4d5c9435720f7c48e85ecbc582658821e01d2ad51d92274cfb54bc1a64e4e3"


def packet():
    return {
        "contract": TOOL_REQUEST_VERSION,
        "question": "Does a range-reversion mechanism improve matched after-cost outcomes?",
        "capabilities": {
            "r0": {"kind": "replication", "family": "breakout"},
            "r1": {"kind": "independent", "family": "range_reversion"},
        },
        "tool_inventory": {
            "strategy_family": ["breakout", "range_reversion"],
            "feature": ["atr", "excursion_bps", "modeled_hurdle_bps"],
            "analysis_tool": ["reviewed_rule_inputs", "matched_comparison"],
        },
        "evidence": {
            "e0": {"outcome": "data_blocked", "delta_usd": None},
            "e2": {
                "features": {
                    "shared": {"eligible": False},
                    "by_capability": {
                        "r1": {"excursion_bps": 2.7080220655895104, "modeled_hurdle_bps": 24.0}
                    },
                },
                "request_data_conditions": {"new_closed_bars": {"kind": "closed_bars"}},
            },
        },
    }


def answer(action="unsupported_capability"):
    return {
        "action": action,
        "capability": None,
        "dependency": None,
        "evidence_ids": ["e0", "e2"],
        "mechanism": "The range-reversion feature is not supported by the declared capability.",
        "falsification": "A later closed bar could confirm the range-reversion signal.",
        "rationale": (
            "The r1 capability is independent and does not support this range-reversion claim."
        ),
        "unsupported_basis": {"kind": "strategy_family", "identifier": "range_reversion"},
        "tool_request": None,
    }


def tool_answer(kind="feature", identifier="book_resilience"):
    result = answer("request_tool")
    result["unsupported_basis"] = None
    result["tool_request"] = {
        "kind": kind,
        "identifier": identifier,
        "purpose": "Measure whether the offered range-reversion input survives book instability.",
        "required_inputs": ["Timestamped observed BTCUSD books", "Causal closed-minute bars"],
        "acceptance_checks": [
            "Reject stale books and future closed bars without substituting inputs.",
            "Retain missing coverage and verify outputs against their exact input hashes.",
        ],
    }
    return result


def successor(value, observed=None):
    return validate(
        "researcher", value, packet() if observed is None else observed, TOOL_REQUEST_VERSION
    )


def test_frozen_v5_defaults_and_hash_remain_exact():
    assert VERSION == "reviewed-rule-role-v5"
    assert contract_hash() == contract_hash(VERSION) == V5_HASH
    assert prompt("researcher") == prompt("researcher", VERSION)
    assert schema("researcher") == schema("researcher", VERSION)
    assert "unsupported_basis" not in schema("researcher")["properties"]
    assert "tool_request" not in schema("researcher")["properties"]
    assert contract_hash(TOOL_REQUEST_VERSION) != V5_HASH
    assert TOOL_REQUEST_VERSION == "reviewed-rule-role-v6"
    assert contract_hash(TOOL_REQUEST_VERSION) == V6_HASH


def capability_successor(value, observed=None):
    selected = packet() if observed is None else copy.deepcopy(observed)
    selected["contract"] = CAPABILITY_VERSION
    return validate("researcher", value, selected, CAPABILITY_VERSION)


def retained_handle_denial():
    # Redacted scientific reproduction of c887's actual v6 answer/issued packet.
    # Original operating files stay private; this fixture makes no new inference.
    observed = packet()
    value = {
        "action": "unsupported_capability",
        "capability": None,
        "dependency": None,
        "evidence_ids": ["e0", "e2"],
        "falsification": "A later closed bar with confirmed volume could enable the comparison.",
        "mechanism": "The declared capability is a feature, not a strategy family.",
        "rationale": "The requested comparison is not supported by the declared capability.",
        "unsupported_basis": {"kind": "feature", "identifier": "r0"},
        "tool_request": None,
    }
    return observed, value


def test_actual_v6_handle_denial_remains_valid_historically_but_v7_refuses():
    observed, value = retained_handle_denial()
    original = packet_json({"packet": observed, "answer": value})
    assert successor(value, observed).unsupported_basis.identifier == "r0"
    with pytest.raises(ValueError, match="offered comparison handle"):
        capability_successor(value, observed)
    assert packet_json({"packet": observed, "answer": value}) == original


@pytest.mark.parametrize("kind", ["feature", "strategy_family", "analysis_tool"])
@pytest.mark.parametrize("handle", ["r0", "r1"])
@pytest.mark.parametrize("action", ["unsupported_capability", "request_tool"])
def test_any_offered_handle_cannot_be_denied_or_requested_under_another_kind(kind, handle, action):
    value = answer() if action == "unsupported_capability" else tool_answer(kind, handle)
    if action == "unsupported_capability":
        value["unsupported_basis"] = {"kind": kind, "identifier": handle}
    with pytest.raises(ValueError, match="offered comparison handle"):
        capability_successor(value)


@pytest.mark.parametrize("action", ["unsupported_capability", "request_tool"])
def test_unoffered_feature_identifier_is_still_a_typed_v7_request_or_abstention(action):
    value = tool_answer() if action == "request_tool" else answer()
    if action == "unsupported_capability":
        value["unsupported_basis"] = {"kind": "feature", "identifier": "book_resilience"}
    parsed = capability_successor(value)
    assert parsed.action == action
    assert (parsed.unsupported_basis or parsed.tool_request).identifier == "book_resilience"


def test_v7_missing_current_data_uses_the_offered_wait_and_preserves_the_source():
    value = answer("request_data")
    value.update(unsupported_basis=None, dependency="new_closed_bars")
    assert capability_successor(value).dependency == "new_closed_bars"
    with pytest.raises(ValueError, match="offered wait requirement"):
        capability_successor(value | {"dependency": "preferred_future_outcome"})


def test_v7_contract_is_explicit_with_same_typed_shape_and_fixed_control_instructions():
    assert CAPABILITY_VERSION == "reviewed-rule-role-v7"
    assert schema("researcher", CAPABILITY_VERSION) == schema("researcher", TOOL_REQUEST_VERSION)
    assert schema("reviewer", CAPABILITY_VERSION) == schema("reviewer", VERSION)
    assert contract_hash(CAPABILITY_VERSION) not in {V5_HASH, V6_HASH}
    explicit = prompt("researcher", CAPABILITY_VERSION)
    assert "reserved comparison handle" in explicit
    assert "volume_multiple" in explicit
    assert "Identical fixed controls do not constitute a stronger-volume comparison" in explicit
    assert "reserved comparison handle" not in prompt("researcher", TOOL_REQUEST_VERSION)
    observed, value = retained_handle_denial()
    with pytest.raises(ValueError, match="exact frozen packet contract"):
        validate("researcher", value, observed, CAPABILITY_VERSION)
    with pytest.raises(ValueError, match="exact frozen packet contract"):
        successor(value, observed | {"contract": CAPABILITY_VERSION})


def test_v7_offered_fixed_volume_is_not_an_invented_proposal_handle():
    observed = packet()
    for capability in observed["capabilities"].values():
        capability["fixed_comparison"] = {
            "strategy": {"volume_multiple": "2", "exit_seconds": 2700, "progress_seconds": 600},
            "reference": {"volume_multiple": "2", "exit_seconds": 2700, "progress_seconds": 600},
            "parameter_selection": "server_frozen_only",
        }
    value = answer("propose_experiment") | {"capability": "r0", "unsupported_basis": None}
    frozen = packet_json(observed)
    assert capability_successor(value, observed).capability == "r0"
    with pytest.raises(ValueError, match="Unsupported or stale rule capability"):
        capability_successor(value | {"capability": "r0_stronger_volume"}, observed)
    assert packet_json(observed) == frozen


@pytest.mark.parametrize(
    "kind,identifier",
    [("strategy_family", "breakout"), ("feature", "atr"), ("analysis_tool", "matched_comparison")],
)
def test_v7_inventory_absence_rules_still_reject_implemented_tools(kind, identifier):
    with pytest.raises(ValueError, match="already in the frozen tool inventory"):
        capability_successor(tool_answer(kind, identifier))


def test_v7_inventory_cannot_omit_an_offered_family_or_invent_evidence():
    observed = packet()
    observed["tool_inventory"]["strategy_family"].remove("range_reversion")
    with pytest.raises(ValueError, match="omits an offered strategy family"):
        capability_successor(tool_answer(), observed)
    with pytest.raises(ValueError, match="evidence handle"):
        capability_successor(tool_answer() | {"evidence_ids": ["invented"]})


def test_retained_v5_adverse_answer_is_not_regraded_or_rewritten():
    old_answer = {
        k: v for k, v in answer().items() if k not in {"unsupported_basis", "tool_request"}
    }
    old_packet = {k: v for k, v in packet().items() if k not in {"contract", "tool_inventory"}}
    frozen = packet_json({"answer": old_answer, "packet": old_packet})
    assert validate("researcher", old_answer, old_packet).action == "unsupported_capability"
    assert packet_json({"answer": old_answer, "packet": old_packet}) == frozen
    with pytest.raises(ValueError):
        validate("researcher", tool_answer(), old_packet)


@pytest.mark.parametrize("eligible", [False, True])
def test_offered_family_denial_fails_regardless_of_current_entry_signal(eligible):
    observed = packet()
    observed["evidence"]["e2"]["features"]["shared"]["eligible"] = eligible
    with pytest.raises(ValueError, match="already in the frozen tool inventory"):
        successor(answer(), observed)


def test_exact_unavailable_mechanism_is_a_valid_typed_abstention():
    value = answer()
    value["unsupported_basis"]["identifier"] = "pairs_reversion"
    parsed = successor(value)
    assert isinstance(parsed, IdeaV6) and isinstance(parsed, Idea)
    assert parsed.action == "unsupported_capability"
    assert parsed.unsupported_basis.identifier == "pairs_reversion"
    assert parsed.capability is None and parsed.dependency is None


@pytest.mark.parametrize(
    ("kind", "identifier"),
    [
        ("feature", "book_resilience"),
        ("analysis_tool", "execution_coverage"),
        ("strategy_family", "pairs_reversion"),
    ],
)
def test_missing_tool_request_is_typed_review_work_without_execution_authority(kind, identifier):
    value = tool_answer(kind, identifier)
    frozen = copy.deepcopy(value)
    parsed = successor(value)
    assert parsed.action == "request_tool"
    assert parsed.tool_request.identifier == identifier
    assert parsed.tool_request.kind == kind
    assert parsed.capability is None and parsed.dependency is None
    assert parsed.unsupported_basis is None
    assert parsed.evidence_ids == ["e0", "e2"]
    assert value == frozen


@pytest.mark.parametrize(
    ("kind", "identifier"),
    [
        ("strategy_family", "range_reversion"),
        ("feature", "atr"),
        ("analysis_tool", "matched_comparison"),
    ],
)
def test_existing_tool_cannot_be_requested_as_missing(kind, identifier):
    with pytest.raises(ValueError, match="already in the frozen tool inventory"):
        successor(tool_answer(kind, identifier))


def test_missing_feature_request_can_use_an_offered_strategy_family():
    parsed = successor(tool_answer())
    assert "range_reversion" in packet()["tool_inventory"]["strategy_family"]
    assert parsed.tool_request.kind == "feature"
    assert parsed.tool_request.identifier == "book_resilience"


def test_insufficient_current_evidence_uses_the_exact_data_dependency():
    value = answer("request_data")
    value.update(unsupported_basis=None, dependency="new_closed_bars")
    parsed = successor(value)
    assert parsed.action == "request_data" and parsed.dependency == "new_closed_bars"
    assert parsed.unsupported_basis is None and parsed.tool_request is None
    with pytest.raises(ValueError, match="offered wait requirement"):
        successor(value | {"dependency": "arbitrary_future_result"})


@pytest.mark.parametrize("field", ["unsupported_basis", "tool_request"])
def test_successor_nullable_action_fields_must_be_explicit(field):
    value = answer()
    del value[field]
    with pytest.raises(ValueError):
        successor(value)


@pytest.mark.parametrize("action", ["no_change", "propose_experiment", "request_data"])
def test_other_actions_cannot_smuggle_a_tool_request(action):
    value = tool_answer() | {"action": action}
    if action == "propose_experiment":
        value["capability"] = "r1"
    if action == "request_data":
        value["dependency"] = "new_closed_bars"
    with pytest.raises(ValueError, match="Only a tool request"):
        successor(value)


def test_typed_unsupported_basis_cannot_be_smuggled_into_tool_request():
    value = tool_answer() | {"unsupported_basis": {"kind": "feature", "identifier": "unknown"}}
    with pytest.raises(ValueError, match="Only an unsupported decision"):
        successor(value)


@pytest.mark.parametrize("identifier", ["range-reversion", "ATR", "a" * 65, "../tool", ""])
def test_capability_identifiers_are_bounded_exact_keys(identifier):
    with pytest.raises(ValueError):
        successor(tool_answer(identifier=identifier))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "too short"),
        ("required_inputs", []),
        ("required_inputs", ["i"]),
        ("required_inputs", ["input"] * 9),
        ("acceptance_checks", []),
        ("acceptance_checks", ["measurable acceptance"] * 7),
    ],
)
def test_tool_requests_require_bounded_reviewable_purpose_inputs_and_checks(field, value):
    request = tool_answer()
    request["tool_request"][field] = value
    with pytest.raises(ValueError):
        successor(request)


def test_inventory_cannot_omit_an_offered_family_to_make_denial_pass():
    observed = packet()
    observed["tool_inventory"]["strategy_family"].remove("range_reversion")
    with pytest.raises(ValueError, match="omits an offered strategy family"):
        successor(answer(), observed)


@pytest.mark.parametrize("problem", ["missing", "duplicate", "unknown", "over_bound"])
def test_inventory_is_explicit_bounded_and_unambiguous(problem):
    observed = packet()
    if problem == "missing":
        del observed["tool_inventory"]["feature"]
    elif problem == "duplicate":
        observed["tool_inventory"]["feature"].append("atr")
    elif problem == "unknown":
        observed["tool_inventory"]["execute"] = []
    else:
        observed["tool_inventory"]["feature"] = [f"feature_{i}" for i in range(65)]
    with pytest.raises(ValueError):
        successor(tool_answer(), observed)


def test_successor_packet_version_and_evidence_handles_fail_closed():
    with pytest.raises(ValueError, match="exact frozen packet contract"):
        successor(tool_answer(), packet() | {"contract": VERSION})
    with pytest.raises(ValueError, match="evidence handle"):
        successor(tool_answer() | {"evidence_ids": ["invented"]})


@pytest.mark.parametrize("operation", [schema, prompt, contract_hash])
def test_unknown_contract_is_not_implicitly_selected(operation):
    with pytest.raises(ValueError, match="contract version"):
        if operation is contract_hash:
            operation("not_reviewed")
        else:
            operation("researcher", "not_reviewed")


def test_review_schema_remains_unchanged_while_successor_packet_is_bound():
    from trading.role_worker import RoleWorker

    assert schema("reviewer", TOOL_REQUEST_VERSION) == schema("reviewer")
    assert "unsupported_basis" not in prompt("reviewer", TOOL_REQUEST_VERSION)
    assert "tool_request" not in prompt("reviewer", TOOL_REQUEST_VERSION)
    task = {
        "stage": "review",
        "context": {
            "contract": TOOL_REQUEST_VERSION,
            "question": {
                "question": "Does the frozen matched prospective method retain its evidence limits?"
            },
            "policy": {},
        },
        "proposal": {
            "kind": "independent",
            "strategy": {"family": "range_reversion"},
            "reference": {"family": "breakout"},
        },
        "evaluation": {
            "input_count": 600,
            "input_sha256": "a" * 64,
            "feature": {"eligible": False},
            "inputs": [{"private_detail_not_in_model_packet": True}],
        },
    }
    worker = RoleWorker.__new__(RoleWorker)  # Pure packet builder; no registry or transport owner.
    role, review_packet = worker._packet(task)
    assert role == "reviewer" and "tool_inventory" not in review_packet
    assert "inputs" not in review_packet["evidence"]["e1"]
    review = {
        "action": "inconclusive",
        "evidence_ids": ["e0"],
        "issues": ["missing_data"],
        "rationale": "Recorded missing executable coverage prevents a comparative conclusion.",
    }
    parsed = validate(
        "reviewer",
        review,
        review_packet,
        TOOL_REQUEST_VERSION,
    )
    assert isinstance(parsed, Review) and parsed.action == "inconclusive"
    with pytest.raises(ValueError, match="exact frozen packet contract"):
        validate("reviewer", review, review_packet | {"contract": VERSION}, TOOL_REQUEST_VERSION)
