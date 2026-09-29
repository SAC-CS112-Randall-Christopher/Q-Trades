import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import evaluate_research_roles as runner


def test_checkpoint_retries_windows_reader_conflict_without_partial_json(tmp_path, monkeypatch):
    destination = tmp_path / "receipt.json"
    destination.write_text('{"old":true}', encoding="utf-8")
    original = Path.replace
    attempts = []
    waits = []

    def sharing_conflict(path, target):
        attempts.append(path)
        assert json.loads(destination.read_text()) == {"old": True}
        if len(attempts) < 3:
            raise PermissionError("Windows reader holds destination")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", sharing_conflict)
    monkeypatch.setattr(runner.time, "sleep", waits.append)
    runner.save({"new": True}, destination)
    assert json.loads(destination.read_text()) == {"new": True}
    assert len(attempts) == 3
    assert 0 < sum(waits) < 3
    assert not destination.with_suffix(".tmp").exists()


def test_permanent_checkpoint_failure_preserves_both_receipts(tmp_path, monkeypatch):
    destination = tmp_path / "receipt.json"
    destination.write_text('{"old":true}', encoding="utf-8")
    attempts = []

    def denied(path, target):
        attempts.append(path)
        raise PermissionError("Still locked")

    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        runner.save({"new": True}, destination)
    assert len(attempts) == 10
    assert json.loads(destination.read_text()) == {"old": True}
    assert json.loads(destination.with_suffix(".tmp").read_text()) == {"new": True}


def test_continuation_preserves_failed_prefix_and_refuses_changed_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    directory = tmp_path / "docs/evidence"
    directory.mkdir(parents=True)
    source = directory / "interrupted.json"
    report = {
        "models": {"test-only": {"digest": "synthetic"}},
        "seeds": [1],
        "thinking": False,
        "settings": {"num_thread": 2},
        "request_timeout_seconds": 120,
        "runner_sha256": "old-runner",
        "results": [],
    }
    row = {
        "model": "test-only",
        "case": "case-1",
        "role": "researcher",
        "seed": 1,
        "settings": {"seed": 1, "num_thread": 2},
        "request_timeout_seconds": 120,
        "complete": True,
        "passed": False,
        "critical": [],
        "response": "failed-original",
    }
    previous = copy.deepcopy(report)
    previous["results"] = [row]
    source.write_text(json.dumps(previous), encoding="utf-8")
    before = source.read_bytes()
    cases = [{"id": "case-1", "role": "researcher"}, {"id": "case-2", "role": "researcher"}]
    runner.resume_prefix(source, report, cases)
    assert report["results"] == [row]
    assert report["resumed_from"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before
    changed = copy.deepcopy(report)
    changed["settings"]["num_thread"] = 8
    with pytest.raises(ValueError, match="frozen evaluation profile"):
        runner.resume_prefix(source, changed, cases)
    previous["results"] = [row, row]
    source.write_text(json.dumps(previous), encoding="utf-8")
    with pytest.raises(ValueError, match="recorded prefix"):
        runner.resume_prefix(source, report, cases)
