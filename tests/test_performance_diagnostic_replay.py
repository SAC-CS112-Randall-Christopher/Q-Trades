"""Mixed performance archives retain exact financial state and guard observations."""

import asyncio
import copy
import time

import pytest
from test_paper_engine import frame

from trading.evidence_runtime import plain
from trading.execution_replay import run_replay, source_hashes
from trading.paper_diagnostics import create_diagnostic, start_diagnostic
from trading.paper_engine import PaperEngine
from trading.research_evidence import digest, evidence_page, evidence_record


def test_mixed_sampled_guard_replays_exactly_but_excludes_diagnostic_research(decision_packet):
    recorder, template, _, studies = decision_packet
    state = copy.deepcopy(template["state_before"])
    initial = PaperEngine(state, template["at"])
    create_diagnostic(initial, "diagnostic-replay-create-001")
    start_diagnostic(initial, "diagnostic-replay-start-001", 1)
    for sequence, allowed in enumerate((True, False, True, True, False, True), 1):
        now = template["at"] + sequence
        frames = {
            "BTCUSD": {
                **frame(now, sequence=sequence),
                "source": "synthetic-performance-fixture",
                "diagnostic_risk_input_valid": True,
            }
        }
        packet = copy.deepcopy(template)
        packet.update(
            at=now,
            diagnostic_allowed=allowed,
            state_before=plain(state),
            frames=plain(
                {s: {k: v for k, v in f.items() if k != "book"} for s, f in frames.items()}
            ),
        )
        engine = PaperEngine(state, now)
        engine.tick(frames, copy.deepcopy(studies), diagnostic_allowed=allowed)
        recorder.complete(packet, engine.events, state, [], {}, time.perf_counter())
    asyncio.run(recorder.flush())
    ids = sorted(row["id"] for row in evidence_page(recorder.path, limit=50)["records"])
    records = [evidence_record(recorder.path, row_id) for row_id in ids]
    try:
        assert len(records) == 6
        result = run_replay(records, source_hashes())
        assert result["status"] == "reconciled", result
        assert all(row["state_matches"] and row["events_match"] for row in result["baseline"])
        assert all(
            "performance-diagnostic" not in {a["account"] for a in scenario["accounts"]}
            for scenario in result["scenarios"]
        )
        assert all(
            e["account"] != "performance-diagnostic"
            for scenario in result["scenarios"]
            for e in scenario["fills"]
        )
        broken = copy.deepcopy(records)
        broken[0]["payload"].pop("diagnostic_allowed")
        broken[0]["sha256"] = digest(broken[0]["payload"])
        with pytest.raises(ValueError, match="Diagnostic admission observation was not recorded"):
            run_replay(broken, source_hashes())
    finally:
        recorder._archive.close()
