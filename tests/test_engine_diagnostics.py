from trading.engine_diagnostics import EngineWorkDiagnostics


def sample(elapsed, **stages):
    return {"at": 1000, "elapsed_ms": elapsed, "stages_ms": stages}


def test_severe_trigger_keeps_operation_evidence_and_original_sample():
    diagnostics = EngineWorkDiagnostics()
    slow = sample(1100, prepare=1, transaction=1080, reconcile=19)
    receipt = diagnostics.record(slow, 100, repeated=False, severe=True)
    assert receipt["sample"] == slow
    assert receipt["slow_window"] == [slow]
    assert receipt["severe_stall"] and not receipt["repeated_slow_work"]
    diagnostics.record(sample(15), 101, repeated=False, severe=False)
    assert receipt["sample"] == slow
    assert diagnostics.snapshot(110, 400)["cooldown_remaining_seconds"] == 290
    assert diagnostics.snapshot(401, 400)["cooldown_remaining_seconds"] == 0


def test_repeated_trigger_retains_the_slow_samples_even_when_current_work_is_fast():
    diagnostics = EngineWorkDiagnostics()
    for i in range(20):
        diagnostics.record(sample(130 if i >= 16 else 10), i, repeated=False, severe=False)
    receipt = diagnostics.record(sample(10), 20, repeated=True, severe=False)
    assert len(diagnostics.samples) == 20
    assert len(receipt["slow_window"]) == 4
    assert receipt["sample"]["elapsed_ms"] == 10
    assert receipt["repeated_slow_work"]


def test_diagnostics_coalesce_without_losing_peak_and_keep_memory_bounded():
    diagnostics = EngineWorkDiagnostics()
    first = diagnostics.record(sample(1100), 0, repeated=False, severe=True)
    for i in range(1, 60):
        duration = 2500 if i == 4 else 150
        assert diagnostics.record(
            sample(duration, transaction=duration), i, repeated=True, severe=duration >= 1000
        ) is None
    pending = diagnostics.snapshot(59, 359)
    assert pending["unreported_peak"]["elapsed_ms"] == 2500
    second = diagnostics.record(sample(150), 60, repeated=True, severe=False)
    assert second["triggers_since_receipt"] == 60
    assert second["peak_since_receipt"]["elapsed_ms"] == 2500
    assert first["trigger_number"] == 1
    assert diagnostics.queued_receipts == 2 and len(diagnostics.samples) == 20
    assert diagnostics.snapshot(61, 360)["unreported_triggers"] == 0
