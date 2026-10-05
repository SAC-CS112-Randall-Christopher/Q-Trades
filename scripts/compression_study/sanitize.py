"""Publish only results from the explicitly synthetic fixture protocol."""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .codecs import StudyError
from .run import write_json


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
    args = parser.parse_args()
    value = json.loads(Path(args.private_result).read_text(encoding="utf-8"))
    write_json(Path(args.output), sanitized(value))


if __name__ == "__main__":
    main()
