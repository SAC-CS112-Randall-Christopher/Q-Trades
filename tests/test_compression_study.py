"""Small disposable evidence/failure checks. No operating root or shared services."""

import ctypes
import gzip
import importlib.util
import json
import os
import random
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

import pytest

from scripts.compression_study.codecs import (
    ARMS,
    MAX_INPUT,
    Clock,
    Identity,
    StudyError,
    identity,
    transfer,
)
from scripts.compression_study.prototype import publish, read_manifest, restore
from scripts.compression_study.specimens import (
    EPOCH,
    export_jsonl,
    make_fixture,
    probes,
    read_jsonl,
    read_sqlite,
    sqlite_signature,
    verify_jsonl,
    verify_sqlite,
)
from trading.research_storage import ResearchStorage


def child_options():
    root = Path(__file__).resolve().parents[1]
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(
                [str(root), str(root / "src"), sysconfig.get_paths()["purelib"]]
            ),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return {
        "cwd": root,
        "env": env,
        "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS
        if os.name == "nt"
        else 0,
    }


def require_codec(arm):
    # Optional codecs belong to the study environment, never the shared product lockfile.
    if arm.startswith("zstd-"):
        pytest.importorskip("zstandard", reason="Use the pinned dedicated study environment")
    elif arm == "lz4-frame":
        pytest.importorskip("lz4.frame", reason="Use the pinned dedicated study environment")


@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize("entropy", [False, True])
def test_all_codecs_restore_exact_bytes_and_preserve_input(tmp_path, arm, entropy):
    require_codec(arm)
    source = tmp_path / "source"
    source.write_bytes(random.Random(11).randbytes(8192) if entropy else b"repeat\x00\xff" * 1000)
    expected = identity(source)
    result = publish(source, tmp_path / "results", "one", expected, arm)
    assert result["manifest"]["input"] == expected.dump()
    restored = tmp_path / "restored"
    restore(tmp_path / "results/one", restored, expected, arm)
    assert restored.read_bytes() == source.read_bytes()
    assert identity(source) == expected
    previous = identity(tmp_path / "results/one/payload")
    assert publish(source, tmp_path / "results", "one", expected, arm)["reused"]
    assert identity(tmp_path / "results/one/payload") == previous


@pytest.mark.parametrize("shape", ["repeated", "mixed", "noisy"])
@pytest.mark.skipif(importlib.util.find_spec("zstandard") is None, reason="Dedicated study codec")
def test_writer_records_and_existing_archive_representation_are_equivalent(
    tmp_path, shape, monkeypatch
):
    monkeypatch.setattr("trading.research_storage.time.time", lambda: EPOCH)
    source = make_fixture(tmp_path, shape, rows=4)
    signature, selection = sqlite_signature(source), probes(source)
    archive = tmp_path / "archive.jsonl"
    export_jsonl(source, archive)
    verify_jsonl(archive, signature)
    assert (
        read_jsonl(archive, selection, signature)["selection_sha256"]
        == read_sqlite(source, selection)["selection_sha256"]
    )
    from trading.research_storage import StoragePlan, volume

    root = source.parent.parent
    plan = StoragePlan(
        root=str(root),
        volume_identity=volume(root)["identity"],
        temporary_bytes=8 * 1024**2,
        research_bytes=8 * 1024**2,
        scratch_bytes=128 * 1024,
        segment_bytes=64 * 1024,
        free_reserve_bytes=5 * 1024**3,
        temporary_retention_seconds=7200,
    )
    store = ResearchStorage(plan)
    try:
        store.housekeeping(EPOCH + 20, capacity_triggered=True)
        retained = root / "research/segment-000000000001.jsonl.gz"
        # Check actual owner serialization and Windows text newlines separately from codecs.
        with gzip.open(retained, "rb") as reader:
            assert reader.read() == archive.read_bytes()
    finally:
        store.close()
    expected = identity(source)
    result = publish(
        source,
        tmp_path / "results",
        "sqlite",
        expected,
        "zstd-3",
        verify_evidence=lambda p: verify_sqlite(p, signature),
    )
    assert result["manifest"]["input"] == expected.dump()
    restored = tmp_path / "restored"
    restore(tmp_path / "results/sqlite", restored, expected, "zstd-3")
    verify_sqlite(restored, signature)
    assert signature["records"] == 4


@pytest.mark.parametrize("arm", ARMS[1:])
@pytest.mark.parametrize("damage", ["truncate", "corrupt", "append", "wrong-codec"])
def test_bad_frames_cannot_complete_a_decoder_output(tmp_path, arm, damage):
    require_codec(arm)
    source = tmp_path / "source"
    source.write_bytes(b"source evidence " * 300)
    expected = identity(source)
    encoded = tmp_path / "encoded"
    transfer(arm, source, encoded, expected, decompress=False)
    data = encoded.read_bytes()
    if damage == "truncate":
        encoded.write_bytes(data[:-1])
    elif damage == "corrupt":
        damaged = bytearray(data)
        damaged[len(damaged) // 2] ^= 0x7F
        encoded.write_bytes(damaged)
    elif damage == "append":
        encoded.write_bytes(data + b"extra")
    else:
        arm = "lz4-frame" if arm != "lz4-frame" else "gzip-9"
    # Native frame errors and our explicit bounds both constitute a refused operation.
    with pytest.raises(StudyError):
        transfer(arm, encoded, tmp_path / "decoded-partial", expected, decompress=True)
    assert identity(source) == expected


@pytest.mark.parametrize("length", [-1, MAX_INPUT + 1, True, "10"])
def test_invalid_declared_sizes_are_rejected_before_io(tmp_path, length):
    with pytest.raises(StudyError, match="declared size"):
        transfer(
            "none",
            tmp_path / "absent",
            tmp_path / "decoded",
            Identity(length, "0" * 64),
            decompress=True,
        )
    assert not (tmp_path / "decoded").exists()


@pytest.mark.parametrize("arm", ARMS)
def test_declared_expansion_cap_prevents_disk_growth(tmp_path, arm):
    require_codec(arm)
    source = tmp_path / "source"
    source.write_bytes(b"x" * (256 * 1024))
    original = identity(source)
    encoded = tmp_path / "encoded"
    transfer(arm, source, encoded, original, decompress=False)
    target = tmp_path / "decoded-partial"
    with pytest.raises(StudyError, match="expansion"):
        transfer(arm, encoded, target, Identity(32, "f" * 64), decompress=True)
    assert target.stat().st_size <= 32
    assert identity(source) == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "future-version"),
        ("arm", "gzip-9"),
        ("input", {"length": 1, "sha256": "f" * 64}),
        ("complete", False),
        ("profile", {"codec": "old-profile"}),
    ],
)
@pytest.mark.skipif(importlib.util.find_spec("zstandard") is None, reason="Dedicated study codec")
def test_stale_or_incompatible_manifests_never_overwrite_results(tmp_path, field, value):
    source = tmp_path / "source"
    source.write_bytes(b"exact original")
    expected = identity(source)
    publish(source, tmp_path / "results", "one", expected, "zstd-1")
    result = tmp_path / "results/one"
    previous = identity(result / "payload")
    manifest = json.loads((result / "manifest.json").read_text())
    manifest[field] = value
    (result / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(StudyError, match="codec/version|manifest"):
        restore(result, tmp_path / "decoded", expected, "zstd-1")
    with pytest.raises(StudyError):
        publish(source, tmp_path / "results", "one", expected, "zstd-1")
    assert identity(result / "payload") == previous
    assert identity(source) == expected
    assert not (tmp_path / "decoded").exists()


@pytest.mark.parametrize("arm", ARMS)
def test_disk_full_simulation_leaves_unique_partial_and_can_retry(tmp_path, arm):
    require_codec(arm)
    source = tmp_path / "source"
    source.write_bytes(random.Random(12).randbytes(2048))
    expected = identity(source)
    parent = tmp_path / "results"
    with pytest.raises(OSError, match="disk-full"):
        publish(source, parent, "one", expected, arm, fail_after=16)
    assert not (parent / "one").exists()
    partials = list(parent.glob("one.partial-*"))
    assert len(partials) == 1 and not (partials[0] / "manifest.json").exists()
    publish(source, parent, "one", expected, arm)
    read_manifest(parent / "one", expected, arm)
    assert partials[0].exists()  # An unsuccessful attempt is retained, never cleaned implicitly.
    assert identity(source) == expected


@pytest.mark.parametrize("point", ["after_write", "before_rename", "after_rename"])
def test_actual_process_interruption_is_recoverable_at_publish_boundaries(tmp_path, point):
    source = tmp_path / "source"
    source.write_bytes(b"exact input" * 100)
    expected = identity(source)
    parent = tmp_path / "results"
    code = """
import os, sys
from pathlib import Path
from scripts.compression_study.codecs import identity
from scripts.compression_study.prototype import publish
source, parent, point = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
def interrupt(at, _):
    if at == point:
        os._exit(23)
publish(source, parent, 'one', identity(source), 'gzip-9', checkpoint=interrupt)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(source), str(parent), point],
        timeout=20,
        capture_output=True,
        **child_options(),
    )
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    assert (parent / "one").exists() == (point == "after_rename")
    if point == "before_rename":
        for partial in parent.glob("one.partial-*"):
            with pytest.raises(StudyError, match="not published"):
                read_manifest(partial, expected, "gzip-9")
    retried = publish(source, parent, "one", expected, "gzip-9")
    assert retried["reused"] == (point == "after_rename")
    read_manifest(parent / "one", expected, "gzip-9")
    assert identity(source) == expected


def test_concurrent_process_claim_refuses_work_and_releases_on_exit(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"protected original")
    expected, parent = identity(source), tmp_path / "results"
    parent.mkdir()
    ready = tmp_path / "claim-ready"
    code = """
import sys
from pathlib import Path
from trading.ownership import CollectorLock
lock = CollectorLock(Path(sys.argv[1]))
lock.acquire()
ready = Path(sys.argv[2])
partial = ready.with_name(ready.name + '.partial')
partial.write_text('owned', encoding='utf-8')
partial.rename(ready)
sys.stdin.buffer.read(1)
"""
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", code, str(parent / "one.claim"), str(ready)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **child_options(),
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        # The closed-marker rename acknowledges acquisition; no second file open is needed.
        assert ready.exists() and child.poll() is None
        with pytest.raises(RuntimeError, match="owns"):
            publish(source, parent, "one", expected, "gzip-9")
        assert not (parent / "one").exists()
    finally:
        try:
            child.communicate(input=b"1", timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=5)
    publish(source, parent, "one", expected, "gzip-9")
    assert identity(source) == expected


@pytest.mark.parametrize("release", [b"", b"0", b"1"])
def test_child_bootstrap_requires_exact_release_before_worker_side_effects(tmp_path, release):
    pytest.importorskip("psutil", reason="Dedicated study supervisor")
    from scripts.compression_study.run import BOOTSTRAP

    marker = tmp_path / "worker-entered"
    spy = """
import sys, types
from pathlib import Path
worker = types.ModuleType('scripts.compression_study.run')
worker.worker_main = lambda: Path(sys.argv[1]).write_text('released', encoding='utf-8')
sys.modules['scripts.compression_study.run'] = worker
"""
    result = subprocess.run(
        [
            getattr(sys, "_base_executable", sys.executable),
            "-B",
            "-c",
            spy + BOOTSTRAP,
            str(marker),
        ],
        input=release,
        capture_output=True,
        timeout=15,
        **child_options(),
    )
    assert result.returncode == (0 if release == b"1" else 125), result.stderr
    assert marker.exists() == (release == b"1")


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows file sharing/rename refusal")
def test_windows_locked_destination_cannot_publish_and_retry_preserves_input(tmp_path):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    source = tmp_path / "source"
    source.write_bytes(b"original" * 100)
    expected, handles = identity(source), []

    def locked(point, partial):
        if point == "before_rename":
            handle = kernel.CreateFileW(str(partial / "payload"), 0x80000000, 1, None, 3, 0, None)
            assert handle not in (None, ctypes.c_void_p(-1).value)
            handles.append(handle)

    try:
        with pytest.raises(OSError):
            publish(source, tmp_path / "results", "one", expected, "gzip-9", checkpoint=locked)
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
    assert not (tmp_path / "results/one").exists()
    publish(source, tmp_path / "results", "one", expected, "gzip-9")
    assert identity(source) == expected


def test_changed_frozen_source_never_publishes(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    expected = identity(source)

    def changed(point, _):
        if point == "after_write":
            source.write_bytes(b"changed during experiment")

    with pytest.raises(StudyError, match="changed during"):
        publish(source, tmp_path / "results", "one", expected, "gzip-9", checkpoint=changed)
    assert not (tmp_path / "results/one").exists()


def test_finite_deadline_preserves_source_and_refuses_completion(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"exact input")
    expected = identity(source)
    clock = Clock(1)
    clock.deadline = 0
    with pytest.raises(TimeoutError, match="deadline"):
        transfer("none", source, tmp_path / "partial", expected, decompress=False, clock=clock)
    assert identity(source) == expected


def test_unresolved_journal_is_refused_without_opening_sqlite(tmp_path):
    source = tmp_path / "copy.sqlite"
    source.write_bytes(b"not a safe frozen database")
    journal = tmp_path / "copy.sqlite-journal"
    journal.write_bytes(b"unresolved")
    with pytest.raises(StudyError, match="sidecar"):
        sqlite_signature(source)
    assert journal.read_bytes() == b"unresolved"


@pytest.mark.parametrize("arm", ["zstd-1", "lz4-frame"])
def test_expected_hash_rejects_valid_frames_without_optional_checksums(tmp_path, arm):
    require_codec(arm)
    source, encoded, decoded = (tmp_path / n for n in ("source", "encoded", "decoded-partial"))
    source.write_bytes(b"original evidence")
    tampered = b"modified evidence"
    assert len(tampered) == source.stat().st_size
    if arm == "zstd-1":
        import zstandard

        encoded.write_bytes(
            zstandard.ZstdCompressor(
                level=1,
                threads=0,
                write_checksum=False,
            ).compress(tampered)
        )
    else:
        import lz4.frame

        encoded.write_bytes(
            lz4.frame.compress(
                tampered,
                compression_level=0,
                content_checksum=False,
                block_checksum=False,
            )
        )
    with pytest.raises(StudyError, match="SHA-256"):
        transfer(arm, encoded, decoded, identity(source), decompress=True)


def test_retry_detects_stale_source_and_preserves_prior_verified_result(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"original evidence")
    expected = identity(source)
    publish(source, tmp_path / "results", "one", expected, "gzip-9")
    previous = identity(tmp_path / "results/one/payload")
    source.write_bytes(b"different evidence")
    with pytest.raises(StudyError, match="Frozen source differs"):
        publish(source, tmp_path / "results", "one", expected, "gzip-9")
    assert identity(tmp_path / "results/one/payload") == previous


def test_physical_allocation_is_separate_from_logical_length(tmp_path):
    pytest.importorskip("psutil", reason="Dedicated study process/allocation observations")
    from scripts.compression_study.resources import allocation

    source = tmp_path / "small"
    source.write_bytes(b"x" * 5001)
    observed = allocation(source)
    assert source.stat().st_size == 5001
    assert observed is None or observed > source.stat().st_size


@pytest.mark.parametrize("private", ["real-data", "path", "credential"])
def test_publication_refuses_real_results_and_private_fields(private):
    pytest.importorskip("psutil", reason="Dedicated study publication environment")
    from scripts.compression_study.sanitize import sanitized

    value = {"real_specimens": 0, "specimens": [], "samples": []}
    if private == "real-data":
        value["real_specimens"] = 1
    elif private == "path":
        value["samples"] = [{"path": r"G:\private-evidence\sample"}]
    else:
        value["samples"] = [{"credential": "private"}]
    with pytest.raises(StudyError, match="Real-data|private path|sensitive"):
        sanitized(value)


def test_one_record_segment_has_exact_reference_and_bounded_range(tmp_path):
    source = make_fixture(tmp_path, "mixed", rows=1)
    selection, signature = probes(source), sqlite_signature(source)
    assert len(selection["references"]) == 1
    assert selection["range"] == [1, 4]
    archive = tmp_path / "archive.jsonl"
    export_jsonl(source, archive)
    assert (
        read_jsonl(archive, selection, signature)["selection_sha256"]
        == read_sqlite(
            source,
            selection,
        )["selection_sha256"]
    )
