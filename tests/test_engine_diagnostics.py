from trading.engine_diagnostics import (
    PRESSURE_POLICY_VERSION,
    EngineWorkDiagnostics,
    EngineWorkPressurePolicy,
)


def pressure_at(now, severe_at):
    policy = EngineWorkPressurePolicy()
    policy.observe(1000, severe_at)
    return policy.evaluate(now)


def test_current_window_distinguishes_fresh_work_from_an_expired_trigger():
    diagnostics = EngineWorkDiagnostics()
    stalled = {"at": 1000, "elapsed_ms": 1200, "stages_ms": {"transaction": 900}}
    diagnostics.record(stalled, 1000, repeated=False, severe=True)
    for offset in range(25):
        diagnostics.record(
            {"at": 1400 + offset, "elapsed_ms": 20, "stages_ms": {"compact_capture": 2}},
            1400 + offset,
            repeated=False,
            severe=False,
        )
    snapshot = diagnostics.snapshot(pressure_at(1500, 1000))
    assert snapshot["cooldown_remaining_seconds"] == 0
    assert all(snapshot["last_trigger"]["sample"][key] == value for key, value in stalled.items())
    assert snapshot["latest_work"]["at"] == 1424
    assert len(snapshot["current_window"]) == 20
    assert all(row["elapsed_ms"] == 20 for row in snapshot["current_window"])


def sample(elapsed, **stages):
    return {"at": 1000, "elapsed_ms": elapsed, "stages_ms": stages}


def test_severe_trigger_keeps_operation_evidence_and_original_sample():
    diagnostics = EngineWorkDiagnostics()
    slow = sample(1100, prepare=1, transaction=1080, reconcile=19)
    receipt = diagnostics.record(slow, 100, repeated=False, severe=True)
    assert all(receipt["sample"][key] == value for key, value in slow.items())
    assert receipt["slow_window"] == [receipt["sample"]]
    assert receipt["blocking_window"] == [receipt["sample"]]
    assert receipt["severe_stall"] and not receipt["repeated_slow_work"]
    diagnostics.record(sample(15), 101, repeated=False, severe=False)
    assert all(receipt["sample"][key] == value for key, value in slow.items())
    assert diagnostics.snapshot(pressure_at(110, 100))["cooldown_remaining_seconds"] == 290
    assert diagnostics.snapshot(pressure_at(401, 100))["cooldown_remaining_seconds"] == 0


def test_repeated_trigger_retains_the_slow_samples_even_when_current_work_is_fast():
    diagnostics = EngineWorkDiagnostics()
    for i in range(20):
        diagnostics.record(sample(130 if i >= 16 else 10), i, repeated=False, severe=False)
    receipt = diagnostics.record(sample(10), 20, repeated=True, severe=False)
    assert len(diagnostics.samples) == 20
    assert len(receipt["slow_window"]) == 4
    assert receipt["blocking_window"] == []
    assert receipt["sample"]["elapsed_ms"] == 10
    assert receipt["repeated_slow_work"]


def test_diagnostics_coalesce_without_losing_peak_and_keep_memory_bounded():
    diagnostics = EngineWorkDiagnostics()
    first = diagnostics.record(sample(1100), 0, repeated=False, severe=True)
    for i in range(1, 60):
        duration = 2500 if i == 4 else 150
        assert (
            diagnostics.record(
                sample(duration, transaction=duration), i, repeated=True, severe=duration >= 1000
            )
            is None
        )
    pending = diagnostics.snapshot(pressure_at(59, 59))
    assert pending["unreported_peak"]["elapsed_ms"] == 2500
    second = diagnostics.record(sample(150), 60, repeated=True, severe=False)
    assert second["triggers_since_receipt"] == 60
    assert second["peak_since_receipt"]["elapsed_ms"] == 2500
    assert first["trigger_number"] == 1
    assert diagnostics.queued_receipts == 2 and len(diagnostics.samples) == 20
    assert diagnostics.snapshot(pressure_at(61, 60))["unreported_triggers"] == 0


def test_observation_identity_is_bounded_authoritative_and_versioned():
    diagnostics = EngineWorkDiagnostics("existing-runtime-epoch")
    original = {"at": 1000, "elapsed_ms": 500, "work_number": -1, "observed_mono": -1}
    first = diagnostics.record(original, 10, repeated=True, severe=False)
    for offset in range(25):
        diagnostics.record(sample(150), 11 + offset, repeated=False, severe=False)
    snapshot = diagnostics.snapshot(pressure_at(36, 10))
    assert original["work_number"] == -1  # The producer's input was not overwritten.
    assert first["sample"]["work_number"] == 1
    assert first["sample"]["observed_mono"] == 10
    assert first["policy_version"] == PRESSURE_POLICY_VERSION
    assert first["blocking_window"][0]["elapsed_ms"] == 500
    assert first["severe_cooldown_seconds"] == 300
    assert "cooldown_seconds" not in first  # Moderate pressure has no fixed 300s deadline.
    assert snapshot["work_observations"] == 26
    assert snapshot["observation_epoch"] == "existing-runtime-epoch"
    assert [row["work_number"] for row in snapshot["current_window"]] == list(range(7, 27))
    assert all(row["observation_epoch"] == "existing-runtime-epoch"
               for row in snapshot["current_window"])
