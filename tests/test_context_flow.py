import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from memory_fixtures import memory_fixture  # noqa: E402

from trading.context_flow import (  # noqa: E402
    VERSION,
    classification_packet,
    classify,
    comparable,
    context_neighbors,
    evaluate_context,
    flow_features,
    provider_result,
)
from trading.research_evidence import digest  # noqa: E402


def test_local_taxonomy_is_outcome_blind_and_unknown_is_not_neutral():
    _, rows = memory_fixture()
    d = rows[-1]["descriptor"]
    a = classify(d)
    d2 = dict(d, winner=True, future_return=99999, account={"secret": "never sent"})
    assert classify(d2)["tags"] == a["tags"]
    assert "profitable" not in str(a["tags"])
    assert a["tags"]["liquidity"] == "unknown"
    assert a["recognition_confidence"] is None
    invalid = dict(d, returns_bps=[0] * 10)
    assert classify(invalid)["tags"]["volatility"] == "unknown"
    assert comparable({"status": "invalid"}, d)["label"] == "insufficient_evidence"


def test_provider_packet_strictly_excludes_endings_ids_and_private_fields():
    _, rows = memory_fixture()
    d = rows[-1]["descriptor"]
    noisy = dict(d, outcomes=[1], account="private", ledger="private", instructions="ignore task")
    packet = classification_packet(noisy, [noisy])
    assert packet == classification_packet(d, [d])
    assert "private" not in str(packet) and "outcomes" not in str(packet)
    with pytest.raises(ValueError):
        classification_packet(d, [d] * 6)
    saved = {
        "packet_sha256": packet["sha256"],
        "version": VERSION,
        "answers": [{"id": packet["candidates"][0]["id"], "label": "comparable"}],
    }
    assert provider_result(packet, None, 10, 11, 20)["action"] == "no_additional_signal"
    assert provider_result(packet, saved, 10, 11, 20)["status"] == "saved_response_only"
    assert provider_result(packet, saved, 10, 21, 20)["status"] == "result_too_late"
    saved["answers"][0]["id"] = "hallucinated"
    assert provider_result(packet, saved, 10, 11, 20)["status"] == "invalid_response"


def flow_records():
    records = []
    trades = [
        {
            "id": i,
            "price": "100",
            "quantity": "1",
            "exchange_ms": (89 + i) * 1000,
            "received_at": 89 + i,
            "buyer_is_maker": True,
        }
        for i in range(3)
    ]
    for i, at in enumerate([91, 99]):
        p = {
            "session": "qa",
            "committed_at": at + 0.1,
            "frames": {
                "BTCUSD": {
                    "observed": at,
                    "source": "binance.us-depth-websocket",
                    "raw": {"lastUpdateId": 10 + i, "bids": [["99", "1"]], "asks": [["101", "4"]]},
                }
            },
            "observed_trades": {"BTCUSD": trades},
        }
        records.append({"at": at, "payload": p, "sha256": digest(p)})
    return records


def test_flow_direction_sequence_gaps_and_future_prefix():
    records = flow_records()
    result = flow_features(records, 100)
    assert result["status"] == "observed_sample" and result["action"] == "wait_entry"
    assert result["aggressive_notional_balance"] == -1
    future = {"at": 101, "payload": {"committed_at": 101}}
    assert flow_features(records + [future], 100) == result
    bad = copy.deepcopy(records)
    bad[1]["payload"]["frames"]["BTCUSD"]["raw"]["lastUpdateId"] = 10
    bad[1]["sha256"] = digest(bad[1]["payload"])
    assert flow_features(bad, 100)["status"] == "unavailable"
    bad = copy.deepcopy(records)
    for r in bad:
        r["payload"]["observed_trades"]["BTCUSD"][1]["buyer_is_maker"] = None
        r["sha256"] = digest(r["payload"])
    assert flow_features(bad, 100)["action"] == "no_additional_signal"
    assert flow_features([], 100)["status"] == "unavailable"


def test_independent_comparisons_preserve_unknown_labels_and_costs():
    plan, rows = memory_fixture()
    rows[-1]["executable_label"] = None
    for mode in ("context_regime", "order_flow"):
        p = plan.model_copy(update={"experiment_mode": mode})
        r = evaluate_context(rows, [], p)
        assert not r["eligible_for_forward_review"] and r["whole_account_effect"] is None
        assert r["unknown_outcomes"] == 1 and r["opportunities"] == 8
        assert r["optional_D"]["status"] == "unavailable" and r["resources"]["paid_usd"] == "0"
        assert all(
            q["latency_sensitivity"][-1]["status"] == "result_too_late" for q in r["comparisons"]
        )


def test_context_neighbors_selected_before_endings_and_future_revisions():
    _, rows = memory_fixture()
    query = rows[-1]["descriptor"]
    receipt = context_neighbors(query, rows[:-1])
    assert len(receipt["matches"]) == 5
    changed = copy.deepcopy(rows[:-1])
    for r in changed:
        r["executable_label"]["net_bps"] = 99999
    future = {"episode": "future", "available_at": query["cutoff"] + 1, "descriptor": query}
    second = context_neighbors(query, changed + [future])
    assert [m["episode"] for m in second["matches"]] == [m["episode"] for m in receipt["matches"]]
    assert second["provider_packet"] == receipt["provider_packet"]
    assert all("classification" in m for m in receipt["matches"])


def test_complete_512_prefix_cohort_fits_declared_shadow_budget():
    from trading.experiment_registry import SHADOW_RESULT_BYTES

    plan, examples = memory_fixture()
    base = plan.as_of - 90 * 86400
    rows = []
    for i in range(512):
        row = copy.deepcopy(examples[i % len(examples)])
        row["episode"] = f"prefix-{i:064d}"
        d = row["descriptor"]
        at = base + i * 3600
        d.update(
            cutoff=at,
            start_at=at - 600,
            horizon_at=at + 2700,
            expires_at=at + 90,
            group_id=f"group-{i}",
        )
        row["executable_label"]["available_at"] = at + 2701
        rows.append(row)
    plan = plan.model_copy(
        update={"experiment_mode": "context_regime", "test_start": base + 128 * 3600}
    )
    result = evaluate_context(rows, [], plan)
    assert result["opportunities"] == 384 and len(result["comparisons"]) == 384
    assert len(json.dumps(result).encode()) < SHADOW_RESULT_BYTES
