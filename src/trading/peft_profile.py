"""One explicit inference-only CPU profile; no qualification or activation implied."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

NAME = "qtrades-crypto-researcher-4b-v2"
PROFILE: dict[str, Any] = {
    "backend": "lab-transformers-peft-cpu-v1",
    "development_only": True,
    "device": "cpu",
    "precision": "float32",
    "quantization": "none",
    "cpu_threads": 2,
    "priority_class": 0x40,
    "processors_max": 2,
    "enable_thinking": False,
    "do_sample": False,
    "seed": 92811,
    "max_context": 8192,
    "max_new_tokens": 1024,
    "timeout_seconds": 600,
    "max_rss_bytes": 24 * 1024**3,
    "minimum_available_bytes": 8 * 1024**3,
    "hourly_wall_seconds": 1800,
    "hourly_tokens": 65536,
    "token_allowance": 8192,
    "python": "3.12.10",
    "packages": {
        "torch": "2.14.1+cpu",
        "transformers": "5.18.0",
        "peft": "0.21.2",
        "accelerate": "1.15.0",
        "tokenizers": "0.23.2",
        "safetensors": "0.8.0",
    },
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def regular(path: Path) -> Path:
    if not path.is_absolute() or path.drive.startswith("\\\\"):
        raise ValueError("Serving requires absolute local paths")
    for p in (path, *path.parents):
        if p.is_symlink() or (
            p.exists() and os.name == "nt" and p.stat().st_file_attributes & 0x400
        ):
            raise ValueError("Serving refuses redirected private paths")
    return path


def read(path: Path) -> dict[str, Any]:
    regular(path)
    if not path.is_file() or path.stat().st_size > 262144:
        raise ValueError("Serving requires a bounded regular JSON receipt")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Serving receipt must be an object")
    digest(value)
    return value


def metadata(config: dict[str, Any], private_root: Path) -> dict[str, Any]:
    """Small metadata only. Weight verification/loading happens in the owned child."""
    if set(config) != {"format", "candidate", "candidate_sha256", "run_sha256"} or (
        config["format"] != "qtrades-peft-development-v1"
    ):
        raise ValueError("Declare the pinned development serving configuration")
    alias_path = regular(Path(config["candidate"]))
    if alias_path != private_root / "named-models" / (NAME + ".json"):
        raise ValueError("Only the selected private trained-v2 alias is supported")
    alias = read(alias_path)
    if hashlib.sha256(alias_path.read_bytes()).hexdigest() != config["candidate_sha256"]:
        raise ValueError("Selected trained alias changed")
    if alias.get("name") != NAME or alias.get("version") != "lab-named-adapter-v1":
        raise ValueError("Selected trained-v2 identity differs")
    paths = {
        key: regular(Path(alias[key]))
        for key in ("base_directory", "run_directory", "adapter_directory")
    }
    for path in paths.values():
        if not path.is_relative_to(private_root) or any(
            (p / ".git").exists() for p in (path, *path.parents)
        ):
            raise ValueError("Weights and runs must remain in the configured private root")
    run_path = paths["run_directory"] / "run.json"
    run = read(run_path)
    if hashlib.sha256(run_path.read_bytes()).hexdigest() != config["run_sha256"]:
        raise ValueError("Selected trained run changed")
    if (
        run.get("status") != "trained"
        or alias.get("base_model") != "Qwen/Qwen3.5-4B"
        or paths["adapter_directory"] != paths["run_directory"] / "best-adapter"
        or paths["base_directory"] != Path(run["base_directory"])
        or alias["selected_step"] != run["best_step"]
        or any(alias[k] != run[k] for k in ("base_sha256", "profile_sha256"))
        or alias["adapter_files"] != run["candidate_files"]
        or run["recipe"]["model_kind"] != "qwen3_5_text"
        or run["recipe"]["enable_thinking"] is not False
    ):
        raise ValueError("Base, active adapter or selected training step linkage differs")
    return {
        "alias": alias,
        "run": run,
        "candidate_sha256": config["candidate_sha256"],
        "run_sha256": config["run_sha256"],
    }
