import asyncio
import copy
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trading.api import create_app
from trading.config import Settings
from trading.experiment_lab import ExperimentLab
from trading.experiment_registry import (
    PREFLIGHT_END,
    ExperimentPlan,
    ExperimentRegistry,
    fingerprint,
)
from trading.experiment_worker import code_fingerprint, evaluate
from trading.research_experiment import examples, run_experiment

ROOT = Path(__file__).resolve().parents[1]


def plan(request="experiment-one", **changes):
    return ExperimentPlan.model_validate(
        {
            "request_id": request,
            "name": "Registered hypothesis",
            "mechanism": "Momentum may persist beyond the declared cost hurdle.",
            "falsification": "Reject if no after-cost forecasts remain positive.",
            "as_of": PREFLIGHT_END + 100000.0,
            "test_start": PREFLIGHT_END + 10000.0,
            "test_end": PREFLIGHT_END + 90000.0,
            **changes,
        }
    )


def retained():
    return json.loads(
        (ROOT / "docs/evidence/numeric-preflight-20260928T113855Z.quotes.json").read_text()
    )


def shifted_inputs():
    data = retained()
    for row in data["rows"]:
        row["at"] += 60000
        row["body"]["last_observed_at"] += 60000
        row["body"]["minute"] += 1000
    data["manifest"] = {
        "rows": len(data["rows"]),
        "older_rows_omitted": False,
        "dataset_sha256": fingerprint(data["rows"]),
    }
    return data


def test_retained_preflight_hashes_exact_reproduction_and_original_rejection():
    evidence = ROOT / "docs/evidence"
    receipt = json.loads((evidence / "numeric-preflight-20260928T113855Z.json").read_text())
    for field in ("plan", "snapshot"):
        raw = (evidence / Path(receipt[field]).name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == receipt[field + "_sha256"]
    actual = run_experiment(retained()["rows"], "momentum_5", 5)
    assert actual == receipt["result"]
    assert actual["test_end"] == PREFLIGHT_END
    assert not actual["eligible_for_forward_review"]
    assert actual["metrics"]["positive_predictions"] == 0
    assert (
        run_experiment(retained()["rows"], "spread_bps", 5, PREFLIGHT_END)["status"]
        == "insufficient_data"
    )


@pytest.mark.parametrize("changed", [{}, {"feature": "spread_bps"}, {"feature": "momentum_1"}])
def test_omitted_caller_boundary_or_feature_change_cannot_reuse_preflight(tmp_path, changed):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    try:
        with pytest.raises(ValueError, match="consumed"):
            registry.reserve(
                plan(test_start=PREFLIGHT_END - 20000, test_end=PREFLIGHT_END, **changed), "a"
            )
        assert registry.snapshot()["counts"] == {}
    finally:
        registry.close()


def test_atomic_concurrent_window_reservation_and_exact_retry(tmp_path):
    path = tmp_path / "registry.sqlite"
    first, second = ExperimentRegistry(path), ExperimentRegistry(path)
    outcomes = []
    barrier = threading.Barrier(2)

    def reserve(registry, request):
        barrier.wait()
        try:
            outcomes.append(registry.reserve(plan(request), "frozen-code")["request_id"])
        except ValueError:
            outcomes.append("overlap-refused")

    threads = [
        threading.Thread(target=reserve, args=(r, f"experiment-{i}"))
        for i, r in enumerate((first, second))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("overlap-refused") == 1
    accepted = next(x for x in outcomes if x != "overlap-refused")
    assert first.reserve(plan(accepted), "frozen-code")["retry"]
    with pytest.raises(ValueError, match="frozen"):
        first.reserve(plan(accepted, feature="spread_bps"), "frozen-code")
    first.close()
    second.close()


def test_cancel_failure_restart_and_fencing_preserve_consumption(tmp_path):
    path = tmp_path / "registry.sqlite"
    registry = ExperimentRegistry(path)
    registry.reserve(plan(), code_fingerprint())
    registry.inputs("experiment-one", shifted_inputs())
    job = registry.claim()
    assert job and registry.claim() is None
    registry.cancel("experiment-one")
    assert not registry.finish(job["request_id"], job["lease"], {"invented": True}, None)
    registry.close()
    registry = ExperimentRegistry(path)
    assert registry.get("experiment-one")["status"] == "cancelled"
    with pytest.raises(ValueError, match="consumed"):
        registry.reserve(plan("different-hash", feature="volatility_5"), "other-code")
    for table in ("experiments", "evidence_windows", "experiment_events"):
        with pytest.raises(sqlite3.IntegrityError):
            registry.db.execute(f"DELETE FROM {table}")
    registry.close()


def test_expired_owner_cannot_finish_or_launch_parallel_workers(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    registry.reserve(plan(), code_fingerprint())
    registry.inputs("experiment-one", shifted_inputs())
    job = registry.claim(time.time() - 60)
    new = registry.claim()
    assert job and new and job["lease"] != new["lease"]
    assert not registry.finish(job["request_id"], job["lease"], {}, None)
    assert registry.finish(new["request_id"], new["lease"], {"decision": "reject"}, None)
    assert len(registry.get("experiment-one")["events"]) == 6
    registry.close()


def test_snapshot_hash_and_availability_are_checked_before_fitting(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    registry.reserve(plan(), code_fingerprint())
    registry.inputs("experiment-one", shifted_inputs())
    job = registry.claim()
    assert job
    payload = registry.get("experiment-one", inputs=True)
    assert payload
    job = dict(payload, plan=json.dumps(payload["plan"]), snapshot=json.dumps(payload["snapshot"]))
    changed = dict(job, snapshot=json.dumps({"rows": [], "manifest": {}}))
    with pytest.raises(ValueError, match="fingerprint"):
        evaluate(changed)
    changed = json.loads(job["snapshot"])
    changed["rows"][0]["at"] = plan().as_of + 1
    with pytest.raises(ValueError, match="availability"):
        evaluate(dict(job, snapshot=json.dumps(changed), snapshot_sha256=fingerprint(changed)))
    registry.close()


def test_feature_availability_revisions_gaps_and_label_purge():
    data = retained()["rows"]
    changed = copy.deepcopy(data)
    changed[10]["body"]["last_observed_at"] = changed[10]["at"] + 300
    built = examples(changed, "momentum_5", 5)
    assert built["excluded"]["late_or_future_record"] >= 1
    revision = copy.deepcopy(data[50])
    revision["id"] += 100000
    revision["at"] += 300
    revision["body"]["last_depth"]["bid"] = "100"
    revision["body"]["last_depth"]["ask"] = "101"
    revised = examples([*data, revision], "momentum_5", 5)
    assert all(s["feature_event"] != revision["id"] for s in revised["samples"])
    report = run_experiment(data, "momentum_5", 5)
    assert report["train_end"] < report["split_at"] - 300


def test_child_worker_retains_result_without_financial_connection(tmp_path):
    lab = ExperimentLab(tmp_path / "registry.sqlite", None, lambda: True)
    data = shifted_inputs()
    original = json.loads(
        (ROOT / "docs/evidence/numeric-preflight-20260928T113855Z.json").read_text()
    )
    frozen = plan(
        test_start=original["result"]["split_at"] + 60000,
        test_end=PREFLIGHT_END + 60000,
        evidence_kind="synthetic_qa",
    )
    lab.registry.reserve(frozen, code_fingerprint())
    lab.registry.inputs(frozen.request_id, data)
    assert asyncio.run(lab.run_once())
    result = lab.registry.get(frozen.request_id)
    assert result["status"] == "completed"
    assert result["result"]["decision"] == "reject"
    assert result["result"]["metrics"]["positive_predictions"] == 0
    assert float(result["result"]["metrics"]["model_mse_bps_squared"]) > 0
    assert result["result"]["test_end"] <= frozen.test_end
    assert not result["result"]["independent_validation"]
    assert lab.child is None
    lab.registry.close()


def test_api_auth_protected_boundary_retry_failure_and_export(tmp_path):
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        assert client.get("/api/lab").json()["preflight_boundary"] == PREFLIGHT_END
        frozen = plan().model_dump()
        assert client.post("/api/lab/experiments", json=frozen).status_code == 403
        assert (
            client.post(
                "/api/lab/experiments",
                json=frozen,
                headers={"X-Local-Operator": "1", "Origin": "http://foreign.invalid"},
            ).status_code
            == 403
        )
        response = client.post(
            "/api/lab/experiments", json=frozen, headers={"X-Local-Operator": "1"}
        )
        assert response.status_code == 200 and response.json()["status"] == "failed"
        assert client.post(
            "/api/lab/experiments", json=frozen, headers={"X-Local-Operator": "1"}
        ).json()["retry"]
        receipt = client.get("/api/lab/experiments/experiment-one").json()
        assert "snapshot" not in receipt and receipt["status"] == "failed"
        assert receipt["plan"]["mechanism"] == frozen["mechanism"]
        protected = plan(
            "old-test-period", test_start=PREFLIGHT_END - 1000, test_end=PREFLIGHT_END
        ).model_dump()
        assert (
            client.post(
                "/api/lab/experiments", json=protected, headers={"X-Local-Operator": "1"}
            ).status_code
            == 409
        )
