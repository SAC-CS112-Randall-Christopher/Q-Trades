import copy
import json
import sqlite3
from decimal import Decimal

import pytest

from trading.pattern_memory import CONTRACT, descriptor, lookup, market_outcome
from trading.research_evidence import EvidenceArchive, digest, evidence_record


def rows_at(cutoff, count=60, offset="0"):
    end = int(cutoff // 60) * 60000
    return [
        {
            "open_ms": end - (count - i) * 60000,
            "close_ms": end - (count - i) * 60000 + 59999,
            "open": str(Decimal(100) + Decimal(offset) + Decimal(i) / 100),
            "close": str(Decimal(100) + Decimal(offset) + Decimal(i) / 100),
            "high": str(Decimal(100) + Decimal(offset) + Decimal(i) / 100 + Decimal(".05")),
            "low": str(Decimal(100) + Decimal(offset) + Decimal(i) / 100 - Decimal(".05")),
            "volume": "10",
            "available_at": cutoff - 0.1,
        }
        for i in range(count)
    ]


def entry(cutoff, name, offset="0"):
    d = descriptor(rows_at(cutoff, offset=offset), cutoff, {"liquidity": "unknown"}, "synthetic")
    assert d["status"] == "available"
    return {
        "episode": name,
        "record_id": int(cutoff),
        "available_at": cutoff + 0.01,
        "descriptor": d,
        "descriptor_sha256": digest(d),
    }


def test_full_prefix_invariance_descriptors_matches_classification_and_saved_receipt():
    cutoff = 20000.0
    prefix = rows_at(cutoff)
    d = descriptor(prefix, cutoff, {"liquidity": "unknown"}, "synthetic")
    original = entry(6000.0, "historical")
    original["outcome"] = {"available_at": 9000.0, "status": "available", "return_bps": "-20"}
    late = entry(12000.0, "delayed-ending")
    late["outcome"] = {"available_at": cutoff + 10, "status": "available", "return_bps": "1000"}
    library = [original, late]
    saved = lookup(d, library, cutoff + 0.1)
    # Old exchange times alone cannot make this revised or malformed later data eligible.
    revised = copy.deepcopy(prefix[-1])
    revised.update(close="99999", available_at=cutoff + 2)
    future = {"available_at": cutoff + 1, "open_ms": "invalid future", "outcome": "winner"}
    after = descriptor(prefix + [future, revised], cutoff, {"liquidity": "unknown"}, "synthetic")
    library[1]["outcome"]["return_bps"] = "-99999"
    library.append({"available_at": cutoff + 1, "descriptor": {"anything": "changed"}})
    repeated = lookup(after, list(reversed(library)), cutoff + 0.1)
    assert after == d and repeated == saved
    assert repeated["classification"] == saved["classification"]
    assert repeated["changed_decision"] is False
    assert (
        next(m for m in repeated["matches"] if m["episode"] == "historical")["outcome_status"]
        == "available"
    )


def test_exhaustive_reference_ranking_is_outcome_blind_and_preserves_mixed_endings():
    d = descriptor(rows_at(30000), 30000, {}, "synthetic")
    library = [entry(4000, "a"), entry(8000, "b", "10"), entry(12000, "c", "40")]
    for candidate, value in zip(library, ["-100", "200", "-300"], strict=True):
        candidate["outcome"] = {"status": "available", "available_at": 16000, "return_bps": value}
    result = lookup(d, library, 30000.1)
    reference = sorted(
        library,
        key=lambda e: sum(
            (a - b) ** 2
            for a, b in zip(d["returns_bps"], e["descriptor"]["returns_bps"], strict=True)
        ),
    )
    assert [m["episode"] for m in result["matches"]] == [e["episode"] for e in reference]
    assert {m["outcome"]["return_bps"] for m in result["matches"]} == {"-100", "200", "-300"}
    for item in library:
        item["outcome"]["return_bps"] = "5000"
    changed = lookup(d, library, 30000.1)
    assert [m["episode"] for m in changed["matches"]] == [m["episode"] for m in result["matches"]]
    assert changed["library_sha256"] == result["library_sha256"]


def test_overlapping_and_duplicate_event_groups_do_not_become_independent_support():
    d = descriptor(rows_at(30000), 30000, {}, "synthetic")
    library = [entry(4000, "a"), entry(4100, "duplicate"), entry(29000, "overlap")]
    result = lookup(d, library, 30000.1)
    assert len(result["matches"]) == result["distinct_groups"] == 1
    assert any(
        c.get("excluded") == "Overlapping lookback/outcome event" for c in result["candidates"]
    )
    assert any(
        c.get("excluded") == "Group concentration / neighbor cap" for c in result["candidates"]
    )
    assert result["recognition_confidence"] is None


def test_overlap_across_calendar_group_boundary_does_not_duplicate_support():
    d = descriptor(rows_at(30000), 30000, {}, "synthetic")
    library = [entry(6500, "a"), entry(6650, "b")]
    assert library[0]["descriptor"]["group_id"] != library[1]["descriptor"]["group_id"]
    result = lookup(d, library, 30000.1)
    assert result["distinct_groups"] == len(result["matches"]) == 1
    assert any(c.get("overlapping_historical_event") for c in result["candidates"])


@pytest.mark.parametrize("failure", ["gap", "flat", "missing", "late"])
def test_invalid_descriptors_and_unavailable_context_are_explicit(failure):
    rows = rows_at(20000)
    if failure == "gap":
        rows.pop(-3)
    elif failure == "flat":
        for row in rows:
            row["close"] = "100"
    elif failure == "missing":
        rows = rows[:3]
    else:
        for row in rows:
            row["available_at"] = 20001
    d = descriptor(rows, 20000, {"order_flow": "unavailable"}, "synthetic")
    assert d["status"] == "invalid_input"
    result = lookup(d, [], 20000.1)
    assert result["status"] == "data_incomplete" and not result["matches"]
    assert result["fallback"].startswith("No additional signal")


def test_delayed_market_outcome_is_separate_and_never_executable_pnl():
    episode = entry(6000, "first")
    horizon = episode["descriptor"]["horizon_at"]
    with pytest.raises(ValueError, match="not matured"):
        market_outcome(episode, [], horizon - 1, horizon)
    rows = rows_at(horizon + 1, 60, "10")
    result = market_outcome(episode, rows, horizon + 1, horizon + 2)
    assert result["status"] == "available" and result["observed_bars"] == 45
    assert result["realized_pnl"] is None and result["remaining_executable_opportunity"] is None
    assert result["ambiguity"].startswith("Intrabar ordering unknown")
    assert Decimal(result["favorable_excursion_bps"]) >= 0
    assert Decimal(result["adverse_excursion_bps"]) <= 0
    rows.pop(-10)
    incomplete = market_outcome(episode, rows, horizon + 1, horizon + 2)
    assert incomplete["status"] == "unavailable" and incomplete["required_bars"] == 45


def test_library_versions_and_response_expiry_preserve_baseline_fallback():
    d = descriptor(rows_at(20000), 20000, {}, "synthetic")
    candidate = entry(6000, "earlier")
    candidate["descriptor"]["contract"] = {**CONTRACT, "version": "other"}
    result = lookup(d, [candidate], 20100)
    assert result["status"] == "result_too_late" and not result["matches"]
    assert result["candidates"][0]["excluded"].startswith("Incompatible")


def test_archive_episode_outcome_reopen_restart_and_future_append_are_immutable(
    tmp_path, decision_packet, monkeypatch
):
    _, packet, _, _ = decision_packet
    at = packet["at"]
    clock = [at + 0.1]
    monkeypatch.setattr("trading.research_evidence.time.time", lambda: clock[0])
    path = tmp_path / "archive.sqlite"
    archive = EvidenceArchive(path)
    archive.append([packet])
    original = evidence_record(path, 1)
    assert original["payload"]["episode"]["descriptor"]["status"] == "available"
    assert original["subsequent_outcome"]["status"] == "outcome_pending"
    later = copy.deepcopy(packet)
    later.pop("episode", None)
    later["at"] = at + 2701
    later["bars"]["BTCUSD"] = rows_at(later["at"], 60, "10")
    later["feature_origin"]["BTCUSD"]["computed_at"] = later["at"]
    clock[0] = later["at"] + 0.1
    archive.append([later])
    reopened = evidence_record(path, 1)
    assert reopened["payload"] == original["payload"]
    assert reopened["subsequent_outcome"]["payload"]["status"] == "available"
    outcome = reopened["subsequent_outcome"]
    archive.close()
    archive = EvidenceArchive(path)
    clock[0] += 60
    future = copy.deepcopy(later)
    future["at"] += 60
    for row in future["bars"]["BTCUSD"]:
        row["close"] = "99999"
        row["available_at"] = future["at"] + 0.1
    archive.append([future])
    assert evidence_record(path, 1)["payload"] == original["payload"]
    assert evidence_record(path, 1)["subsequent_outcome"] == outcome
    assert archive.snapshot()["outcomes"] == 1
    # Derived index corruption is not hidden by a plausible numerical result.
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE evidence_episodes SET descriptor=?", (json.dumps({"changed": True}),)
        )
    with pytest.raises(ValueError, match="corrupted"):
        archive._library(future["at"] + 1)
    archive.close()
