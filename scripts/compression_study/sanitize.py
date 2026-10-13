"""Publish synthetic fixtures or a numeric allowlist of reviewed access results."""

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, cast

from .codecs import StudyError, profile
from .run import access_summary, source_identity, write_json
from .specimens import SEED, STRATA


def numeric(value: Any) -> int | float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise StudyError("Aggregate numeric field contains nonnumeric or nonfinite data")
    return cast(int | float, value)


def timing(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {k: numeric(value.get(k)) for k in ("wall_s", "cpu_s")}


def phases(value: dict[str, Any]) -> dict[str, Any]:
    return {
        k: timing(value[k])
        for k in ("codec", "io_read", "io_write", "hash", "flush") if k in value
    }


def memory(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        k: numeric(value.get(k))
        for k in (
            "rss_bytes", "peak_working_set_bytes", "peak_commit_bytes",
            "process_cpu_s", "priority_class", "threads_observed",
        )
    }
    result["process_io"] = {
        k: numeric(value.get("process_io", {}).get(k))
        for k in ("read_count", "write_count", "read_bytes", "write_bytes")
    }
    return result


def transfer_metrics(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result: dict[str, Any] = {
        "total": timing(value), "phases": phases(value.get("phases", {})),
        "stream_input_bytes": numeric(value.get("stream_input_bytes")),
        "stream_output_bytes": numeric(value.get("stream_output_bytes")),
    }
    if "artifact_verification" in value:
        verification = value["artifact_verification"]
        result["artifact_verification"] = {
            "total": timing(verification), "phases": phases(verification.get("phases", {})),
        }
    return result


def public_sources(value: dict[str, Any]) -> dict[str, str]:
    result = {}
    for name in source_identity():
        sha = value.get(name)
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise StudyError("Missing or invalid public code identity")
        result[name] = sha
    return result


def public_dependencies(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "python", "zlib_build", "zlib_runtime", "sqlite", "zstandard", "lz4", "psutil",
        "pydantic", "pytest", "ruff", "mypy", "lz4_native",
    ):
        version = value.get(key, "unavailable")
        if version != "unavailable" and (
            not isinstance(version, str)
            or not re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}(?:\.[0-9]{1,4})?(?:[a-z][0-9]+)?", version)
        ):
            raise StudyError("Unexpected public dependency version")
        result[key] = version
    for key, choices in (
        ("architecture", {"AMD64", "x86_64", "x86", "ARM64", "aarch64"}),
        ("os", {"Windows", "Linux", "Darwin"}),
        ("pointer_bits", {32, 64}),
        ("zstd_backend", {"cext", "cffi"}),
    ):
        if value.get(key) not in choices:
            raise StudyError("Unexpected public platform metadata")
        result[key] = value[key]
    native = value.get("zstd_native")
    if not isinstance(native, list) or len(native) != 3 or any(
        type(number) is not int or not 0 <= number <= 999 for number in native
    ):
        raise StudyError("Unexpected native codec version")
    result["zstd_native"] = native
    return result


def access_aggregate(value: dict[str, Any]) -> dict[str, Any]:
    """Explicit numeric allowlist. No real identities, paths, records or manifests escape."""
    if value.get("version") != "frozen-sqlite-access-v1":
        raise StudyError("Unknown frozen access protocol")
    if (
        value.get("mode") not in {"smoke", "measure"}
        or value.get("status") not in {"completed", "failed", "deferred"}
        or not re.fullmatch(r"[0-9a-f]{40}", value.get("source_base", ""))
        or value.get("profiles") != {arm: profile(arm) for arm in ("none", "zstd-1")}
        or value.get("seed") != SEED
        or type(value.get("repetitions")) is not int
        or not 1 <= value["repetitions"] <= 5
        or value["mode"] == "measure" and value["repetitions"] != 5
        or value.get("actual_reclaimed_bytes") != 0
        or value.get("operating_quota_change_bytes") != 0
    ):
        raise StudyError("Unexpected protocol identity or operating mutation claim")
    specs = value.get("specimens", [])
    if len(specs) > 8 or len({s["label"] for s in specs}) != len(specs):
        raise StudyError("Aggregate exceeds specimen cap")
    labels = {s["label"]: i + 1 for i, s in enumerate(specs)}
    real_count = value.get("real_specimens")
    if real_count is not None and (
        type(real_count) is not int or not 0 <= real_count <= len(specs)
    ):
        raise StudyError("Invalid real specimen count")
    public_specs = []
    for spec in specs:
        stratum = spec.get("stratum", {})
        if stratum and any(stratum.get(k) not in choices for k, choices in STRATA.items()):
            raise StudyError("Unknown public sampling stratum")
        public_specs.append({
            "specimen": labels[spec["label"]], "input_bytes": numeric(spec["input"]["length"]),
            "records": numeric(spec["signature"]["records"]),
            "stratum": {k: stratum.get(k) for k in STRATA},
        })
    preparations = []
    prepared: set[tuple[int, str]] = set()
    for prep in value.get("preparations", []):
        if prep["arm"] not in {"none", "zstd-1"}:
            raise StudyError("Unexpected access preparation arm")
        key = (labels[prep["label"]], prep["arm"])
        if key in prepared or prep["manifest"]["input"]["length"] != (
            specs[key[0] - 1]["input"]["length"]
        ):
            raise StudyError("Repeated preparation or mismatched input denominator")
        prepared.add(key)
        preparations.append({
            "specimen": labels[prep["label"]], "arm": prep["arm"],
            "input_bytes": numeric(prep["manifest"]["input"]["length"]),
            "output_bytes": numeric(prep["manifest"]["output"]["length"]),
            **{k: numeric(prep.get(k)) for k in (
                "metadata_bytes", "claim_bytes", "input_allocation_bytes",
                "output_allocation_bytes", "manifest_allocation_bytes", "claim_allocation_bytes",
                "peak_staging_bytes", "peak_staging_allocation_bytes",
                "publish_total_wall_s", "publish_total_cpu_s", "supervisor_wall_s",
            )},
            "compression": transfer_metrics(prep["compression"]),
            "verification_decode": transfer_metrics(prep["verification_decode"]),
            "verification_total": timing(prep["verification_total"]),
            "source_verification_phases": phases(prep.get("source_verification_phases", {})),
            "metadata_write": timing(prep["metadata_write"]),
            "finalization": timing(prep["finalization"]),
            "startup": timing(prep.get("startup")), "memory": memory(prep["memory"]),
        })
    samples = []
    expected_groups: dict[tuple[int, str, str], set[int]] = {}
    for sample in value.get("samples", []):
        if sample["arm"] not in {"direct", "none", "zstd-1"} or sample["workload"] not in {
            "one-reference", "batch",
        }:
            raise StudyError("Unknown public access workload")
        ordinal = labels[sample["label"]]
        group = (ordinal, sample["arm"], sample["workload"])
        repetition = sample["repetition"]
        observed = expected_groups.setdefault(group, set())
        if type(repetition) is not int or not 0 <= repetition < 5 or repetition in observed:
            raise StudyError("Duplicate or invalid access repetition")
        observed.add(repetition)
        samples.append({
            "specimen": ordinal, "label": f"specimen-{ordinal}",
            "arm": sample["arm"], "workload": sample["workload"], "repetition": repetition,
            **{k: numeric(sample.get(k)) for k in (
                "sequence", "total_wall_s", "total_cpu_s", "worker_total_wall_s",
                "worker_total_cpu_s", "supervisor_wall_s", "restored_scratch_bytes",
                "restored_scratch_allocation_bytes",
            )},
            **{k: timing(sample.get(k)) for k in (
                "access", "frozen_source_check", "database_read", "full_validation", "startup",
            )},
            "restoration": transfer_metrics(sample.get("restoration")),
            "memory": memory(sample["memory"]),
        })
    complete = (
        value.get("mode") == "measure" and value.get("status") == "completed"
        and len(expected_groups) == len(specs) * 6 and bool(specs)
        and all(reps == set(range(5)) for reps in expected_groups.values())
        and len(prepared) == len(specs) * 2
        and not value.get("failures")
    )
    savings = []
    for arm in ("none", "zstd-1"):
        selected = [prep for prep in preparations if prep["arm"] == arm]
        if len(selected) != len(specs) or not specs:
            continue
        original = sum(prep["input_bytes"] for prep in selected)
        encoded = sum(prep["output_bytes"] for prep in selected)
        metadata = sum(prep["metadata_bytes"] + prep["claim_bytes"] for prep in selected)
        original_allocations = [prep["input_allocation_bytes"] for prep in selected]
        replacement_allocations = [
            prep[key] for prep in selected for key in (
                "output_allocation_bytes", "manifest_allocation_bytes", "claim_allocation_bytes",
            )
        ]
        savings.append({
            "arm": arm, "input_bytes_counted_once": original, "payload_bytes": encoded,
            "metadata_and_claim_bytes": metadata, "replacement_bytes": encoded + metadata,
            "payload_reduction_fraction": 1 - encoded / original if original else None,
            "replacement_reduction_fraction": (
                1 - (encoded + metadata) / original if original else None
            ),
            "input_allocation_bytes": (
                sum(original_allocations) if all(v is not None for v in original_allocations)
                else None
            ),
            "replacement_allocation_bytes": (
                sum(replacement_allocations) if all(v is not None for v in replacement_allocations)
                else None
            ),
        })
    return {
        "version": "frozen-sqlite-access-v1", "mode": value["mode"],
        "source_base": value["source_base"], "source_files": public_sources(value["source_files"]),
        "dependencies": public_dependencies(value["dependencies"]),
        "profiles": {arm: profile(arm) for arm in ("none", "zstd-1")},
        "seed": numeric(value["seed"]), "repetitions": numeric(value["repetitions"]),
        "real_specimens": numeric(value.get("real_specimens")),
        "status": (
            value["status"] if value["status"] in {"completed", "failed", "deferred"} else "failed"
        ),
        "complete_five_repetitions": complete,
        "specimens": public_specs, "preparations": preparations, "samples": samples,
        "summary": access_summary(samples) if samples else [], "savings": savings,
        "strata": STRATA,
        "eligible_frame_bytes": numeric(value.get("selection", {}).get("eligible_frame_bytes")),
        "savings_scope": (
            "selected SQLite input lengths counted once; no operating-tier extrapolation"
        ),
        **{k: numeric(value.get(k)) for k in (
            "input_preparation_wall_s", "phase_wall_s", "peak_owned_scratch_charge_bytes",
            "memory_limit_bytes", "scratch_limit_bytes",
            "operation_deadline_seconds", "phase_deadline_seconds",
        )},
        "failure_count": len(value.get("failures", [])),
        "actual_reclaimed_bytes": 0, "operating_quota_change_bytes": 0,
        "timing_scope": "source check, access, full validation and startup are reported separately",
        "io_scope": "stream calls and process counters; device traffic unmeasured",
        "cache_protocol": "No cache clearing; validation/preparation precedes reads",
        "boundary": "Benchmark-only; operating files unchanged; zero reclaimed bytes",
    }


def sanitized(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("real_specimens") != 0:
        raise StudyError("Real-data publication requires a separate manually reviewed aggregate")
    for spec in value["specimens"]:
        if spec.get("provenance") not in {
            "synthetic-existing-storage-writer",
            "synthetic-seeded-incompressible-bytes",
        } or spec.get("label") not in {"repeated", "mixed", "noisy", "incompressible"}:
            raise StudyError("Only declared synthetic fixture results may be published")
    keys = (
        "version",
        "mode",
        "status",
        "started_utc",
        "finished_utc",
        "preparation_wall_s",
        "phase_wall_s",
        "total_run_wall_s",
        "source_base",
        "source_files",
        "dependencies",
        "profiles",
        "seed",
        "repetitions",
        "phase_deadline_seconds",
        "operation_deadline_seconds",
        "memory_limit_bytes",
        "scratch_limit_bytes",
        "workload",
        "cache_protocol",
        "real_specimens",
        "real_sampling",
        "performance_claim",
        "summary",
        "samples",
        "specimens",
        "peak_owned_scratch_charge_bytes",
        "scratch_peak_scope",
        "allocation_protocol",
        "actual_reclaimed_bytes",
        "operating_quota_change_bytes",
        "boundary",
    )
    public = {k: value[k] for k in keys if k in value}
    public["failures"] = [
        {k: failure[k] for k in ("sequence", "label", "arm", "failure_type") if k in failure}
        for failure in value.get("failures", [])
    ]
    encoded = json.dumps(public, ensure_ascii=True)
    if re.search(
        r"[A-Za-z]:[/\\]|(?:password|credential|owner_token|dsn|stdout|stderr)\"\s*:", encoded
    ):
        raise StudyError("Publication contains a private path or sensitive field")
    return public


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-result", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--access-aggregate", action="store_true")
    args = parser.parse_args()
    value = json.loads(Path(args.private_result).read_text(encoding="utf-8"))
    public = access_aggregate(value) if args.access_aggregate else sanitized(value)
    encoded = json.dumps(public, ensure_ascii=True)
    if re.search(
        r"[A-Za-z]:[/\\]|(?:password|credential|owner_token|dsn|stdout|stderr)\"\s*:", encoded
    ):
        raise StudyError("Publication contains a private path or sensitive field")
    write_json(Path(args.output), public)


if __name__ == "__main__":
    main()
