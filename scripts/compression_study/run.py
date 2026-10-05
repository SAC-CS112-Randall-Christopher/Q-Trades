"""CLI: bounded reproducible fixture study, supervised one operation at a time."""

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import sysconfig
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from trading.ownership import CollectorLock
from trading.peft_child_owner import ChildOwner

from .codecs import ARMS, Identity, StudyError, dependencies, identity, profile
from .prototype import publish, restore
from .resources import MEMORY_LIMIT, Scratch, allocation, own_memory, workloads
from .specimens import (
    SEED,
    make_specimens,
    read_jsonl,
    read_sqlite,
    verify_jsonl,
    verify_sqlite,
)

BOOTSTRAP = (
    "import sys\n"
    "if sys.stdin.buffer.read(1) != b'1':\n"
    "    raise SystemExit(125)\n"
    "from scripts.compression_study.run import worker_main\n"
    "worker_main()\n"
)


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(value, out, indent=2, ensure_ascii=True, allow_nan=False)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())


def source_identity() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    files = list(Path(__file__).parent.glob("*.py")) + [
        root / "src/trading/research_storage.py",
        root / "src/trading/research_evidence.py",
        root / "src/trading/ownership.py",
        root / "src/trading/peft_child_owner.py",
        root / "tests/test_compression_study.py",
        root / "requirements-lock.txt",
        root / "pyproject.toml",
        Path(__file__).parent / "requirements.txt",
    ]
    return {str(p.relative_to(root)).replace("\\", "/"): identity(p).sha256 for p in sorted(files)}


def worker_main() -> None:
    task = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    spec, arm = task["specimen"], task["arm"]
    if task.get("source_files") != source_identity():
        raise StudyError("Source changed before child operation")
    if os.name == "nt" and psutil.Process().nice() != psutil.IDLE_PRIORITY_CLASS:
        raise StudyError("Child must run at Windows IDLE priority")
    expected = Identity(**spec["input"])
    path, parent = Path(spec["path"]), Path(task["results"])
    representation, signature, selection = spec["representation"], spec["signature"], spec["probes"]

    def verify(restored: Path) -> None:
        if representation == "sqlite":
            verify_sqlite(restored, signature)
        elif representation == "jsonl":
            verify_jsonl(restored, signature)

    def read(candidate: Path) -> dict[str, Any] | None:
        if representation == "sqlite":
            return read_sqlite(candidate, selection)
        if representation == "jsonl":
            return read_jsonl(candidate, selection, signature)
        return None

    direct = read(path)
    result = publish(
        path,
        parent,
        task["name"],
        expected,
        arm,
        verify_evidence=verify,
        allocation_fn=allocation,
    )
    target = parent / (task["name"] + ".read-" + uuid.uuid4().hex)
    decoded = restore(parent / task["name"], target, expected, arm)
    reopened = read(target)
    verify(target)
    if direct and reopened and direct["selection_sha256"] != reopened["selection_sha256"]:
        raise StudyError("First/middle/last/random/range reads differ")
    target.unlink()  # Only the individually named decoder output created by this child.
    result.update(
        {
            "label": spec["label"],
            "representation": representation,
            "arm": arm,
            "repetition": task["repetition"],
            "direct_read": direct,
            "restoration": decoded,
            "restored_read": reopened,
            "reopen_total_wall_s": decoded["reopen_decode_wall_s"]
            + (reopened["wall_s"] if reopened else 0),
            "reopen_total_cpu_s": decoded["reopen_decode_cpu_s"]
            + (reopened["cpu_s"] if reopened else 0),
            "input_allocation_bytes": allocation(path),
            "output_allocation_bytes": allocation(parent / task["name"] / "payload"),
            "manifest_allocation_bytes": allocation(parent / task["name"] / "manifest.json"),
            "claim_bytes": (parent / (task["name"] + ".claim")).stat().st_size,
            "claim_allocation_bytes": allocation(parent / (task["name"] + ".claim")),
            "memory": own_memory(),
            "preservation": "exact length/hash and complete evidence passed",
        }
    )
    print(json.dumps(result, allow_nan=False))


def supervised(task: Path, receipt: Path, *, deadline: float) -> dict[str, Any]:
    if time.monotonic() >= deadline:
        raise TimeoutError("Measured/smoke phase deadline reached")
    root = Path(__file__).resolve().parents[2]
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
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
    )
    # Use the actual base interpreter, not the Windows venv redirector. It waits
    # before importing the study; the existing job utility imposes memory/lifetime first.
    flags = subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
    child = subprocess.Popen(
        [str(getattr(sys, "_base_executable", sys.executable)), "-B", "-c", BOOTSTRAP, str(task)],
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=flags,
    )
    owner = None
    started = time.perf_counter()
    try:
        owner = ChildOwner(child, memory_limit=MEMORY_LIMIT)
        out, err = child.communicate(
            input=b"1", timeout=min(60, max(0.1, deadline - time.monotonic()))
        )
        raw = {
            "returncode": child.returncode,
            "stdout": out.decode("utf-8", errors="replace"),
            "stderr": err.decode("utf-8", errors="replace"),
            "supervisor_wall_s": time.perf_counter() - started,
            "memory_ceiling_bytes": MEMORY_LIMIT,
            "hard_memory_limit_enforced": os.name == "nt",
        }
        write_json(receipt, raw)
        if child.returncode:
            raise StudyError("Child failed; unsuccessful private receipt retained")
        result: dict[str, Any] = json.loads(out)
        result["supervisor_wall_s"] = raw["supervisor_wall_s"]
        result["hard_memory_limit_enforced"] = raw["hard_memory_limit_enforced"]
        return result
    except BaseException as exc:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        if not receipt.exists():
            write_json(receipt, {"failure_type": type(exc).__name__, "reason": str(exc)})
        raise
    finally:
        if owner:
            owner.close()


def summarize(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        groups[(sample["label"], sample["representation"], sample["arm"])].append(sample)
    result = []
    for (label, representation, arm), values in sorted(groups.items()):
        sizes = {v["manifest"]["output"]["length"] for v in values}
        if len(sizes) != 1:
            raise StudyError("Identical frozen bytes produced inconsistent output lengths")
        input_bytes, output_bytes = values[0]["manifest"]["input"]["length"], next(iter(sizes))
        item = {
            "label": label,
            "representation": representation,
            "arm": arm,
            "samples": len(values),
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
            "ratio": output_bytes / input_bytes,
            "reduction_percent": 100 * (1 - output_bytes / input_bytes),
            "metadata_bytes": values[0]["metadata_bytes"],
            "hypothetical_quota_bytes": output_bytes
            + values[0]["metadata_bytes"]
            + values[0]["claim_bytes"],
        }
        paths = {
            "compress_wall_s": ("compression", "wall_s"),
            "compress_cpu_s": ("compression", "cpu_s"),
            "codec_compress_wall_s": ("compression", "phases", "codec", "wall_s"),
            "codec_compress_cpu_s": ("compression", "phases", "codec", "cpu_s"),
            "decode_wall_s": ("restoration", "wall_s"),
            "decode_cpu_s": ("restoration", "cpu_s"),
            "codec_decode_wall_s": ("restoration", "phases", "codec", "wall_s"),
            "codec_decode_cpu_s": ("restoration", "phases", "codec", "cpu_s"),
            "reopen_wall_s": ("reopen_total_wall_s",),
            "reopen_cpu_s": ("reopen_total_cpu_s",),
            "peak_memory_bytes": ("memory", "peak_working_set_bytes"),
            "peak_commit_bytes": ("memory", "peak_commit_bytes"),
            "peak_staging_bytes": ("peak_staging_bytes",),
            "peak_staging_allocation_bytes": ("peak_staging_allocation_bytes",),
            "input_allocation_bytes": ("input_allocation_bytes",),
            "output_allocation_bytes": ("output_allocation_bytes",),
            "manifest_allocation_bytes": ("manifest_allocation_bytes",),
            "claim_allocation_bytes": ("claim_allocation_bytes",),
            "direct_read_wall_s": ("direct_read", "wall_s"),
        }
        for name, path in paths.items():
            observations = []
            for value in values:
                current: Any = value
                for key in path:
                    current = current.get(key) if isinstance(current, dict) else None
                if current is not None:
                    observations.append(current)
            item[name] = (
                {
                    "median": statistics.median(observations),
                    "min": min(observations),
                    "max": max(observations),
                }
                if observations
                else None
            )
        result.append(item)
    return result


def run(args: argparse.Namespace) -> Path:
    run_started = time.monotonic()
    if os.name == "nt":
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    scratch = Scratch(Path(args.scratch), args.owner_token, Path(args.live_root))
    lock = CollectorLock(scratch.work / ".study.claim")
    lock.acquire()
    try:
        folder = scratch.work / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        )
        folder.mkdir()
        start_sources, dependency_versions, workload = (
            source_identity(),
            dependencies(),
            workloads(),
        )
        metadata = {
            "version": "compression-study-v1",
            "mode": args.mode,
            "started_utc": datetime.now(UTC).isoformat(),
            "source_files": start_sources,
            "source_base": args.base,
            "dependencies": dependency_versions,
            "profiles": {a: profile(a) for a in ARMS},
            "seed": SEED,
            "repetitions": args.repetitions,
            "phase_deadline_seconds": args.seconds,
            "operation_deadline_seconds": 60,
            "memory_limit_bytes": MEMORY_LIMIT,
            "scratch_limit_bytes": 1024**3,
            "workload": workload,
            "cache_protocol": (
                "No cache clearing; first-observed study reads after generation/hashing, "
                "then warm repeats"
            ),
            "real_specimens": 0,
            "real_sampling": (
                "Deferred: no authorized consistent frozen copies or quiet window established"
            ),
            "performance_claim": "uncontrolled correctness-smoke timings"
            if args.mode == "smoke"
            else "bounded measured fixture timings",
            "installed_evidence": "No installation inferred from source/merge status",
        }
        write_json(folder / "run-start.json", metadata)
        if args.mode == "measure" and not workload["quiet_window_established"]:
            write_json(
                folder / "deferred.json",
                {"reason": "Shared-hardware quiet window not established", "workload": workload},
            )
            return folder
        samples: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        preparation_started = time.perf_counter()
        specs = make_specimens(folder / "specimens", smallest=args.smallest)
        preparation_wall_s = time.perf_counter() - preparation_started
        write_json(folder / "specimens-private.json", specs)
        (folder / "results").mkdir()
        (folder / "attempts").mkdir()
        phase_started = time.monotonic()
        deadline, rng = phase_started + args.seconds, random.Random(SEED)
        tasks = []
        # Randomize within each repetition; first-observed reads precede repeated reads.
        for rep in range(args.repetitions):
            block = [(rep, spec, arm) for spec in specs for arm in ARMS]
            rng.shuffle(block)
            tasks.extend(block)
        seen: set[tuple[str, str]] = set()
        for sequence, (rep, spec, arm) in enumerate(tasks):
            if args.mode == "measure":
                observed = workloads()
                if not observed["quiet_window_established"]:
                    failures.append(
                        {
                            "sequence": sequence,
                            "reason": "Workload overlap detected; remaining measurements deferred",
                            "workload": observed,
                        }
                    )
                    break
            name = f"{sequence:04d}-{spec['label']}-{spec['representation']}-{arm}-r{rep}"
            task = {
                "specimen": spec,
                "arm": arm,
                "repetition": rep,
                "name": name,
                "results": str(folder / "results"),
                "source_files": start_sources,
            }
            task_path = folder / "attempts" / (name + "-task.json")
            write_json(task_path, task)
            try:
                scratch.check(additional=spec["input"]["length"] * 4 + 65536)
                result = supervised(
                    task_path, folder / "attempts" / (name + "-receipt.json"), deadline=deadline
                )
                result["sequence"] = sequence
                key = (spec["label"], spec["representation"])
                result["read_observation"] = (
                    "first-observed-study-read" if key not in seen else "warm-repeated-study-read"
                )
                seen.add(key)
                samples.append(result)
                # Peak stage is known exactly even when it disappeared between parent observations.
                scratch.peak_bytes = max(
                    scratch.peak_bytes,
                    scratch.check() + spec["input"]["length"],
                )
            except Exception as exc:
                failures.append(
                    {
                        "sequence": sequence,
                        "label": spec["label"],
                        "arm": arm,
                        "failure_type": type(exc).__name__,
                        "reason": str(exc),
                    }
                )
                # Stop consuming resources after any guard or correctness failure.
                break
        if start_sources != source_identity():
            failures.append(
                {"reason": "Source changed during run; performance observations invalid"}
            )
        metadata.update(
            {
                "finished_utc": datetime.now(UTC).isoformat(),
                "preparation_wall_s": preparation_wall_s,
                "phase_wall_s": time.monotonic() - phase_started,
                "total_run_wall_s": time.monotonic() - run_started,
                "summary": summarize(samples),
                "status": "failed" if failures else "completed",
                "samples": samples,
                "failures": failures,
                "peak_owned_scratch_charge_bytes": scratch.peak_bytes,
                "scratch_peak_scope": (
                    "Conservative file-length charge including environment/cache "
                    "and verification copy"
                ),
                "allocation_protocol": (
                    "NTFS FILE_STANDARD_INFO.AllocationSize for normal streams; "
                    "compressed/sparse/reparse allocation is unknown; "
                    "MFT/directory overhead excluded"
                ),
                "specimens": [{k: v for k, v in s.items() if k != "path"} for s in specs],
                "actual_reclaimed_bytes": 0,
                "operating_quota_change_bytes": 0,
                "boundary": (
                    "Benchmark-only. Operating storage and settings are unchanged. "
                    "No space has yet been reclaimed by this lane."
                ),
            }
        )
        write_json(folder / "results-private.json", metadata)
        return folder
    finally:
        lock.release()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--owner-token", required=True)
    parser.add_argument("--live-root", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--mode", choices=["smoke", "measure"], default="smoke")
    parser.add_argument("--repetitions", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--seconds", type=int, choices=range(1, 901), default=900)
    parser.add_argument("--smallest", action="store_true")
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({"private_result_directory": str(result)}))
    if (result / "results-private.json").exists():
        status = json.loads((result / "results-private.json").read_text())
        if status["failures"]:
            raise SystemExit(2)
    else:
        raise SystemExit(3)  # Deferred is explicit, never a successful measurement.


if __name__ == "__main__":
    main()
