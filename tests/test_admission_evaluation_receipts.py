"""Retained-window coverage cannot manufacture an uninterrupted calm trace."""

import pytest

from scripts.evaluate_admission_recovery import load_receipt, summarize_window


def window(durations):
    return [{"at": 1000 + i * 0.5, "elapsed_ms": value} for i, value in enumerate(durations)]


def test_slow_work_interrupts_clean_suffix_without_fabricating_prior_recovery():
    result = summarize_window(window([50] * 7 + [102.131] + [50] * 12))
    assert result["samples"] == 20
    assert result["slow_samples"] == 1
    assert result["clean_suffix_samples"] == 12
    assert not result["candidate_admission_replayed"]
    assert result["candidate_recovery_evidence"].startswith("insufficient_clean_suffix")


def test_even_twenty_fast_wall_clock_samples_cannot_prove_monotonic_recovery():
    result = summarize_window(window([50] * 20))
    assert result["clean_suffix_samples"] == 20
    assert result["candidate_recovery_evidence"].startswith("unknown_monotonic_clock")
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
