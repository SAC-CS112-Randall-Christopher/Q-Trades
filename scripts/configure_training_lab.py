"""Pin the existing local Lab for private import/preparation. Never loads a model."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.lab_role_contract import packet_json  # noqa: E402
from trading.training_bridge import TrainingBridge, compact_digest, read_object  # noqa: E402


def configure(args: argparse.Namespace) -> dict:
    root, lab, base, recipe = (
        p.resolve() for p in (args.private_root, args.lab, args.base, args.recipe)
    )
    if not base.is_relative_to(root) or not recipe.is_relative_to(root):
        raise ValueError("Base and recipe must belong to the approved private root")
    model = read_object(base / "base-manifest.json")
    if model.get("provenance") != (
        "https://huggingface.co/Qwen/Qwen3.5-4B/tree/" + str(model.get("revision", ""))
    ) or not model.get("revision"):
        raise ValueError("Pin the verified original Qwen3.5-4B source; do not relabel another base")
    if model["base_sha256"] != compact_digest(
        {k: v for k, v in model.items() if k != "base_sha256"}
    ):
        raise ValueError("Pinned base manifest changed")
    config = read_object(base / "config.json")
    if config.get("model_type") != "qwen3_5":
        raise ValueError("This workflow uses the existing Qwen3.5-4B text configuration")
    source = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((lab / "src/llm_lab").glob("*.py"))
    }
    studies = []
    for sealed, paths in [(True, args.protected_corpus), (False, args.consumed_corpus)]:
        for directory in paths:
            manifest = directory.resolve() / "manifest.json"
            if not manifest.is_relative_to(root):
                raise ValueError("Study must belong to approved private storage")
            read_object(manifest)
            studies.append(
                {
                    "id": manifest.parent.parent.name + "/" + manifest.parent.name,
                    "manifest": str(manifest.relative_to(root)),
                    "sealed": sealed,
                    "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                }
            )
    value = {
        "format": "qtrades-local-lab-v1",
        "private_root": str(root),
        "lab_root": str(lab),
        "python": str(
            lab / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        ),
        "lab_source_sha256": compact_digest(source),
        "model_sha256": model["base_sha256"],
        "timeout_seconds": 180,
        "profile": {
            "name": "Qwen3.5-4B",
            "base": str(base.relative_to(root)),
            "recipe": str(recipe.relative_to(root)),
            "recipe_file_sha256": hashlib.sha256(recipe.read_bytes()).hexdigest(),
        },
        "policy": {"studies": studies, "retirements": []},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        previous = read_object(args.output)
        if previous["private_root"] != value["private_root"]:
            raise ValueError("Do not replace an existing private storage authority")
        value["policy"]["retirements"] = previous["policy"].get("retirements", [])
        value["comparisons"] = previous.get("comparisons", [])
    comparison_inputs = (args.comparison_run, args.comparison_directory, args.semantic_review)
    if any(comparison_inputs):
        if not all(comparison_inputs) or not args.comparison_id:
            raise ValueError(
                "Provide run, comparison directory, semantic review and link ID together"
            )
        run = read_object(args.comparison_run)
        corpus = Path(run["corpus_directory"]).resolve() / "manifest.json"
        if not corpus.is_relative_to(root):
            raise ValueError("Original comparison corpus must belong to private storage")
        original = read_object(corpus)
        link = {
            "id": args.comparison_id,
            "label": args.comparison_label,
            "model_sha256": run["base_sha256"],
            "dataset_sha256": original.get("source_corpus_sha256", original["corpus_sha256"]),
            "review_history": [],
        }
        for key, path in {
            "run": args.comparison_run,
            "plan": args.comparison_directory / "evaluation-plan.json",
            "comparison": args.comparison_directory / "comparison.json",
            "answers": args.comparison_directory / "answers.jsonl",
            "semantic": args.semantic_review,
        }.items():
            path = path.resolve()
            if not path.is_relative_to(root) or path.is_symlink():
                raise ValueError("Existing comparison must belong to private storage")
            link[key] = str(path.relative_to(root))
            link[key + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        for path in args.review_history:
            path = path.resolve()
            if not path.is_relative_to(root):
                raise ValueError("Existing review history must belong to private storage")
            read_object(path)
            link["review_history"].append(
                {
                    "path": str(path.relative_to(root)),
                    "label": path.parent.name + "/" + path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        value["comparisons"] = [
            c for c in value.get("comparisons", []) if c["id"] != link["id"]
        ] + [link]
    TrainingBridge.validate_configuration(value)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(packet_json(value) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    TrainingBridge(args.output).configuration()
    return {
        "configured": True,
        "model": value["profile"]["name"],
        "studies": len(studies),
        "lab_source_sha256": value["lab_source_sha256"],
        "model_sha256": value["model_sha256"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("lab", "private-root", "base", "recipe", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--protected-corpus", type=Path, action="append", default=[])
    parser.add_argument("--consumed-corpus", type=Path, action="append", default=[])
    parser.add_argument("--comparison-run", type=Path)
    parser.add_argument("--comparison-directory", type=Path)
    parser.add_argument("--semantic-review", type=Path)
    parser.add_argument("--comparison-id")
    parser.add_argument("--comparison-label", default="Preserved paired evaluation")
    parser.add_argument("--review-history", type=Path, action="append", default=[])
    print(json.dumps(configure(parser.parse_args()), indent=2))
