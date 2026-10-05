"""Unique partial directory -> verify -> one atomic rename. No operating reader changes."""

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trading.ownership import CollectorLock

from .codecs import CHUNK, MAX_INPUT, Clock, Identity, StudyError, identity, profile, transfer

VERSION = "compression-study-v1"


def read_manifest(result: Path, expected: Identity, arm: str) -> dict[str, Any]:
    expected.validate()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", result.name) or result.is_symlink():
        raise StudyError("Partial or redirected result is not published")
    path = result / "manifest.json"
    if path.stat().st_size > 16 * 1024:
        raise StudyError("Manifest exceeds study bound")
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if (
        manifest.get("version") != VERSION
        or manifest.get("input") != expected.dump()
        or manifest.get("arm") != arm
        or manifest.get("profile") != profile(arm)
        or manifest.get("complete") is not True
    ):
        raise StudyError("Wrong codec/version or stale/mismatched manifest")
    if identity(
        result / "payload",
        max_bytes=MAX_INPUT + MAX_INPUT // 8 + CHUNK,
    ).dump() != manifest.get("output"):
        raise StudyError("Compressed artifact checksum or length differs")
    return manifest


def restore(result: Path, target: Path, expected: Identity, arm: str) -> dict[str, Any]:
    clock = Clock()
    started, cpu = time.perf_counter(), time.process_time()
    read_manifest(result, expected, arm)
    verification = {"wall_s": time.perf_counter() - started, "cpu_s": time.process_time() - cpu}
    metrics = transfer(arm, result / "payload", target, expected, decompress=True, clock=clock)
    metrics["artifact_verification"] = verification
    metrics["reopen_decode_wall_s"] = time.perf_counter() - started
    metrics["reopen_decode_cpu_s"] = time.process_time() - cpu
    return metrics


def publish(
    source: Path,
    parent: Path,
    name: str,
    expected: Identity,
    arm: str,
    *,
    verify_evidence: Callable[[Path], Any] | None = None,
    allocation_fn: Callable[[Path], int | None] | None = None,
    checkpoint: Callable[[str, Path], None] | None = None,
    fail_after: int | None = None,
) -> dict[str, Any]:
    expected.validate()
    profile(arm)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", name):
        raise StudyError("Unsafe result name")
    parent.mkdir(exist_ok=True, parents=True)
    clock = Clock()
    lock = CollectorLock(parent / (name + ".claim"))
    lock.acquire()
    try:
        result = parent / name
        if identity(source, clock) != expected:
            raise StudyError("Frozen source differs from expected identity")
        if result.exists():
            manifest = read_manifest(result, expected, arm)
            # Verify idempotent recovery again; a declared hash is never sufficient.
            retry_copy = parent / (name + ".retry-" + uuid.uuid4().hex)
            restore(result, retry_copy, expected, arm)
            if verify_evidence:
                verify_evidence(retry_copy)
            retry_copy.unlink()  # Individually identified disposable output from this attempt.
            return {"reused": True, "manifest": manifest}
        partial = parent / (name + ".partial-" + uuid.uuid4().hex)
        partial.mkdir()
        if checkpoint:
            checkpoint("before_write", partial)
        encoded = transfer(
            arm,
            source,
            partial / "payload",
            expected,
            decompress=False,
            clock=clock,
            fail_after=fail_after,
        )
        if checkpoint:
            checkpoint("after_write", partial)
        verify_started, verify_cpu = time.perf_counter(), time.process_time()
        restored = partial / "verified-copy"
        decoded = transfer(
            arm, partial / "payload", restored, expected, decompress=True, clock=clock
        )
        if verify_evidence:
            verify_evidence(restored)
        if identity(source, clock) != expected:
            raise StudyError("Frozen source changed during operation")
        verification = {
            "wall_s": time.perf_counter() - verify_started,
            "cpu_s": time.process_time() - verify_cpu,
        }
        manifest = {
            "version": VERSION,
            "complete": True,
            "input": expected.dump(),
            "output": encoded["identity"],
            "arm": arm,
            "profile": profile(arm),
        }
        metadata_started, metadata_cpu = time.perf_counter(), time.process_time()
        staged = partial / "manifest.json"
        with staged.open("x", encoding="utf-8", newline="\n") as out:
            json.dump(manifest, out, sort_keys=True, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
        metadata_write = {
            "wall_s": time.perf_counter() - metadata_started,
            "cpu_s": time.process_time() - metadata_cpu,
        }
        peak_staging = sum(p.stat().st_size for p in partial.iterdir())
        allocations = [allocation_fn(p) for p in partial.iterdir()] if allocation_fn else []
        physical_staging = (
            sum(int(a) for a in allocations if a is not None)
            if allocations and all(a is not None for a in allocations)
            else None
        )
        restored.unlink()  # Only this lane's precisely known verification scratch.
        if checkpoint:
            checkpoint("before_rename", partial)
        final_started, final_cpu = time.perf_counter(), time.process_time()
        # Never replace an earlier result. OS-released claim also excludes concurrent publishers.
        os.rename(partial, result)
        finalization = {
            "wall_s": time.perf_counter() - final_started,
            "cpu_s": time.process_time() - final_cpu,
        }
        if checkpoint:
            checkpoint("after_rename", result)
        return {
            "reused": False,
            "manifest": manifest,
            "compression": encoded,
            "verification_decode": decoded,
            "verification_total": verification,
            "metadata_write": metadata_write,
            "finalization": finalization,
            "peak_staging_bytes": peak_staging,
            "peak_staging_allocation_bytes": physical_staging,
            "metadata_bytes": (result / "manifest.json").stat().st_size,
        }
    finally:
        lock.release()
