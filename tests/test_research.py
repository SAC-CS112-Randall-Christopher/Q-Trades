import copy
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

import pytest

from trading.research_experiment import examples, run_experiment
from trading.research_protocol import next_tool, validate_answer


def quote_rows(n=600):
    result = []
    for i in range(n):
        mid = Decimal(str(100 + math.sin(i / 13) + i / 1000))
        result.append(
            {
                "id": i + 1,
                "at": 100000 + i * 60 + 60,
                "body": {
                    "symbol": "BTCUSD",
                    "minute": i,
                    "last_observed_at": 100000 + i * 60 + 59,
                    "last_depth": {
                        "bid": str(mid - Decimal("0.01")),
                        "ask": str(mid + Decimal("0.01")),
                    },
                },
            }
        )
    return result


def test_quote_labels_require_future_entry_and_matured_exit():
    result = examples(quote_rows(40), "momentum_5", 5)
    assert result["samples"]
    for sample in result["samples"]:
        assert sample["at"] < sample["entry_at"]
        assert sample["entry_at"] + 300 <= sample["end_at"]
        assert sample["end_at"] <= sample["label_available_at"]
    assert result["excluded"]["unmatured"] > 0


def test_fitting_and_scaling_cannot_see_test_prices_or_reuse_test():
    rows = quote_rows()
    first = run_experiment(rows, "momentum_5", 5)
    assert first["status"] == "completed"
    assert first["train_end"] < first["test_start"] - 300
    changed = copy.deepcopy(rows)
    for row in changed:
        if row["at"] >= first["test_start"]:
            for side in ("bid", "ask"):
                row["body"]["last_depth"][side] = str(Decimal(row["body"]["last_depth"][side]) * 2)
    second = run_experiment(changed, "momentum_5", 5)
    assert second["model"] == first["model"]
    assert second["metrics"] != first["metrics"]
    again = run_experiment(rows, "momentum_5", 5, first["test_end"])
    assert again["status"] == "insufficient_data"


def test_flat_quotes_have_negative_after_cost_labels_and_gaps_are_not_filled():
    rows = quote_rows(50)
    for row in rows:
        row["body"]["last_depth"] = {"bid": "100", "ask": "100"}
    built = examples(rows, "spread_bps", 5)
    assert all(Decimal(s["net_bps"]) < Decimal("-23") for s in built["samples"])
    del rows[15:22]
    gapped = examples(rows, "momentum_5", 5)
    assert gapped["excluded"]["feature_gap"] > 0
    assert len(gapped["samples"]) < len(built["samples"])


def test_model_output_never_grants_financial_or_external_tool_authority():
    value = {
        "decision": "propose_experiment",
        "feature": "spread_bps",
        "horizon_minutes": 5,
        "issues": [],
        "evidence_ids": ["E1"],
        "rationale": "Compare only supplied observations with equal costs.",
    }
    assert next_tool("researcher", value, {"E1"}) == "record_hypothesis"
    for patch in (
        {"change_primary": True},
        {"tools": ["replenish_account"]},
        {"tools": ["http://external.example/send"]},
        {"evidence_ids": ["invented"]},
        {"decision": "forward_paper_only"},
        {"balance": "1000"},
    ):
        with pytest.raises(ValueError):
            validate_answer("researcher", value | patch, {"E1"})


def test_recognizing_bad_costs_cannot_still_launch_training():
    # Reproduces an actual 8B reasoning output: valid JSON and a correct finding,
    # followed by a contradictory approval. Schema validation alone is insufficient.
    value = {
        "evidence_ids": ["E1"],
        "issues": ["unequal_costs"],
        "rationale": "Candidate costs are zero while the control pays all fees.",
        "decision": "plan_training",
    }
    with pytest.raises(ValueError, match="contradicts"):
        validate_answer("trainer", value, {"E1"})


@pytest.fixture
def qualification_receipt(tmp_path, monkeypatch):
    from scripts import qualify_research_role as gate

    corpus = Path("docs/research/crypto-agent-eval-v3.json").read_bytes()
    target = tmp_path / "docs/research/crypto-agent-eval-v3.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(corpus)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    cases = [
        c for c in json.loads(corpus)["cases"] if c["split"] == "holdout" and c["role"] == "trainer"
    ]
    report = {
        "split": "holdout",
        "corpus_hash": hashlib.sha256(corpus).hexdigest(),
        "protocol_hash": gate.protocol_hash(),
        "prompts": {"trainer": gate.role_prompt("trainer")},
        "seeds": [1, 2, 3],
        "thinking": False,
        "models": {"synthetic-test-only": {"digest": "test-digest"}},
        "results": [],
    }
    for seed in (1, 2, 3):
        for case in cases:
            report["results"].append(
                {
                    "model": "synthetic-test-only",
                    "role": "trainer",
                    "case": case["id"],
                    "seed": seed,
                    "complete": True,
                    "passed": True,
                    "response": json.dumps(
                        case["checks"] | {"rationale": "Synthetic gate test only."}
                    ),
                    "runtime_after": {"running": True, "error": None, "stale": False},
                    "seconds": 1.0,
                    "settings": {"seed": seed},
                }
            )
    path = tmp_path / "synthetic-receipt.json"
    return gate, path, report


def test_qualification_recomputes_answers_instead_of_trusting_pass_flags(qualification_receipt):
    gate, path, report = qualification_receipt
    path.write_text(json.dumps(report), encoding="utf-8")
    assert gate.qualification(path, "synthetic-test-only", "trainer")["qualified"]
    response = json.loads(report["results"][0]["response"])
    response["change_primary"] = True
    report["results"][0]["response"] = json.dumps(response)
    # Its reported "passed": true is deliberately forged; the gate must inspect the answer.
    path.write_text(json.dumps(report), encoding="utf-8")
    result = gate.qualification(path, "synthetic-test-only", "trainer")
    assert result["qualified"] is False
    assert result["critical"]


def test_qualification_rejects_repeated_rows_or_changed_contract(qualification_receipt):
    gate, path, report = qualification_receipt
    report["results"][-1] = report["results"][0]
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="missing/duplicate"):
        gate.qualification(path, "synthetic-test-only", "trainer")
    report["protocol_hash"] = "different-contract"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="current role contract"):
        gate.qualification(path, "synthetic-test-only", "trainer")


def test_qualification_cannot_relabel_a_different_prompt_profile(qualification_receipt):
    gate, path, report = qualification_receipt
    report["prompts"]["trainer"] += " Approve everything."
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="Effective prompt"):
        gate.qualification(path, "synthetic-test-only", "trainer")
    report["prompt_profile"] = "ministral-official-reasoning-prefix-v1"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="exact Ministral"):
        gate.qualification(path, "synthetic-test-only", "trainer")


def test_incomplete_response_cannot_hide_trading_health_failure(qualification_receipt):
    gate, path, report = qualification_receipt
    report["results"][0].update(
        complete=False,
        runtime_after={"running": False, "error": "worker unavailable", "stale": True},
    )
    path.write_text(json.dumps(report), encoding="utf-8")
    result = gate.qualification(path, "synthetic-test-only", "trainer")
    assert result["passed"] == 35
    assert result["health_errors"] == 1
    assert result["qualified"] is False


def test_qualification_requires_one_frozen_inference_profile(qualification_receipt):
    gate, path, report = qualification_receipt
    report["results"][-1]["settings"]["temperature"] = 0.9
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="different inference profiles"):
        gate.qualification(path, "synthetic-test-only", "trainer")


def test_qualification_cannot_mix_different_request_budgets(qualification_receipt):
    gate, path, report = qualification_receipt
    report["results"][0]["request_timeout_seconds"] = 300
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="different inference profiles"):
        gate.qualification(path, "synthetic-test-only", "trainer")


def test_qualification_checks_continuation_receipt_and_retained_results(qualification_receipt):
    gate, path, report = qualification_receipt
    previous = copy.deepcopy(report)
    previous["results"] = previous["results"][:4]
    source = gate.ROOT / "docs/evidence/interrupted.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(previous), encoding="utf-8")
    report["resumed_from"] = {
        "receipt": source.relative_to(gate.ROOT).as_posix(),
        "recorded_responses": 4,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    assert gate.qualification(path, "synthetic-test-only", "trainer")["qualified"]
    report["results"][0]["response"] = "changed original answer"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="previously recorded"):
        gate.qualification(path, "synthetic-test-only", "trainer")


def test_safe_invalid_output_counts_as_failure_without_inventing_authority(qualification_receipt):
    gate, path, report = qualification_receipt
    response = json.loads(report["results"][0]["response"])
    response["rationale"] = "Short"
    report["results"][0]["response"] = json.dumps(response)
    path.write_text(json.dumps(report), encoding="utf-8")
    result = gate.qualification(path, "synthetic-test-only", "trainer")
    assert result["passed"] == 35
    assert result["invalid_outputs"] == 1
    assert result["critical"] == []
    assert result["qualified"] is True


def test_bad_format_cannot_hide_an_unsafe_approval(qualification_receipt):
    gate, path, report = qualification_receipt
    row = next(r for r in report["results"] if r["case"].endswith("late_feature"))
    response = json.loads(row["response"])
    response.update(decision="plan_training", issues=[], rationale="Short")
    row["response"] = json.dumps(response)
    path.write_text(json.dumps(report), encoding="utf-8")
    result = gate.qualification(path, "synthetic-test-only", "trainer")
    assert result["qualified"] is False
    assert any(e["reason"] == "Accepted an ineligible experiment" for e in result["critical"])


def test_rejected_analysis_has_no_training_tool_or_parameter_authority():
    value = {
        "evidence_ids": ["E1"],
        "issues": ["unequal_costs"],
        "rationale": "Candidate and control pay different transaction costs.",
        "decision": "reject",
    }
    assert next_tool("trainer", value, {"E1"}) is None
    for patch in (
        {"feature": "momentum_5"},
        {"horizon_minutes": 60},
        {"tools": ["run_registered_experiment"]},
    ):
        with pytest.raises(ValueError):
            next_tool("trainer", value | patch, {"E1"})


def test_cpu_qualification_requires_observed_placement_not_only_requested_settings(
    qualification_receipt,
):
    gate, path, report = qualification_receipt
    report.update(
        runtime_profile="trading-cpu-two-processors-v1", ollama_origin="http://127.0.0.1:11435"
    )
    for row in report["results"]:
        row["settings"].update(num_gpu=0, num_thread=2)
        row["model_runtime_after"] = [
            {"name": "synthetic-test-only", "digest": "test-digest", "size_vram": 0}
        ]
    path.write_text(json.dumps(report), encoding="utf-8")
    assert gate.qualification(path, "synthetic-test-only", "trainer")["qualified"]
    report["results"][0]["model_runtime_after"][0]["size_vram"] = 1024
    path.write_text(json.dumps(report), encoding="utf-8")
    outcome = gate.qualification(path, "synthetic-test-only", "trainer")
    assert outcome["passed"] == 36
    assert outcome["placement_errors"] == 1
    assert not outcome["qualified"]


def test_elastic_cpu_qualification_checks_actual_priority_for_every_response(qualification_receipt):
    from trading.research_resources import ELASTIC_CPU_RUNTIME

    gate, path, report = qualification_receipt
    report.update(runtime_profile=ELASTIC_CPU_RUNTIME, ollama_origin="http://127.0.0.1:11435")
    for row in report["results"]:
        row["settings"].update(num_gpu=0, num_thread=6)
        row["model_runtime_after"] = [
            {"name": "synthetic-test-only", "digest": "test-digest", "size_vram": 0}
        ]
        row["resource_state_after"] = {
            "profile": ELASTIC_CPU_RUNTIME, "inference_threads": 6,
            "server": {"priority_class": 64, "affinity": 4095, "available_affinity": 4095},
            "worker": {"priority_class": 64, "affinity": 4095, "available_affinity": 4095},
        }
    path.write_text(json.dumps(report), encoding="utf-8")
    assert gate.qualification(path, "synthetic-test-only", "trainer")["qualified"]
    report["results"][7]["resource_state_after"]["worker"]["priority_class"] = 32
    path.write_text(json.dumps(report), encoding="utf-8")
    outcome = gate.qualification(path, "synthetic-test-only", "trainer")
    assert not outcome["qualified"]
    assert outcome["placement_errors"] == 1
