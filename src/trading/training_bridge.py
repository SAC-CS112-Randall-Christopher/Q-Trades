"""Operator-configured, bounded local preparation; no model or shell launch surface."""

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from trading.lab_role_contract import packet_json
from trading.llm_training import verify_bundle, write_bundle

MAX_RECEIPT = 262_144


def compact_digest(value: Any) -> str:
    return hashlib.sha256(packet_json(value).encode()).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("Required private archive is missing or linked")
    if path.stat().st_size > MAX_RECEIPT:
        raise ValueError("Private receipt exceeds its bounded limit")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Expected a private JSON object")
    packet_json(result)
    return result


class TrainingBridge:
    def __init__(self, config: Path):
        self.config_path = config

    def configuration(self) -> dict[str, Any]:
        cfg = read_object(self.config_path)
        return self.validate_configuration(cfg)

    @staticmethod
    def validate_configuration(cfg: dict[str, Any]) -> dict[str, Any]:
        if cfg.get("format") != "qtrades-local-lab-v1":
            raise ValueError("Configure the existing private Lab before handoff")
        root, lab, python = (Path(cfg[k]) for k in ("private_root", "lab_root", "python"))
        for path in (root, lab, python):
            if (
                not path.is_absolute()
                or path.drive.startswith("\\\\")
                or any(p.is_symlink() for p in (path, *path.parents))
            ):
                raise ValueError("Lab configuration requires absolute unlinked local paths")
        if not root.is_dir() or any((p / ".git").exists() for p in (root, *root.parents)):
            raise ValueError("Handoffs require existing private storage outside Git")
        expected_python = (
            lab / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        if python.resolve() != expected_python.resolve() or not python.is_file():
            raise ValueError("Use only the configured Lab virtual environment interpreter")
        if not (lab / "src/llm_lab/handoff.py").is_file():
            raise ValueError("Existing Lab does not support this handoff contract")
        source = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((lab / "src/llm_lab").glob("*.py"))
        }
        if compact_digest(source) != cfg["lab_source_sha256"]:
            raise ValueError("Lab source differs from verified configuration")
        if not 5 <= cfg.get("timeout_seconds", 0) <= 180:
            raise ValueError("Handoff timeout must be bounded between 5 and 180 seconds")
        return cfg

    def dispatch(
        self,
        request: dict[str, Any],
        bundle: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        cfg = self.configuration()
        root = Path(cfg["private_root"])
        identity = job_id or uuid.uuid4().hex
        if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("Invalid local handoff identity")
        parent = root / "qtrades-handoffs"
        parent.mkdir(exist_ok=True)
        if parent.is_symlink():
            raise ValueError("Linked handoff directory refused")
        job = parent / identity
        job.mkdir(exist_ok=False)
        frozen = {
            "format": "qtrades-lab-handoff-v1",
            **request,
            "policy": cfg["policy"],
            "profile": cfg["profile"],
            "nonce": uuid.uuid4().hex,
        }
        if bundle is not None:
            manifest = write_bundle(bundle, job / "bundle")
            frozen["expected"]["dataset_sha256"] = manifest["corpus_sha256"]
        (job / "request.json").write_text(packet_json(frozen) + "\n", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(Path(cfg["lab_root"]) / "src"),
                "HF_HUB_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "TOKENIZERS_PARALLELISM": "false",
                "CUDA_VISIBLE_DEVICES": "",
            }
        )
        # Fixed arguments from verified local configuration; no client command, path or URL.
        command = [cfg["python"], "-m", "llm_lab.cli", "application-handoff", str(root), str(job)]
        try:
            completed = subprocess.run(
                command,
                cwd=cfg["lab_root"],
                env=env,
                shell=False,
                capture_output=True,
                timeout=cfg["timeout_seconds"],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "Lab preparation timed out; incomplete private attempt retained"
            ) from exc
        if completed.returncode or len(completed.stdout) > MAX_RECEIPT:
            (job / "failure.txt").write_bytes(completed.stderr[:MAX_RECEIPT])
            reason = completed.stderr.decode("utf-8", errors="replace").strip()[:700]
            raise ValueError("Lab refused preparation: " + reason)
        receipt = read_object(job / "receipt.json")
        if frozen["operation"] == "prepare":
            self.validate(receipt, frozen, cfg)
        (job / "dispatch.json").write_text(
            packet_json(
                {
                    "request_sha256": compact_digest(frozen),
                    "receipt_sha256": compact_digest(receipt),
                    "lab_source_sha256": cfg["lab_source_sha256"],
                    "operation": frozen["operation"],
                    "exit_code": completed.returncode,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return receipt, identity

    @staticmethod
    def validate(receipt: dict[str, Any], request: dict[str, Any], cfg: dict[str, Any]) -> None:
        expected = request["expected"]
        if (
            receipt.get("format") != "llm-lab-preparation-receipt-v1"
            or receipt.get("stage") != "prepared"
            or receipt.get("trained") is not False
            or receipt.get("evaluated") is not False
            or receipt.get("nonce") != request["nonce"]
            or receipt.get("request_sha256") != compact_digest(request)
            or receipt.get("profile_sha256") != compact_digest(cfg["profile"])
            or receipt.get("lab_source_sha256") != cfg["lab_source_sha256"]
            or any(receipt.get(k) != v for k, v in expected.items())
        ):
            raise ValueError(
                "Preparation receipt has conflicting dataset/model/profile/run linkage"
            )

    def reopen(self, job_id: str) -> dict[str, Any]:
        cfg = self.configuration()
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("Invalid local result identity")
        job = Path(cfg["private_root"]) / "qtrades-handoffs" / job_id
        request, receipt, dispatch = (
            read_object(job / name) for name in ("request.json", "receipt.json", "dispatch.json")
        )
        if (
            dispatch.get("operation") != "prepare"
            or dispatch.get("exit_code") != 0
            or dispatch.get("receipt_sha256") != compact_digest(receipt)
            or dispatch.get("request_sha256") != compact_digest(request)
        ):
            raise ValueError("Unverified or interrupted local receipt cannot be imported")
        archived = cfg | {
            "profile": request["profile"],
            "lab_source_sha256": dispatch["lab_source_sha256"],
        }
        self.validate(receipt, request, archived)
        manifest = verify_bundle(job / "bundle")
        if manifest["corpus_sha256"] != receipt["dataset_sha256"]:
            raise ValueError("Linked source dataset changed")
        corpus = read_object(job / "corpus/manifest.json")
        if (
            compact_digest({k: v for k, v in corpus.items() if k != "corpus_sha256"})
            != receipt["corpus_sha256"]
            or corpus["corpus_sha256"] != receipt["corpus_sha256"]
        ):
            raise ValueError("Linked imported corpus changed")
        for name, meta in corpus["files"].items():
            if name not in {s + ".jsonl" for s in ("train", "validation", "test")}:
                raise ValueError("Unexpected imported corpus file")
            file = job / "corpus" / name
            if file.is_symlink() or not file.is_file() or file.stat().st_size != meta["bytes"]:
                raise ValueError("Imported corpus archive is missing or changed")
            if hashlib.sha256(file.read_bytes()).hexdigest() != meta["sha256"]:
                raise ValueError("Imported corpus content changed")
        return receipt
