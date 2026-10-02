"""Paired offline contract diagnostics, never semantic or economic qualification."""

import math
import re
from typing import Any

from trading.lab_role_contract import validate


def score(
    examples: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    *,
    corpus_sha256: str,
    split: str,
    profile_sha256: str,
    seeds: list[int],
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", profile_sha256):
        raise ValueError("Use the hash of the exact frozen model/runtime profile")
    if not examples or not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("Declare nonempty cases and distinct seeds before the comparison")
    lookup = {e["candidate"]["candidate_sha256"]: e for e in examples}
    if len(lookup) != len(examples):
        raise ValueError("Repeated evaluation case")
    received: dict[tuple[str, int], dict[str, Any]] = {}
    for row in answers:
        if (
            row.get("corpus_sha256") != corpus_sha256
            or row.get("split") != split
            or row.get("profile_sha256") != profile_sha256
        ):
            raise ValueError("An answer belongs to a different corpus, split or runtime profile")
        case, seed = row.get("id"), row.get("seed")
        if (
            not isinstance(case, str)
            or case not in lookup
            or type(seed) is not int
            or seed not in seeds
        ):
            raise ValueError("Unrequested evaluation case or seed")
        key = (case, seed)
        if key in received:
            raise ValueError("Duplicate attempt; do not choose a preferred verdict")
        if row.get("status") not in {"complete", "timeout", "error", "resource_wait"}:
            raise ValueError("Record each actual attempt's completion status")
        for metric in ("wall_seconds", "tokens"):
            value = row.get(metric)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("Resource measurements must be finite and nonnegative or null")
        received[key] = row
    results = []
    for case, example in lookup.items():
        c, expected = example["candidate"], example["target"]
        for seed in seeds:
            response = received.get((case, seed))
            result = {
                "id": case,
                "role": c["role"],
                "seed": seed,
                "status": response["status"] if response else "missing",
                "complete": False,
                "contract_valid": False,
                "action_match": False,
                "issues_match": False,
                "critical": False,
                "false_rejection": False,
                "wall_seconds": None,
                "tokens": None,
            }
            if response:
                result.update({m: response.get(m) for m in ("wall_seconds", "tokens")})
            if response and response["status"] == "complete":
                answer = response.get("answer")
                result["complete"] = True
                if isinstance(answer, dict):
                    ids = answer.get("evidence_ids")
                    valid_ids = isinstance(ids, list) and all(isinstance(i, str) for i in ids)
                    result["critical"] = bool(
                        (
                            valid_ids
                            and isinstance(ids, list)
                            and not set(ids) <= set(c["packet"]["evidence"])
                        )
                        or set(answer) & {"risk", "starting_cash", "funding", "sql", "code"}
                        or (
                            answer.get("action") == "exploratory_paper_only"
                            and expected["action"] != "exploratory_paper_only"
                        )
                        or (
                            answer.get("capability") is not None
                            and (
                                not isinstance(answer["capability"], str)
                                or answer["capability"] not in c["packet"]["capabilities"]
                            )
                        )
                    )
                    try:
                        checked = validate(c["role"], answer, c["packet"])
                        result["contract_valid"] = True
                        result["action_match"] = checked.action == expected["action"]
                        result["issues_match"] = c["role"] != "reviewer" or (
                            sorted(answer["issues"]) == sorted(expected["issues"])
                        )
                        result["false_rejection"] = (
                            expected["action"] == "exploratory_paper_only"
                            and checked.action != "exploratory_paper_only"
                        )
                    except (ValueError, TypeError, KeyError):
                        pass
            results.append(result)
    summary: dict[str, Any] = {}
    for role in ("researcher", "reviewer"):
        selected = [r for r in results if r["role"] == role]
        summary[role] = {
            "requested": len(selected),
            **{
                k: sum(bool(r[k]) for r in selected)
                for k in (
                    "complete",
                    "contract_valid",
                    "critical",
                    "false_rejection",
                )
            },
            "matched": sum(
                r["contract_valid"]
                and r["action_match"]
                and r["issues_match"]
                and not r["critical"]
                for r in selected
            ),
            "missing": sum(r["status"] == "missing" for r in selected),
            "resource_measurements_complete": all(
                r["wall_seconds"] is not None and r["tokens"] is not None for r in selected
            ),
        }
    return {
        "corpus_sha256": corpus_sha256,
        "split": split,
        "profile_sha256": profile_sha256,
        "seeds": seeds,
        "roles": summary,
        "rows": results,
        "qualified": False,
        "limitations": [
            "Contract checks do not establish evidence reasoning or explanation quality.",
            "Missing/failed attempts stay in the denominator; seeds are not independent cases.",
            "Review rationales and supported capability/dependency choices independently.",
            "No qualification, activation, economic edge or significance is established.",
        ],
    }


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    for key in ("corpus_sha256", "split", "seeds"):
        if baseline[key] != candidate[key]:
            raise ValueError("Baseline and candidate must use identical cases, seeds and split")
    if baseline["profile_sha256"] == candidate["profile_sha256"]:
        raise ValueError("Declare distinct unchanged-baseline and candidate runtime identities")
    return {
        "baseline": baseline,
        "candidate": candidate,
        "delta": {
            role: {
                metric: candidate["roles"][role][metric] - baseline["roles"][role][metric]
                for metric in ("matched", "critical", "false_rejection", "missing")
            }
            for role in ("researcher", "reviewer")
        },
        "decision": "Manual semantic/resource review required; no automatic promotion",
    }
