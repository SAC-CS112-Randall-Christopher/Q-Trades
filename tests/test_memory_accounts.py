import copy

import pytest
from test_execution_replay import slices

from scripts.memory_fixtures import memory_fixture
from trading.execution_replay import source_hashes
from trading.memory_accounts import compare_accounts, evaluate_account_memory
from trading.memory_dataset import mature_snapshot
from trading.memory_quality import evaluate_memory
from trading.research_evidence import digest


def inputs(decision_packet, count=3):
    from decimal import Decimal

    from trading.paper_strategy import VARIANTS, Bar, features

    recorder, template, frames, _ = decision_packet
    raw = template["bars"]["BTCUSD"]
    raw[-1]["volume"] = "100"
    for r in raw:
        r["low"] = str(Decimal(r["close"]) - Decimal("0.5"))
    # Real feature reproduction: last-bar volume makes this an eligible breakout.
    bars = [
        Bar(
            r["open_ms"],
            *(Decimal(r[k]) for k in ("open", "high", "low", "close", "volume")),
            r["close_ms"],
        )
        for r in raw
    ]
    actual = {"BTCUSD": {v: features(bars, template["at"], v) for v in VARIANTS}}
    template["study"] = copy.deepcopy(actual)
    decision_packet = recorder, template, frames, actual
    from unittest.mock import patch

    # Explicit synthetic archive clock: its first stored prefix arrives at the first observation.
    with patch("trading.research_evidence.time.time", return_value=template["at"] + 2):
        recorder, records = slices(
            decision_packet,
            offsets=tuple(2 * (i + 1) for i in range(count)),
            quantities=("100",) * count,
        )
    plan, rows = memory_fixture()
    start, end = records[0]["payload"]["at"], records[-1]["payload"]["at"]
    offset = start - plan.test_start
    for row in rows:
        row["available_at"] += offset
        row["executable_label"]["available_at"] += offset
        for key in ("start_at", "cutoff", "horizon_at", "expires_at"):
            row["descriptor"][key] += offset
    plan = plan.model_copy(
        update={
            "account_comparison": True,
            "test_start": start,
            "test_end": end,
            "as_of": end,
            "common_daily_usd": "2",
            "numerical_daily_usd": "1",
            "contextual_daily_usd": "3",
            "cpu_hour_usd": "0.50",
        }
    )
    fit = evaluate_memory(rows, plan, seed_only=True)
    artifacts = {c["arm"]: c["artifact"] for c in fit["candidate_group"]}
    return recorder, records, plan, rows, artifacts


def test_full_account_comparison_marks_open_positions_and_prices_adverse_costs(decision_packet):
    recorder, records, plan, rows, artifacts = inputs(decision_packet)
    original = copy.deepcopy(records)
    result = compare_accounts(records, artifacts, plan, source_hashes())
    assert records == original
    assert result["status"] == "complete"
    assert result["source_reconciled_records"] == len(records)
    assert result["accounts"]["A"]["positions"], result["accounts"]["A"]["decisions"]
    assert result["accounts"]["A"]["sample"]["cash"] != "100"
    assert all(a["net_account_usd"] is not None for a in result["accounts"].values())
    assert result["contributions"][1]["conclusion"] == "unfavorable"
    assert result["passive_benchmark"]["state"]["start"] == plan.test_start
    assert len(result["passive_benchmark"]["entry_fills"]) == 1
    assert result["passive_benchmark"]["net_account_usd"] is not None
    assert result["financial_authority"] is False
    final = evaluate_account_memory(
        rows, {"records": records, "source_files": source_hashes()}, plan
    )
    assert final["whole_account_effect"]["B"] is not None
    assert not final["eligible_for_exploratory_paper"]  # Synthetic cannot be admitted.
    assert not final["eligible_for_forward_review"]
    recorder._archive.close()


def test_complete_period_refuses_corrupted_missing_or_unobserved_boundaries(decision_packet):
    recorder, records, plan, _, artifacts = inputs(decision_packet)
    with pytest.raises(ValueError, match="Unrecorded"):
        compare_accounts([records[0], records[2]], artifacts, plan, source_hashes())
    bad = copy.deepcopy(records)
    bad[-1]["payload"]["after_tick_sha256"] = "0" * 64
    bad[-1]["sha256"] = digest(bad[-1]["payload"])
    with pytest.raises(ValueError, match="reconcile"):
        compare_accounts(bad, artifacts, plan, source_hashes())
    with pytest.raises(ValueError, match="start/end"):
        compare_accounts(
            records,
            artifacts,
            plan.model_copy(update={"test_end": plan.test_end + 20}),
            source_hashes(),
        )
    recorder._archive.close()


def test_unpriced_cost_is_unavailable_and_cannot_create_admission(decision_packet):
    recorder, records, plan, rows, artifacts = inputs(decision_packet)
    plan = plan.model_copy(update={"contextual_daily_usd": None})
    result = compare_accounts(records, artifacts, plan, source_hashes())
    assert result["accounts"]["C"]["net_account_usd"] is None
    assert result["accounts"]["C"]["trading_net_usd"] is not None
    assert result["contributions"][1]["paired_account_effect"] is None
    final = evaluate_account_memory(
        rows, {"records": records, "source_files": source_hashes()}, plan
    )
    assert not final["eligible_for_exploratory_paper"]
    recorder._archive.close()


def test_account_interval_keeps_hash_verified_compact_training_labels(decision_packet):
    recorder, records, plan, rows, _ = inputs(decision_packet)
    for row in rows:
        row["evidence_reference"] = {"archive": "compact", "episode": row["episode"]}
    original = copy.deepcopy(rows)
    snapshot = {"rows": rows, "records": records, "source_files": source_hashes()}
    assert mature_snapshot(snapshot, plan.as_of) == original
    recorder._archive.close()


def test_observed_exploratory_handoff_selects_exact_candidate_without_qualification(
    tmp_path, decision_packet
):
    import time
    from unittest.mock import patch

    from trading.experiment_registry import ExperimentRegistry
    from trading.paper_challengers import admit
    from trading.paper_engine import PaperEngine, initial_state
    from trading.paper_learning import matched_control
    from trading.prospective_review import ProspectiveReview, ProspectiveSpec

    recorder, records, plan, rows, artifacts = inputs(decision_packet)
    result = evaluate_account_memory(
        rows, {"records": records, "source_files": source_hashes()}, plan
    )
    # Constructed observed-contract projection tests authority gates; it is not venue proof.
    result["evidence_kind"] = "observed_public_quotes"
    result["eligible_for_exploratory_paper"] = True
    assert not result["eligible_for_forward_review"]
    registry = ExperimentRegistry(tmp_path / "lab.sqlite")
    with patch.object(registry, "get", return_value={"result": result}):
        now = time.time()
        engine = PaperEngine(initial_state(now), now)
        before = copy.deepcopy(engine.state["accounts"])
        receipt = admit(engine, plan.request_id, artifacts["B"], "100", "2")
        name = receipt["account"]
        control = matched_control(engine, name)["account"]
        assert all(engine.state["accounts"][n] == a for n, a in before.items())
        assert (
            admit(engine, plan.request_id, artifacts["B"], "100", "2")["status"]
            == "already_applied"
        )
        review = ProspectiveReview(registry)
        choices = review.candidates(engine.state)
        assert choices[0]["account"] == name and choices[0]["control"] == control
        spec = ProspectiveSpec(
            request_id="exploratory-review-01",
            name="Exploratory review",
            starts_at=now + 3600,
            purpose="exploratory_memory",
            candidate=name,
            component_requests=[plan.request_id],
        )
        bad = spec.model_copy(update={"request_id": "wrong-component-02", "component_requests": []})
        with pytest.raises(ValueError, match="exact"):
            review.freeze(bad, engine.state)
        frozen = review.freeze(spec, engine.state)
        assert frozen["spec"]["candidate"] == name
        assert frozen["candidate_control"] == control
        assert frozen["components"][0]["request"] == plan.request_id
        assert (
            review.report(spec.request_id, engine.state, {"windows": []}, now)["decision"]
            == "no_promotion"
        )
        result["eligible_for_exploratory_paper"] = False
        assert review.candidates(engine.state) == []
    registry.close()
    recorder._archive.close()


def test_account_comparison_uses_all_records_beyond_short_replay_limit_and_actual_availability(
    decision_packet,
):
    recorder, records, plan, _, artifacts = inputs(decision_packet, count=40)
    result = compare_accounts(records, artifacts, plan, source_hashes())
    assert result["period"]["records"] == 40
    assert result["period"]["last_observation"] == plan.test_end
    assert len(result["passive_benchmark"]["entry_fills"]) == 1
    assert result["passive_benchmark"]["state"]["start"] == plan.test_start
    first = result["accounts"]["A"]["decisions"][0]["at"]
    for arm in ("B", "C"):
        decisions = result["accounts"][arm]["decisions"]
        assert decisions[0]["at"] > first
        assert all(q["available_at"] is None or q["available_at"] <= q["at"] for q in decisions)
    recorder._archive.close()


def test_normal_worker_retains_account_results_and_never_qualifies_synthetic(decision_packet):
    import json

    from trading.experiment_registry import fingerprint
    from trading.experiment_worker import code_fingerprint, evaluate

    recorder, records, plan, rows, _ = inputs(decision_packet)
    for row in rows:
        row["evidence_reference"] = {"archive": "compact", "episode": row["episode"]}
    snapshot = {"rows": rows, "records": records, "source_files": source_hashes()}
    result = evaluate(
        {
            "plan": plan.model_dump_json(),
            "snapshot": json.dumps(snapshot),
            "snapshot_sha256": fingerprint(snapshot),
            "code_sha256": code_fingerprint(),
        }
    )
    assert result["account_comparison"]["status"] == "complete"
    assert result["whole_account_effect"]["C"] is not None
    assert result["decision"] == "reject"
    assert not result["eligible_for_exploratory_paper"]
    assert not result["eligible_for_forward_review"]
    recorder._archive.close()


def test_api_admits_observed_exploratory_pair_and_refuses_synthetic(tmp_path, decision_packet):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from fastapi.testclient import TestClient

    from trading.api import create_app
    from trading.config import Settings

    recorder, records, plan, rows, _ = inputs(decision_packet)
    result = evaluate_account_memory(
        rows, {"records": records, "source_files": source_hashes()}, plan
    )
    paper = Mock()
    paper.forward_admit.return_value = {"status": "created", "account": "test-forward"}
    paper.forward_control.return_value = {"status": "created", "account": "test-control"}
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.lab = SimpleNamespace(
            registry=SimpleNamespace(get=lambda _: {"status": "completed", "result": result})
        )
        app.state.paper = paper
        body = {
            "family": "memory_entry",
            "arm": "B",
            "starting_cash": "100",
            "operating_daily_usd": "2",
        }
        endpoint = f"/api/lab/experiments/{plan.request_id}/forward"
        assert (
            client.post(endpoint, json=body, headers={"X-Local-Operator": "1"}).status_code == 409
        )
        assert not paper.forward_admit.called
        # Authority contract projection only; synthetic fixtures remain marked in other tests.
        result.update(evidence_kind="observed_public_quotes", eligible_for_exploratory_paper=True)
        response = client.post(endpoint, json=body, headers={"X-Local-Operator": "1"})
        assert response.status_code == 200, response.text
        assert response.json()["matched_control"]["account"] == "test-control"
        paper.forward_control.assert_called_once_with("test-forward")
        assert not result["eligible_for_forward_review"]
    recorder._archive.close()
