"""Offline private review/build/paired scoring. Never invokes a model or a database."""

import argparse
import json
from pathlib import Path

from qualify_rule_roles import cases

from trading.lab_role_contract import packet_json
from trading.llm_training import (
    MAX_ROW_BYTES,
    Candidate,
    Example,
    load_jsonl,
    prepare,
    verify_bundle,
    write_bundle,
)
from trading.llm_training_eval import compare, score


def read_object(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ROW_BYTES:
        raise ValueError("Use a regular bounded JSON object")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    packet_json(value)
    return value


def save_new(path: Path, value: dict) -> None:
    path = path.resolve()
    if any((p / ".git").exists() for p in (path.parent, *path.parent.parents)):
        raise ValueError("Keep reviewed private training material outside source repositories")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(packet_json(value) + "\n")


def protected_packets() -> list[dict]:
    # Reuse, never edit or learn from the existing qualification population.
    return [
        {
            "question": "Evaluate the supplied facts and permitted comparison unchanged.",
            "evidence": {"e0": {"facts": description}},
            "capabilities": extra if role == "researcher" else {},
        }
        for split in ("dev", "holdout")
        for role, collection in cases(split).items()
        for _name, description, _action, extra in collection
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    template = sub.add_parser("review-template")
    template.add_argument("candidate", type=Path)
    template.add_argument("output", type=Path)
    review = sub.add_parser("review")
    review.add_argument("candidate", type=Path)
    review.add_argument("adjudication", type=Path)
    review.add_argument("output", type=Path)
    build = sub.add_parser("build")
    build.add_argument("reviewed_jsonl", type=Path)
    build.add_argument("output_directory", type=Path)
    build.add_argument("--train-end", required=True, type=float, help="UTC Unix seconds")
    build.add_argument("--validation-end", required=True, type=float, help="UTC Unix seconds")
    build.add_argument("--embargo-seconds", required=True, type=float)
    check = sub.add_parser("verify")
    check.add_argument("directory", type=Path)
    paired = sub.add_parser("compare")
    paired.add_argument("directory", type=Path)
    paired.add_argument("baseline_answers", type=Path)
    paired.add_argument("candidate_answers", type=Path)
    paired.add_argument("output", type=Path)
    paired.add_argument("--split", choices=("validation", "test"), required=True)
    paired.add_argument("--baseline-profile", required=True)
    paired.add_argument("--candidate-profile", required=True)
    paired.add_argument("--seeds", nargs="+", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command in {"review-template", "review"}:
            original = read_object(args.candidate)
            candidate = Candidate.model_validate(original["candidate"])
            if args.command == "review-template":
                value = {
                    "candidate_sha256": candidate.candidate_sha256,
                    "review": {
                        "approved": False,
                        "reviewer": "",
                        "reviewed_at": 0.0,
                        "rationale": "",
                        "rights_confirmed": False,
                        "data_basis": "observed",
                        "family_ids": [],
                        "categories": [],
                        "episode_start": 0.0,
                        "episode_end": 0.0,
                        "target_available_at": 0.0,
                        "evidence_available_at": {
                            key: None for key in candidate.packet["evidence"]
                        },
                    },
                    "target": None,
                }
                save_new(args.output, value)
                print("Unapproved review template written. No target has been inferred.")
            else:
                value = read_object(args.adjudication)
                if value["candidate_sha256"] != candidate.candidate_sha256:
                    raise ValueError("Adjudication is for another original attempt")
                example = Example.model_validate(
                    {
                        "candidate": candidate.model_dump(),
                        "review": value["review"],
                        "target": value["target"],
                    }
                )
                save_new(args.output, example.model_dump())
                print("Reviewed example saved privately. This does not train or qualify a model.")
        elif args.command == "build":
            result = prepare(
                load_jsonl(args.reviewed_jsonl),
                train_end=args.train_end,
                validation_end=args.validation_end,
                embargo_seconds=args.embargo_seconds,
                protected_packets=protected_packets(),
            )
            print(packet_json(write_bundle(result, args.output_directory)))
        elif args.command == "verify":
            print(packet_json(verify_bundle(args.directory)))
        else:
            manifest = verify_bundle(args.directory)
            examples = load_jsonl(args.directory / (args.split + ".provenance.jsonl"))
            common = dict(
                corpus_sha256=manifest["corpus_sha256"], split=args.split, seeds=args.seeds
            )
            baseline = score(
                examples,
                load_jsonl(args.baseline_answers),
                profile_sha256=args.baseline_profile,
                **common,
            )
            candidate_result = score(
                examples,
                load_jsonl(args.candidate_answers),
                profile_sha256=args.candidate_profile,
                **common,
            )
            result = compare(baseline, candidate_result)
            save_new(args.output, result)
            print(packet_json({"delta": result["delta"], "decision": result["decision"]}))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Pilot refused: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
