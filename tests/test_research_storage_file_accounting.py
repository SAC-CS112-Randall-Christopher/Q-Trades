"""Disposable SQLite sidecar lifecycle and fail-closed storage accounting."""

import errno
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from test_research_storage import plan_at

from trading.research_storage import ResearchStorage, _bytes


@pytest.fixture
def storage(tmp_path):
    owner = ResearchStorage(plan_at(tmp_path))
    try:
        yield owner
    finally:
        owner.close()


def sqlite_writer(directory, name="reference-knowledge.sqlite"):
    path = directory / name
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    db.execute("CREATE TABLE evidence(value TEXT NOT NULL)")
    db.execute("INSERT INTO evidence VALUES('retained original')")
    db.commit()
    assert Path(str(path) + "-shm").is_file()
    assert Path(str(path) + "-wal").is_file()
    return path, db


@pytest.mark.parametrize("suffix", ["-shm", "-wal"])
def test_one_stat_keeps_observed_sidecar_size_after_last_sqlite_connection_closes(
    tmp_path, monkeypatch, suffix
):
    path, db = sqlite_writer(tmp_path)
    sidecar = Path(str(path) + suffix)
    real_stat = Path.stat
    observed_size = real_stat(sidecar).st_size
    calls = []

    def stat_then_close(candidate, **kwargs):
        result = real_stat(candidate, **kwargs)
        if candidate == sidecar:
            calls.append(candidate)
            db.close()
            assert not os.path.exists(sidecar)
        return result

    monkeypatch.setattr(Path, "stat", stat_then_close)
    monkeypatch.setattr(Path, "iterdir", lambda candidate: iter([sidecar]))
    try:
        assert _bytes(tmp_path) == observed_size
        assert calls == [sidecar]
    finally:
        db.close()
    with closing(sqlite3.connect(path)) as reopened:
        assert reopened.execute("SELECT value FROM evidence").fetchone()[0] == "retained original"


@pytest.mark.parametrize("suffix", ["-shm", "-wal"])
def test_sqlite_sidecar_removed_after_enumeration_before_stat_is_absent(
    tmp_path, monkeypatch, suffix
):
    path, db = sqlite_writer(tmp_path)
    sidecar = Path(str(path) + suffix)
    real_stat = Path.stat
    calls = []

    def close_then_stat(candidate, **kwargs):
        if candidate == sidecar:
            calls.append(candidate)
            db.close()
            assert not os.path.exists(sidecar)
        return real_stat(candidate, **kwargs)

    monkeypatch.setattr(Path, "stat", close_then_stat)
    monkeypatch.setattr(
        Path, "iterdir", lambda candidate: iter([sidecar] if os.path.exists(sidecar) else [])
    )
    try:
        assert _bytes(tmp_path) == 0
        assert calls == [sidecar]
    finally:
        db.close()
    with closing(sqlite3.connect(path)) as reopened:
        assert reopened.execute("SELECT value FROM evidence").fetchone()[0] == "retained original"


def test_checkpoint_growth_after_main_stat_is_recounted_before_quota_admission(
    storage, monkeypatch
):
    path, db = sqlite_writer(storage.research)
    db.execute("INSERT INTO evidence VALUES(zeroblob(524288))")
    db.commit()
    sidecar = Path(str(path) + "-shm")
    real_stat = Path.stat
    real_iterdir = Path.iterdir
    main_before = real_stat(path).st_size
    sidecar_names = {path.name + "-shm", path.name + "-wal"}
    stale_used = sum(
        real_stat(candidate).st_size
        for candidate in real_iterdir(storage.research)
        if candidate.name not in sidecar_names
    )
    amount = storage.plan.research_bytes - storage.plan.scratch_bytes - stale_used - 131072
    assert amount > 0
    scans = []
    closes = []

    def main_then_sidecar(candidate):
        rows = list(real_iterdir(candidate))
        if candidate == storage.research:
            scans.append(candidate)
            rows.sort(key=lambda row: 0 if row == path else 1 if row == sidecar else 2)
        return iter(rows)

    def checkpoint_before_sidecar_stat(candidate, **kwargs):
        if candidate == sidecar:
            closes.append(candidate)
            db.close()
            assert not os.path.exists(sidecar)
            assert real_stat(path).st_size > main_before + 131072
        return real_stat(candidate, **kwargs)

    monkeypatch.setattr(Path, "iterdir", main_then_sidecar)
    monkeypatch.setattr(Path, "stat", checkpoint_before_sidecar_stat)
    try:
        with pytest.raises(OSError, match="quota"):
            storage.admission(amount, "research")
        assert scans == [storage.research, storage.research]
        assert closes == [sidecar]
        used = _bytes(storage.research)
        assert stale_used + amount + storage.plan.scratch_bytes < storage.plan.research_bytes
        assert used + amount + storage.plan.scratch_bytes > storage.plan.research_bytes
    finally:
        db.close()
    with closing(sqlite3.connect(path)) as reopened:
        assert reopened.execute("SELECT count(*) FROM evidence").fetchone()[0] == 2


def test_second_real_sqlite_sidecar_disappearance_refuses_without_unbounded_recount(
    tmp_path, monkeypatch
):
    first, first_db = sqlite_writer(tmp_path)
    second, second_db = sqlite_writer(tmp_path, "knowledge-restore-1111111111.sqlite")
    writers = {
        Path(str(first) + "-shm"): first_db,
        Path(str(second) + "-shm"): second_db,
    }
    real_stat = Path.stat
    real_iterdir = Path.iterdir
    scans = []
    closes = []

    def sidecars_first(candidate):
        scans.append(candidate)
        return iter(sorted(real_iterdir(candidate), key=lambda row: row not in writers))

    def close_before_stat(candidate, **kwargs):
        if candidate in writers:
            writers[candidate].close()
            closes.append(candidate)
            assert not os.path.exists(candidate)
        return real_stat(candidate, **kwargs)

    monkeypatch.setattr(Path, "iterdir", sidecars_first)
    monkeypatch.setattr(Path, "stat", close_before_stat)
    try:
        with pytest.raises(OSError, match="recount.*admission refused") as raised:
            _bytes(tmp_path)
        assert isinstance(raised.value.__cause__, FileNotFoundError)
        assert len(scans) == 2 and len(closes) == 2 and len(set(closes)) == 2
    finally:
        first_db.close()
        second_db.close()
    for path in (first, second):
        with closing(sqlite3.connect(path)) as reopened:
            assert (
                reopened.execute("SELECT value FROM evidence").fetchone()[0] == "retained original"
            )


def test_existing_sqlite_sidecars_and_unexpected_files_still_consume_quota(storage):
    _, db = sqlite_writer(storage.research)
    extra = storage.research / "unexpected-retained-file"
    extra.write_bytes(b"x" * 4096)
    (storage.research / "not-a-file").mkdir()
    try:
        used = _bytes(storage.research)
        sidecars = [
            path for path in storage.research.iterdir() if path.name.endswith(("-wal", "-shm"))
        ]
        assert sidecars and all(path.stat().st_size > 0 for path in sidecars)
        sidecar_bytes = sum(path.stat().st_size for path in sidecars)
        assert used >= sidecar_bytes + extra.stat().st_size
        remaining = storage.plan.research_bytes - storage.plan.scratch_bytes - used
        assert remaining > 0
        storage.admission(remaining, "research")
        with pytest.raises(OSError, match="quota"):
            storage.admission(remaining + 1, "research")
    finally:
        db.close()


@pytest.mark.parametrize(
    "name", ["reference-knowledge.sqlite", "unexpected-file", "unexpected-shm"]
)
def test_missing_persistent_or_unrecognized_file_is_not_hidden(tmp_path, monkeypatch, name):
    path = tmp_path / name
    path.write_bytes(b"retained")
    real_stat = Path.stat

    def remove_then_stat(candidate, **kwargs):
        if candidate == path:
            path.unlink()
        return real_stat(candidate, **kwargs)

    monkeypatch.setattr(Path, "stat", remove_then_stat)
    with pytest.raises(FileNotFoundError):
        _bytes(tmp_path)


@pytest.mark.parametrize(
    "error", [PermissionError(errno.EACCES, "denied"), OSError(errno.EIO, "I/O")]
)
def test_genuine_sidecar_io_failure_propagates(tmp_path, monkeypatch, error):
    path, db = sqlite_writer(tmp_path)
    sidecar = Path(str(path) + "-shm")
    real_stat = Path.stat

    def fail_stat(candidate, **kwargs):
        if candidate == sidecar:
            raise error
        return real_stat(candidate, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_stat)
    try:
        with pytest.raises(type(error)) as raised:
            _bytes(tmp_path)
        assert raised.value is error
    finally:
        db.close()


def test_missing_owned_tier_directory_is_not_hidden(tmp_path):
    with pytest.raises(FileNotFoundError):
        _bytes(tmp_path / "missing-tier")


def test_volume_identity_and_free_space_reserve_still_refuse_admission(storage, monkeypatch):
    monkeypatch.setattr(
        "trading.research_storage.volume",
        lambda path: {"identity": "different-owned-volume", "free_bytes": 10**12},
    )
    with pytest.raises(OSError, match="identity changed"):
        storage.admission(0, "research")
    monkeypatch.setattr(
        "trading.research_storage.volume",
        lambda path: {"identity": storage.plan.volume_identity, "free_bytes": 0},
    )
    with pytest.raises(OSError, match="free-space reserve"):
        storage.admission(0, "research")
