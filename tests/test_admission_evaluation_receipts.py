"""Retained-window coverage cannot manufacture an uninterrupted calm trace."""

import pytest

from scripts.evaluate_admission_recovery import load_receipt, summarize_window


def window(durations):
    return [{"at": 1000 + i * 0.5, "elapsed_ms": value} for i, value in enumerate(durations)]


def test_target_miss_below500_does_not_prove_recovery_from_wall_clock_snapshot():
    result = summarize_window(window([50] * 7 + [102.131] + [50] * 12))
    assert result["samples"] == 20
    assert result["target_exceedances_over100"] == 1
    assert result["blocking_samples_at_or_above500"] == 0
    assert result["sub500_suffix_samples"] == 20
    assert not result["candidate_admission_replayed"]
    assert result["candidate_recovery_evidence"].startswith("unknown_monotonic_clock")


def test_even_twenty_fast_wall_clock_samples_cannot_prove_monotonic_recovery():
    result = summarize_window(window([50] * 20))
    assert result["sub500_suffix_samples"] == 20
    assert result["candidate_recovery_evidence"].startswith("unknown_monotonic_clock")
    assert not result["candidate_admission_replayed"]


def test_retained_500_boundary_is_blocking_and_cannot_prove_recovery():
    result = summarize_window(window([50] * 7 + [500] + [150] * 12))
    assert result["target_exceedances_over100"] == 13
    assert result["blocking_samples_at_or_above500"] == 1
    assert result["sub500_suffix_samples"] == 12
    assert result["candidate_recovery_evidence"].startswith("insufficient_sub500_suffix")
    assert not result["candidate_admission_replayed"]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        window([50] * 21),
        window([float("nan")]),
        window([-1]),
        window([True]),
        [{"at": 1000, "elapsed_ms": 50}] * 2,
    ],
)
def test_incomplete_or_malformed_receipts_fail_without_an_admission_result(rows):
    with pytest.raises(ValueError):
        summarize_window(rows)


def test_retained_read_is_bounded_before_json_decoding(tmp_path):
    path = tmp_path / "oversized-receipt.json"
    path.write_bytes(b" " * (2 * 1024**2 + 1))
    with pytest.raises(ValueError, match="bounded read budget"):
        load_receipt(path)
