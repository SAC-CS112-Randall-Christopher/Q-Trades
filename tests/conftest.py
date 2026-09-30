import copy

import pytest


@pytest.fixture
def book():
    return {
        "lastUpdateId": 17,
        "bids": [["99.90", "2.0"], ["99.80", "3.0"], ["98.00", "10"]],
        "asks": [["100.10", "2.0"], ["100.20", "3.0"], ["102.00", "10"]],
    }


@pytest.fixture
def metadata():
    return {
        "symbols": [
            {
                "symbol": "BTCUSD",
                "baseAsset": "BTC",
                "quoteAsset": "USD",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
                "filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "1.00"}],
            }
        ]
    }


@pytest.fixture
def clone():
    return copy.deepcopy


@pytest.fixture
def decision_packet(tmp_path):
    import time
    from collections import deque
    from decimal import Decimal as D

    from test_paper_engine import frame

    from trading.evidence_runtime import EvidenceRecorder
    from trading.paper_engine import initial_state
    from trading.paper_strategy import VARIANTS, Bar, features

    bars = [
        Bar(
            i * 60000,
            D(100) + D(i) / 100,
            D(100) + D(i) / 100 + D(".005"),
            D(100) + D(i) / 100 - D(".01"),
            D(100) + D(i) / 100,
            D(10),
            i * 60000 + 59999,
        )
        for i in range(400)
    ]
    at = (bars[-1].close_ms + 1000) / 1000
    frames = {
        "BTCUSD": {
            **frame(at),
            "source": "synthetic-fixture",
            "received_mono": time.monotonic() - 0.01,
        }
    }
    study = {"BTCUSD": {v: features(bars, at, v) for v in VARIANTS}}
    recorder = EvidenceRecorder(tmp_path / "evidence.sqlite")
    packet = recorder.prepare(
        at,
        frames,
        study,
        {"BTCUSD": bars},
        {"BTCUSD": at},
        0,
        {},
        initial_state(at),
        [],
        {"BTCUSD": deque()},
        {},
    )
    return recorder, packet, frames, study
