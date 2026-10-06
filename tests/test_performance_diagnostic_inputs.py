"""Runtime producers preserve input eligibility while ignoring strategy signals."""

from types import SimpleNamespace

import pytest
from test_paper_engine import START, frame
from test_paper_runtime import instrument

from trading.paper_diagnostics import create_diagnostic, start_diagnostic
from trading.paper_engine import PaperEngine, initial_state
from trading.tiered_runtime import TieredPaperRuntime


@pytest.mark.parametrize(
    "condition,valid", [("current", True), ("stale", False), ("error", False), ("bootstrap", False)]
)
def test_current_frames_derives_protected_diagnostic_risk_input(condition, valid, monkeypatch):
    runtime = TieredPaperRuntime.__new__(TieredPaperRuntime)
    runtime.state = initial_state(START)
    observed = frame(START)
    observed.update(source="synthetic-performance-fixture", received_mono=100.0)
    runtime.stream = SimpleNamespace(
        plan={"BTCUSD": 100}, fresh_books=lambda **_: {"BTCUSD": observed}
    )
    runtime._fallback, runtime._rest_requests, runtime._fallback_at = {}, {}, {}
    runtime._previous_books, runtime.feed_errors = {}, {}
    runtime._rest_retry_at, runtime.metadata_at = 0.0, START
    runtime.instruments = {"BTCUSD": instrument("BTC")}
    runtime.ready_at = START + 1 if condition == "bootstrap" else START - 120
    runtime._candle_errors = {"BTCUSD": "Retained candle error"} if condition == "error" else {}
    risk_input = {
        "eligible": False,
        "reason": "No breakout signal",
        "atr": "1",
        "closed_bars": 400,
        "bar_open_ms": (START - 60) * 1000,
    }
    if condition == "stale":
        risk_input["bar_open_ms"] = (START - 240) * 1000
    runtime.study = {"BTCUSD": {"breakout-v1": risk_input}}
    monkeypatch.setattr("trading.tiered_runtime.time.time", lambda: START)
    monkeypatch.setattr("trading.tiered_runtime.time.monotonic", lambda: 100.0)
    frames, studies = runtime.current_frames()
    assert studies["BTCUSD"]["breakout-v1"]["eligible"] is False
    assert frames["BTCUSD"]["diagnostic_risk_input_valid"] is valid
    engine = PaperEngine(runtime.state, START)
    create_diagnostic(engine, "diagnostic-input-create-001")
    start_diagnostic(engine, "diagnostic-input-start-001", 1)
    engine.tick(frames, studies)
    pending = engine.state["accounts"]["performance-diagnostic"]["pending"]
    assert bool(pending) is valid
