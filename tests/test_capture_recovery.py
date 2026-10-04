"""Real rollback journals in disposable owned storage, never operating capture files."""

import asyncio
import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest
from test_research_storage import packet, plan_at

from trading.evidence_runtime import EvidenceRecorder
from trading.ownership import CollectorLock
from trading.research_storage import ResearchStorage, reopen_evidence, save_plan


def interrupt_segment(path):
    # Force dirty pages to disk while leaving the transaction uncommitted. Exiting
    # without close leaves SQLite's actual hot rollback journal, not a mock error.
    code = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute('PRAGMA cache_size=2')
db.execute('PRAGMA synchronous=FULL')
db.execute('BEGIN IMMEDIATE')
db.execute("UPDATE records SET body=? WHERE id=1", ('uncommitted' * 50000,))
db.execute("INSERT INTO records(sha,body) VALUES(?,?)", ('f' * 64, 'pending' * 50000))
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(path)], check=True, timeout=15)
    assert path.with_name(path.name + "-journal").exists()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        with pytest.raises(sqlite3.OperationalError) as failed:
            source.execute("SELECT * FROM records").fetchall()
        assert failed.value.sqlite_errorname == "SQLITE_READONLY_ROLLBACK"


def committed_segment(tmp_path):
    plan = plan_at(tmp_path)
    values = [packet(1_800_000_000 + i, sample="committed" * 1800) for i in range(2)]
    with closing(ResearchStorage(plan)) as owner:
        refs = owner.append(values, 1_800_000_010, defer_retention=True)
        path = owner._path(1)
        indexed = [
            tuple(row) for row in owner.db.execute("SELECT * FROM storage_records ORDER BY record")
        ]
    return plan, values, refs, path, indexed


def test_normal_owner_recovers_committed_evidence_and_resumes_twice(tmp_path):
    plan, values, refs, path, indexed = committed_segment(tmp_path)
    interrupt_segment(path)
    # A historical reader has no repair authority, and cannot clear the journal.
    with pytest.raises(sqlite3.OperationalError):
        reopen_evidence(plan, refs[0])
    assert path.with_name(path.name + "-journal").exists()
    with closing(ResearchStorage(plan)) as owner:
        assert [
            tuple(row) for row in owner.db.execute("SELECT * FROM storage_records ORDER BY record")
        ] == indexed
        for value, ref in zip(values, refs, strict=True):
            assert owner.reopen(ref) == value
        assert owner.recovery == {"segments_checked": 1, "rollbacks": 1}
        new = packet(1_800_000_012)
        new_ref = owner.append([new], new["at"], defer_retention=True)[0]
    with closing(ResearchStorage(plan)) as owner:
        assert owner.db.execute("SELECT count(*) FROM storage_records").fetchone()[0] == 3
        assert owner.reopen(new_ref) == new
        assert owner.append([new], new["at"], defer_retention=True) == [new_ref]
        assert owner.db.execute("SELECT count(*) FROM storage_records").fetchone()[0] == 3


def forget_index(plan):
    with sqlite3.connect(os.path.join(plan.root, "research", "storage-index.sqlite")) as db:
        db.execute("DELETE FROM storage_records")
        db.execute("DELETE FROM storage_segments")


def test_hot_owned_orphan_and_process_interruption_during_reconciliation(tmp_path):
    plan, values, refs, path, indexed = committed_segment(tmp_path)
    forget_index(plan)  # Simulate a segment commit preceding a lost index commit.
    interrupt_segment(path)
    code = """
import os, sys
from trading import research_storage as storage
original = storage.digest
def interrupt(value):
    if isinstance(value, dict) and value.get('at') == 1800000001:
        os._exit(34)
    return original(value)
storage.digest = interrupt
storage.ResearchStorage(storage.StoragePlan.model_validate_json(sys.argv[1]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, plan.model_dump_json()],
        timeout=15,
        env={**os.environ, "PYTHONPATH": os.path.abspath("src")},
    )
    assert result.returncode == 34
    with closing(ResearchStorage(plan)) as owner:
        assert [
            tuple(row) for row in owner.db.execute("SELECT * FROM storage_records ORDER BY record")
        ] == indexed
        assert [owner.reopen(ref) for ref in refs] == values
    with closing(ResearchStorage(plan)) as owner:
        assert owner.db.execute("SELECT count(*) FROM storage_records").fetchone()[0] == 2


def test_competing_owner_and_sqlite_writer_preserve_files_and_allow_retry(tmp_path):
    plan, _, refs, path, _ = committed_segment(tmp_path)
    with closing(ResearchStorage(plan)) as first:
        with first._exclusive():
            with pytest.raises(OSError, match="busy"):
                ResearchStorage(plan)
        with closing(sqlite3.connect(path)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with pytest.raises(OSError, match="busy"):
                ResearchStorage(plan)
            writer.rollback()
    with closing(ResearchStorage(plan)) as owner:
        assert owner.reopen(refs[0])["at"] == 1_800_000_000


@pytest.mark.parametrize("change", ["plan", "segment", "missing", "corrupt", "foreign"])
def test_unverified_or_broken_recovery_is_explicit_and_never_creates_segment(tmp_path, change):
    plan, _, _, path, _ = committed_segment(tmp_path)
    if change == "plan":
        (path.parent.parent / "owned.json").write_text("{}")
        expected = "marker differs"
    elif change == "segment":
        path.with_suffix(".owner.json").write_text("{}")
        expected = "foreign"
    elif change == "missing":
        path.unlink()
        expected = "missing"
    elif change == "corrupt":
        path.write_bytes(b"corrupt sqlite")
        expected = "corrupt"
    else:
        forget_index(plan)
        path.with_suffix(".owner.json").unlink()
        interrupt_segment(path)
        expected = "foreign"
    before = path.read_bytes() if path.exists() else None
    journal = path.with_name(path.name + "-journal")
    saved_journal = journal.read_bytes() if journal.exists() else None
    with pytest.raises((OSError, ValueError), match=expected):
        ResearchStorage(plan)
    assert (path.read_bytes() if path.exists() else None) == before
    assert (journal.read_bytes() if journal.exists() else None) == saved_journal


def test_pre_intent_indexed_segment_can_recover_but_owner_reader_remains_restricted(tmp_path):
    plan, values, refs, path, _ = committed_segment(tmp_path)
    path.with_suffix(".owner.json").unlink()  # Existing indexed pre-fix capture.
    interrupt_segment(path)
    with closing(ResearchStorage(plan)) as owner:
        assert [owner.reopen(ref) for ref in refs] == values
        assert owner.recovery["rollbacks"] == 1


def test_many_owned_orphans_make_bounded_durable_progress(tmp_path):
    plan = plan_at(tmp_path)
    refs = []
    with closing(ResearchStorage(plan)) as owner:
        for i in range(9):
            value = packet(1_800_000_000 + i, sample="x" * 65000)
            refs += owner.append([value], value["at"], defer_retention=True)
    forget_index(plan)
    with pytest.raises(OSError, match="eight segments reconciled"):
        ResearchStorage(plan)
    with closing(ResearchStorage(plan)) as owner:
        assert owner.recovery["segments_checked"] == 1
        assert owner.db.execute("SELECT count(*) FROM storage_records").fetchone()[0] == 9
        assert all(owner.reopen(ref)["sample"] == "x" * 65000 for ref in refs)


def test_normal_recorder_retries_busy_startup_recovers_and_records_without_manual_repair(tmp_path):
    plan, values, refs, path, _ = committed_segment(tmp_path)
    interrupt_segment(path)
    directory = tmp_path / "coordination"
    save_plan(directory, plan)
    peer = CollectorLock(path.parent.parent / ".capture-owner.lock")
    peer.acquire()
    recorder = EvidenceRecorder(directory / "research-evidence.sqlite")

    async def observe():
        worker = asyncio.create_task(recorder.run(lambda: True))
        try:
            deadline = asyncio.get_running_loop().time() + 5
            while recorder.status.get("state") != "unavailable":
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.02)
            assert "busy" in recorder.status["reason"]
            assert path.with_name(path.name + "-journal").exists()
            peer.release()
            fresh = packet(1_800_000_020)
            # Wait for the normal empty retry to restore admission first.
            while recorder.status.get("state") != "recording":
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.02)
            recorder.enqueue(fresh)
            while recorder.storage_status.get("last_capture") != fresh["at"]:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.02)
            assert recorder._storage.reopen(refs[0]) == values[0]
        finally:
            peer.release()
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker

    asyncio.run(observe())
    with closing(ResearchStorage(plan)) as owner:
        assert [owner.reopen(ref) for ref in refs] == values
        assert owner.db.execute("SELECT count(*) FROM storage_records").fetchone()[0] == 3


def test_noncanonical_numeric_segment_name_is_foreign(tmp_path):
    plan, _, _, path, _ = committed_segment(tmp_path)
    foreign = path.with_name("segment-" + "٠" * 11 + "٢.sqlite")
    foreign.write_bytes(path.read_bytes())
    before = foreign.read_bytes()
    with pytest.raises(ValueError, match="noncanonical"):
        ResearchStorage(plan)
    assert foreign.read_bytes() == before
