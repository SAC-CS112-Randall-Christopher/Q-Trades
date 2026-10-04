"""Bounded read-only dataset diagnostics; the Lab remains historical split authority."""

import math
from typing import Any

from pydantic import ValidationError

from trading.experiment_registry import fingerprint
from trading.lab_role_contract import validate
from trading.llm_training import (
    MAX_ROWS,
    SPLITS,
    Example,
    _content,
    _grams,
    exposure_metadata,
)


def split_for(example: Example, train_end: float, validation_end: float, embargo: float) -> str:
    c, r = example.candidate, example.review
    if c.decision_at <= train_end:
        return "train"
    if r.episode_start > train_end + embargo and c.decision_at <= validation_end:
        return "validation"
    if r.episode_start > validation_end + embargo:
        return "test"
    raise ValueError("Episode spans a cutoff/embargo")


def related(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["evidence_key"] == b["evidence_key"] or set(a["families"]) & set(b["families"]):
        return True
    aw, bw = a["window"], b["window"]
    return bool(aw and bw and max(aw[0], bw[0]) <= min(aw[1], bw[1]))


def coverage(metadata: list[dict[str, Any]]) -> dict[str, Any]:
    # Connected families count related questions/windows once, including BTC/ETH.
    components: list[list[dict[str, Any]]] = []
    for row in metadata:
        attached = [group for group in components if any(related(row, r) for r in group)]
        merged = [row] + [r for group in attached for r in group]
        components = [group for group in components if group not in attached] + [merged]
    categories = sorted(
        {cat for row in metadata for cat in row["categories"]}
        | {
            "useful_proposal",
            "justified_wait",
            "cost_interpretation",
            "negative_inconclusive",
            "strategy_refinement",
            "followup",
        }
    )
    return {
        "examples": len(metadata),
        "distinct_families": len(components),
        "splits": {s: sum(r["split"] == s for r in metadata) for s in SPLITS},
        "skills": {
            cat: {
                "examples": sum(cat in r["categories"] for r in metadata),
                "distinct_families": sum(
                    any(cat in r["categories"] for r in group) for group in components
                ),
            }
            for cat in categories
        },
        "basis": "Reviewed instructional coverage; not representative market frequency",
    }


def preflight(
    rows: list[dict[str, Any]],
    *,
    train_end: float,
    validation_end: float,
    embargo_seconds: float,
    protected_packets: list[dict[str, Any]],
    preparation_only: bool = False,
) -> dict[str, Any]:
    problems: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    protected = [(_content(p), _grams(_content(p))) for p in protected_packets]
    if not 1 <= len(rows) <= MAX_ROWS or not protected:
        raise ValueError("Require 1–2000 examples and existing qualification protection")
    if not all(math.isfinite(v) for v in (train_end, validation_end, embargo_seconds)) or not (
        0 <= train_end < validation_end and embargo_seconds >= 0
    ):
        raise ValueError("Require finite ordered cutoffs and nonnegative embargo")
    tasks: dict[str, tuple[str, str]] = {}
    prior: list[tuple[dict[str, Any], set[str]]] = []
    for number, row in enumerate(rows):
        identity = str(row.get("candidate", {}).get("candidate_sha256", f"row:{number + 1}"))
        try:
            example = Example.model_validate(row)
        except ValidationError as exc:
            for error in exc.errors(include_url=False, include_input=False):
                location = ".".join(str(v) for v in error["loc"])
                code = (
                    "rights"
                    if "rights" in location
                    else "review_metadata"
                    if ("reviewer" in location or "review" in location)
                    else "timing_or_source"
                )
                problems.append(
                    {"id": identity, "code": code, "reason": f"{location}: {error['msg']}"[:800]}
                )
            candidate = row.get("candidate", {})
            if isinstance(row.get("target"), dict) and isinstance(candidate.get("packet"), dict):
                try:
                    validate(
                        candidate.get("role", "researcher"), row["target"], candidate["packet"]
                    )
                except (ValueError, KeyError, TypeError) as target_error:
                    problems.append(
                        {
                            "id": identity,
                            "code": "unsupported_target",
                            "reason": str(target_error)[:800],
                        }
                    )
            continue
        try:
            split = split_for(example, train_end, validation_end, embargo_seconds)
        except ValueError as exc:
            problems.append({"id": identity, "code": "timing", "reason": str(exc)})
            continue
        meta = exposure_metadata(example) | {"split": split}
        text = _content(example.candidate.packet)
        grams = _grams(text)
        if any(
            text == p or (len(g) >= 8 and len(grams & g) / len(g) >= 0.85) for p, g in protected
        ):
            problems.append(
                {
                    "id": identity,
                    "code": "protected_qualification",
                    "reason": "Protected qualification evidence cannot enter this dataset",
                }
            )
        target_key = fingerprint(example.target)
        if meta["task_key"] in tasks:
            previous_id, old_target = tasks[meta["task_key"]]
            problems.append(
                {
                    "id": identity,
                    "related_id": previous_id,
                    "code": "duplicate_task" if old_target == target_key else "conflicting_targets",
                    "reason": "Repeated question/capability/evidence task",
                }
            )
        tasks[meta["task_key"]] = (identity, target_key)
        for previous, previous_grams in prior:
            near_copy = min(len(previous_grams), len(grams)) >= 8 and (
                len(grams & previous_grams) / min(len(grams), len(previous_grams)) >= 0.85
            )
            if previous["split"] != split and (related(meta, previous) or near_copy):
                problems.append(
                    {
                        "id": identity,
                        "related_id": previous["id"],
                        "code": "cross_split_family",
                        "reason": "Shared/overlapping episode or near-copy crosses splits",
                    }
                )
        prior.append((meta, grams))
        metadata.append(meta)
    summary = coverage(metadata)
    counts = summary["splits"]
    if preparation_only:
        if not counts["train"] or counts["validation"] or counts["test"]:
            problems.append(
                {
                    "id": None,
                    "code": "preparation_scope",
                    "reason": "Preparation-only export contains intended training inputs only",
                }
            )
    elif any(not counts[s] for s in SPLITS):
        problems.append(
            {
                "id": None,
                "code": "split_coverage",
                "reason": "All three chronological splits require reviewed examples",
            }
        )
    return {
        "eligible": not problems,
        "problems": problems[: MAX_ROWS * 4],
        "additional_problem_count": max(0, len(problems) - MAX_ROWS * 4),
        "metadata": metadata,
        "coverage": summary,
    }
