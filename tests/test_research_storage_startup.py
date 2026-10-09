"""Disposable indexed metadata and real owned-segment interruption cases."""

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from test_capture_recovery import forget_index
from test_research_storage import packet, plan_at

from trading import research_storage as storage


def populated_index(tmp_path, count=120_000):
    # Synthetic sealed-index metadata measures startup SQL independently of file
    # recovery. It is not an archive/reopen or operating acceptance fixture.
    plan = plan_at(tmp_path).model_copy(update={"research_bytes": 128 * 1024**2})
    kinds = ("", "summary", "old-kind", "quotes", "zz-unknown", "\N{SNOWMAN}")
    with closing(storage.ResearchStorage(plan)) as owner, owner.db:
        owner.db.executemany(
            "INSERT INTO storage_records(rowid,sha,segment,record,at,kind) VALUES(?,?,?,?,?,?)",
            (
                (
                    2 * i + 1,
                    f"{i:064x}",
                    1,
                    i + 1,
                    1_900_000_000 if i < len(kinds) else 1_800_000_000 + i,
                    kinds[i % len(kinds)],
                )
                for i in range(count)
            ),
        )
        owner.db.execute(
            "UPDATE storage_state SET rows=?,rows_through=?,last_capture=? WHERE id=1",
            (count, 2 * count - 1 if count else 0, 1_800_000_000),
        )
    return plan


def index_path(plan):
    return Path(plan.root) / "research" / "storage-index.sqlite"


def records_fingerprint(db):
    result = hashlib.sha256()
    for row in db.execute("SELECT * FROM storage_records ORDER BY sha"):
        result.update(repr(tuple(row)).encode())
    return result.hexdigest()


class MeteredConnection(sqlite3.Connection):
    """Count executed VM instructions without disabling the owner's guard."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.vm_steps = 0
        self.set_progress_handler(None, 0)

    def set_progress_handler(self, callback, instructions):
        if callback is None:

            def meter_only():
                self.vm_steps += 1
                return 0

            super().set_progress_handler(meter_only, 1)
            return
        interval = 0

        def meter():
            nonlocal interval
            self.vm_steps += 1
            interval += 1
            if interval >= instructions:
                interval = 0
                return callback()
            return 0

        super().set_progress_handler(meter, 1)


@pytest.mark.parametrize("count", [0, 120_000])
def test_certified_cold_start_has_bounded_sql_and_exact_all_kind_summary(
    tmp_path, monkeypatch, count
):
    plan = populated_index(tmp_path, count)
    with sqlite3.connect(index_path(plan)) as db:
        original = records_fingerprint(db)
        expected = db.execute("SELECT count(*),max(at) FROM storage_records").fetchone()
    connect = sqlite3.connect
    monkeypatch.setattr(
        storage.sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=MeteredConnection)
    )
    for _ in range(2):
        with closing(storage.ResearchStorage(plan)) as owner:
            assert (
                tuple(owner.db.execute("SELECT rows,last_capture FROM storage_state").fetchone())
                == expected
            )
            # A full record scan needs hundreds of thousands of VM steps. This
            # includes schema/adoption checks, all kind seeks and the state write.
            assert owner.db.vm_steps < 8_000
            assert records_fingerprint(owner.db) == original


@pytest.mark.parametrize("legacy", [True, False])
def test_legacy_stale_count_or_old_owner_advancement_is_readopted(tmp_path, legacy):
    plan = populated_index(tmp_path, 120)
    with sqlite3.connect(index_path(plan)) as db:
        if legacy:
            # A predecessor could commit recovered segments before its recount.
            for name in ("rows_version", "rows_through", "rows_scan_through", "rows_scan_count"):
                db.execute(f"ALTER TABLE storage_state DROP COLUMN {name}")
            db.execute("UPDATE storage_state SET rows=7")
        else:
            # The earlier owner inserts records without knowing the new mark.
            db.execute(
                "INSERT INTO storage_records VALUES(?,1,121,?,'legacy',NULL,NULL)",
                ("f" * 64, 1_900_000_001),
            )
        expected = db.execute("SELECT count(*),max(at),max(rowid) FROM storage_records").fetchone()
        original = records_fingerprint(db)
    with closing(storage.ResearchStorage(plan)) as owner:
        assert (
            tuple(
                owner.db.execute(
                    "SELECT rows,last_capture,rows_through FROM storage_state"
                ).fetchone()
            )
            == expected
        )
        assert owner.db.execute("SELECT rows_version FROM storage_state").fetchone()[0] == 1
        assert records_fingerprint(owner.db) == original


def test_seek_plans_and_legacy_census_are_interruptible(tmp_path):
    plan = populated_index(tmp_path, 12_000)
    with sqlite3.connect(index_path(plan)) as db:
        for sql, args in (
            ("SELECT kind FROM storage_records ORDER BY kind LIMIT 1", ()),
            ("SELECT kind FROM storage_records WHERE kind>? ORDER BY kind LIMIT 1", ("quotes",)),
            ("SELECT at FROM storage_records WHERE kind=? ORDER BY at DESC LIMIT 1", ("summary",)),
        ):
            detail = " ".join(r[3] for r in db.execute("EXPLAIN QUERY PLAN " + sql, args))
            assert "COVERING INDEX storage_record_time" in detail and "TEMP B-TREE" not in detail
            steps = 0

            def meter():
                nonlocal steps
                steps += 1
                return 0

            db.set_progress_handler(meter, 1)
            assert db.execute(sql, args).fetchone() is not None
            db.set_progress_handler(None, 0)
            assert steps < 100
        census = "SELECT rowid FROM storage_records WHERE rowid>? ORDER BY rowid LIMIT 4096"
        detail = " ".join(r[3] for r in db.execute("EXPLAIN QUERY PLAN " + census, (0,)))
        assert "INTEGER PRIMARY KEY" in detail and "TEMP B-TREE" not in detail
        assert "Count" not in {r[1] for r in db.execute("EXPLAIN " + census, (0,))}
        db.set_progress_handler(lambda: 1, 1000)
        with pytest.raises(sqlite3.OperationalError) as failure:
            db.execute(census, (0,)).fetchall()
        assert failure.value.sqlite_errorcode == sqlite3.SQLITE_INTERRUPT
        db.set_progress_handler(None, 0)


@pytest.mark.parametrize("phase", ["census", "kind-seek"])
def test_summary_deadline_refuses_without_certifying_partial_work_and_retries(
    tmp_path, monkeypatch, phase
):
    plan = populated_index(tmp_path, 12_000)
    with sqlite3.connect(index_path(plan)) as db:
        if phase == "census":
            db.execute("UPDATE storage_state SET rows_version=0,rows=7")
        previous = tuple(
            db.execute(
                "SELECT rows,rows_version,rows_through,last_capture FROM storage_state"
            ).fetchone()
        )
        original = records_fingerprint(db)
    times = iter([0.0] * 5 + [6.0] * 1000)
    if phase == "census":
        monkeypatch.setattr(storage.time, "monotonic", lambda: next(times))
    else:
        real_latest = storage.ResearchStorage._latest_indexed_capture

        def late(owner):
            monkeypatch.setattr(storage.time, "monotonic", lambda: next(times))
            return real_latest(owner)

        monkeypatch.setattr(storage.ResearchStorage, "_latest_indexed_capture", late)
    with pytest.raises(OSError, match="startup summary budget exhausted"):
        storage.ResearchStorage(plan)
    with sqlite3.connect(index_path(plan)) as db:
        assert (
            tuple(
                db.execute(
                    "SELECT rows,rows_version,rows_through,last_capture FROM storage_state"
                ).fetchone()
            )
            == previous
        )
        assert records_fingerprint(db) == original
    monkeypatch.undo()
    with closing(storage.ResearchStorage(plan)) as owner:
        assert owner.db.execute("SELECT rows FROM storage_state").fetchone()[0] == 12_000
        assert (
            owner.db.execute("SELECT last_capture FROM storage_state").fetchone()[0]
            == 1_900_000_000
        )
        # The actual constructor closed its failed connection and released the
        # same root lock; its later owner can query normally without a stale guard.
        assert owner.db.execute("SELECT count(*) FROM storage_records").fetchone()[0] == 12_000


def test_duplicate_packet_in_verified_orphan_is_not_counted_twice(tmp_path):
    plan = plan_at(tmp_path)
    value = packet(1_800_000_000)
    with closing(storage.ResearchStorage(plan)) as owner:
        ref = owner.append([value], value["at"], defer_retention=True)[0]
        with owner._exclusive(), owner.db:
            owner.db.execute("UPDATE storage_segments SET state='sealed' WHERE id=1")
            owner._declare_segment(2)
            shutil.copyfile(owner._path(1), owner._path(2))
            owner.db.execute("INSERT INTO storage_segments(id,state) VALUES(2,'active')")
    for _ in range(2):
        with closing(storage.ResearchStorage(plan)) as owner:
            assert owner.db.execute("SELECT rows FROM storage_state").fetchone()[0] == 1
            assert owner.db.execute("SELECT count(*) FROM storage_records").fetchone()[0] == 1
            assert owner.db.execute("SELECT sum(rows) FROM storage_segments").fetchone()[0] == 2
            assert owner.reopen(ref) == value
            assert owner.append([value], value["at"], defer_retention=True) == [ref]


@pytest.mark.parametrize("old_owner_advances", [False, True])
def test_legacy_adoption_process_exit_resumes_or_resets_durable_chunks(
    tmp_path, old_owner_advances
):
    plan = populated_index(tmp_path, 50_000)
    with sqlite3.connect(index_path(plan)) as db:
        db.execute("UPDATE storage_state SET rows_version=0,rows=7")
    code = """
import os, sqlite3, sys
from trading import research_storage as storage
class Interrupt(sqlite3.Connection):
    begins = 0
    def execute(self, sql, parameters=()):
        if sql == 'BEGIN IMMEDIATE':
            self.begins += 1
            if self.begins == 3:
                os._exit(35)
        return super().execute(sql, parameters)
connect = sqlite3.connect
storage.sqlite3.connect = lambda *a, **kw: connect(*a, **kw, factory=Interrupt)
storage.ResearchStorage(storage.StoragePlan.model_validate_json(sys.argv[1]))
"""

    def interrupt_after_one_chunk():
        result = subprocess.run(
            [sys.executable, "-c", code, plan.model_dump_json()],
            timeout=15,
            env={**os.environ, "PYTHONPATH": os.path.abspath("src")},
        )
        assert result.returncode == 35

    interrupt_after_one_chunk()
    with sqlite3.connect(index_path(plan)) as db:
        assert tuple(
            db.execute("SELECT rows,rows_version,rows_scan_count FROM storage_state").fetchone()
        ) == (7, 0, 4096)
        if old_owner_advances:
            db.execute(
                "INSERT INTO storage_records VALUES(?,1,50001,?,'legacy',NULL,NULL)",
                ("f" * 64, 1_900_000_001),
            )
            db.execute("UPDATE storage_state SET rows=rows+1")
        expected = db.execute("SELECT count(*),max(at),max(rowid) FROM storage_records").fetchone()
        original = records_fingerprint(db)
    interrupt_after_one_chunk()
    with sqlite3.connect(index_path(plan)) as db:
        assert db.execute("SELECT rows_scan_count FROM storage_state").fetchone()[0] == (
            4096 if old_owner_advances else 8192
        )
        assert db.execute("SELECT rows_version FROM storage_state").fetchone()[0] == 0
        assert db.execute("SELECT rows_through FROM storage_state").fetchone()[0] == expected[2]
    with closing(storage.ResearchStorage(plan)) as owner:
        assert (
            tuple(
                owner.db.execute(
                    "SELECT rows,last_capture,rows_through FROM storage_state"
                ).fetchone()
            )
            == expected
        )
        assert tuple(
            owner.db.execute(
                "SELECT rows_version,rows_scan_through,rows_scan_count FROM storage_state"
            ).fetchone()
        ) == (1, None, 0)
        assert records_fingerprint(owner.db) == original


def test_process_exit_between_recovery_commits_keeps_counter_and_original_refs(tmp_path):
    plan = plan_at(tmp_path)
    values = [packet(1_800_000_000 + i, sample="x" * 65_000) for i in range(2)]
    with closing(storage.ResearchStorage(plan)) as owner:
        refs = owner.append(values, 1_800_000_010, defer_retention=True)
        available = [
            r[0] for r in owner.db.execute("SELECT available FROM storage_records ORDER BY record")
        ]
    forget_index(plan)
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
    with sqlite3.connect(index_path(plan)) as db:
        assert db.execute("SELECT rows FROM storage_state").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM storage_records").fetchone()[0] == 1
    for _ in range(2):
        with closing(storage.ResearchStorage(plan)) as owner:
            assert [owner.reopen(ref) for ref in refs] == values
            assert [
                r[0] for r in owner.db.execute("SELECT available FROM storage_records ORDER BY at")
            ] == available
            assert owner.db.execute("SELECT rows FROM storage_state").fetchone()[0] == 2
            assert owner.append(values, 1_800_000_010, defer_retention=True) == refs
