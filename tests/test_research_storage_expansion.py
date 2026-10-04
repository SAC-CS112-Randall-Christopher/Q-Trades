import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_paper_store import pg_store as pg_store
from test_research_storage import packet

from trading.research_evidence import canonical, digest
from trading.research_storage import GB, ResearchStorage, StoragePlan, load_plan, save_plan, volume
from trading.research_storage_expansion import expand_temporary_storage


@pytest.fixture(autouse=True)
def synthetic_capacity(monkeypatch):
    # Finite metadata tests do not allocate 400 GB or qualify volume throughput.
    monkeypatch.setattr(
        "trading.research_storage_expansion.volume",
        lambda path: {**volume(path), "free_bytes": 10**12},
    )


def original(tmp_path):
    directory = tmp_path / "data"
    root = tmp_path / "Q-Trades-Data-qa-expansion"
    plan = StoragePlan(root=str(root), volume_identity=volume(root)["identity"])
    save_plan(directory, plan)
    store = ResearchStorage(plan)
    value = packet(1_800_000_000)
    reference = store.append([value], value["at"])[0]
    store.close()
    return directory, plan, reference, value


def contents(directory, plan):
    return (
        (directory / "research-storage.json").read_bytes(),
        (Path(plan.root) / "owned.json").read_bytes(),
    )


def test_temporary_ceiling_is_400gb_without_expanding_defaults_or_retained_tier(tmp_path):
    plan = StoragePlan(root=str(tmp_path / "Q-Trades-Data"), volume_identity="fixture-volume")
    assert plan.temporary_bytes == plan.research_bytes == 100 * GB
    assert StoragePlan.model_validate({**plan.model_dump(), "temporary_bytes": 400 * GB})
    with pytest.raises(ValidationError):
        StoragePlan.model_validate({**plan.model_dump(), "temporary_bytes": 400 * GB + 1})
    with pytest.raises(ValidationError):
        StoragePlan.model_validate({**plan.model_dump(), "research_bytes": 100 * GB + 1})


def test_preview_preserves_original_metadata_and_evidence_and_uses_no_database(tmp_path):
    directory, plan, reference, value = original(tmp_path)
    before = contents(directory, plan)
    report = expand_temporary_storage(directory, "never connected", target_gb=400, expected_gb=100)
    assert report["mode"] == "preview" and report["additional_bytes"] == 300 * GB
    assert report["target_temporary_bytes"] == 400 * GB and report["research_bytes"] == 100 * GB
    assert contents(directory, plan) == before
    assert not (directory / "temporary-storage-100-to-400gb.json").exists()
    store = ResearchStorage(plan)
    assert store.reopen(reference) == value
    store.close()


@pytest.mark.parametrize("failure", ["marker", "volume", "space", "redirect"])
def test_invalid_identity_low_free_space_and_redirected_metadata_refuse(
    tmp_path, monkeypatch, failure
):
    directory, plan, _, _ = original(tmp_path)
    if failure == "marker":
        (Path(plan.root) / "owned.json").write_text(
            canonical({"plan_sha256": "wrong", "version": plan.version})
        )
    elif failure == "redirect":
        marker = Path(plan.root) / "owned.json"
        other = tmp_path / "redirect-target.json"
        other.write_bytes(marker.read_bytes())
        marker.unlink()
        try:
            marker.symlink_to(other)
        except OSError:
            pytest.skip("Creating Windows symlinks requires developer mode")
    else:
        monkeypatch.setattr(
            "trading.research_storage_expansion.volume",
            lambda path: {
                "identity": "wrong" if failure == "volume" else plan.volume_identity,
                "free_bytes": 0 if failure == "space" else 10**12,
            },
        )
    before = contents(directory, plan)
    with pytest.raises((ValueError, OSError)):
        expand_temporary_storage(directory, "unused", target_gb=400, expected_gb=100)
    assert contents(directory, plan) == before
    assert not (directory / "temporary-storage-100-to-400gb.json").exists()


def test_active_writer_refuses_apply_without_metadata_changes(tmp_path, pg_store):
    _, dsn = pg_store
    directory, plan, _, _ = original(tmp_path)
    before = contents(directory, plan)
    with pytest.raises(RuntimeError, match="writer is active"):
        expand_temporary_storage(directory, dsn, target_gb=400, expected_gb=100, apply=True)
    assert contents(directory, plan) == before
    assert not (directory / "temporary-storage-100-to-400gb.json").exists()


def test_stopped_writer_expands_only_quota_and_reopens_exact_evidence(tmp_path, pg_store):
    financial, dsn = pg_store
    state, events = financial.read(), financial.export(0, 1000)
    financial.close()
    directory, plan, reference, value = original(tmp_path)
    before = contents(directory, plan)
    report = expand_temporary_storage(directory, dsn, target_gb=400, expected_gb=100, apply=True)
    after = load_plan(directory)
    assert after and after.temporary_bytes == 400 * GB and after.research_bytes == 100 * GB
    assert after.model_dump(exclude={"temporary_bytes"}) == plan.model_dump(
        exclude={"temporary_bytes"}
    )
    receipt = json.loads((directory / "temporary-storage-100-to-400gb.json").read_text())
    assert receipt["before_plan"].encode() == before[0]
    assert receipt["before_marker"].encode() == before[1]
    assert report["mode"] == "applied" and report["already_applied"] is False
    assert report["financial_rows_modified"] is False and report["evidence_files_modified"] is False
    store = ResearchStorage(after)
    status = store.snapshot()
    assert status["plan"]["temporary_bytes"] == 400 * GB
    assert store.reopen(reference) == value
    store.close()
    (directory / "research-storage-status.json").write_text(json.dumps(status))
    from fastapi.testclient import TestClient

    from trading.api import create_app
    from trading.config import Settings

    with TestClient(
        create_app(Settings(), directory / "monitor.sqlite3", background=False)
    ) as client:
        reopened = client.get("/api/research/storage")
        assert reopened.status_code == 200
        assert reopened.json()["plan"]["temporary_bytes"] == 400 * GB
        assert reopened.json()["plan"]["research_bytes"] == 100 * GB
    applied = contents(directory, after)
    repeat = expand_temporary_storage(directory, dsn, target_gb=400, expected_gb=100, apply=True)
    assert repeat["already_applied"] and contents(directory, after) == applied
    from trading.paper_store import PaperStore

    reader = PaperStore(dsn)
    assert reader.read() == state and reader.export(0, 1000) == events
    reader.close()


def test_interrupted_metadata_transition_fails_closed_and_explicit_retry_completes(
    tmp_path, pg_store, monkeypatch
):
    financial, dsn = pg_store
    financial.close()
    directory, plan, reference, value = original(tmp_path)
    import trading.research_storage_expansion as expansion

    real_replace = expansion.os.replace

    def interrupt(source, target):
        if target == directory / "research-storage.json":
            raise OSError("Synthetic disconnect after successor marker commit")
        return real_replace(source, target)

    monkeypatch.setattr(expansion.os, "replace", interrupt)
    with pytest.raises(OSError, match="disconnect"):
        expand_temporary_storage(directory, dsn, target_gb=400, expected_gb=100, apply=True)
    assert load_plan(directory) == plan
    with pytest.raises(ValueError, match="marker differs"):
        ResearchStorage(plan)
    monkeypatch.setattr(expansion.os, "replace", real_replace)
    expand_temporary_storage(directory, dsn, target_gb=400, expected_gb=100, apply=True)
    after = load_plan(directory)
    assert after
    store = ResearchStorage(after)
    assert store.reopen(reference) == value
    store.close()


def test_frozen_policy_cannot_be_replaced_through_ordinary_plan_save(tmp_path):
    directory, plan, _, _ = original(tmp_path)
    after = StoragePlan.model_validate({**plan.model_dump(), "temporary_bytes": 400 * GB})
    with pytest.raises(ValueError, match="frozen"):
        save_plan(directory, after)


def test_successor_does_not_allow_other_targets_or_a_fabricated_marker(tmp_path):
    directory, plan, _, _ = original(tmp_path)
    before = contents(directory, plan)
    with pytest.raises(ValueError, match="Only the reviewed"):
        expand_temporary_storage(directory, "unused", target_gb=500, expected_gb=100)
    fabricated = {
        "version": "temporary-storage-successor-v1",
        "before_plan": before[0].decode(),
        "before_marker": before[1].decode(),
        "after_plan": plan.model_dump_json(),
        "after_marker": canonical(
            {"plan_sha256": digest(plan.model_dump()), "version": plan.version}
        ),
    }
    (directory / "temporary-storage-100-to-400gb.json").write_text(canonical(fabricated))
    with pytest.raises(ValueError, match="quota-only"):
        expand_temporary_storage(directory, "unused", target_gb=400, expected_gb=100)
    assert contents(directory, plan) == before
