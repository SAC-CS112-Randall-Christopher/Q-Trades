"""Bounded development transport to the private Lab loader; operating admit is refused."""

import hashlib
import os
import subprocess
import time
import uuid
from pathlib import Path
from threading import Event
from typing import Any

from trading.lab_role_contract import contract_hash, packet_json, prompt
from trading.local_role_model import LocalRoles
from trading.numerical_resources import child_rss
from trading.ownership import CollectorLock
from trading.peft_child_owner import ChildOwner, available_memory
from trading.peft_profile import PROFILE, digest, metadata, read, regular
from trading.training_bridge import TrainingBridge


class PeftDevelopmentRoles:
    def __init__(self, directory: Path):
        self.directory = regular(directory.resolve())
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def admit(self, role: str) -> dict[str, Any]:
        raise ValueError("Trained-v2 development transport has no operating qualification")

    def declaration(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        cfg = TrainingBridge(self.directory / "training-lab.json").configuration()
        for key in ("private_root", "lab_root", "python"):
            regular(Path(cfg[key]))
        selected = read(self.directory / "development-serving.json")
        linked = metadata(selected, Path(cfg["private_root"]))
        identity = {
            "candidate_sha256": linked["candidate_sha256"],
            "run_sha256": linked["run_sha256"],
            "base_sha256": linked["alias"]["base_sha256"],
            "adapter_sha256": digest(linked["alias"]["adapter_files"]),
            "lab_source_sha256": cfg["lab_source_sha256"],
            "template_sha256": linked["run"]["masking"]["template_sha256"],
        }
        profile = PROFILE | {
            "identity": identity,
            "contract_sha256": contract_hash(),
            "runner_sha256": self.runner_sha256(),
        }
        return cfg, selected, profile

    @staticmethod
    def runner_sha256() -> str:
        return hashlib.sha256(
            Path(__file__).with_name("peft_role_runner.py").read_bytes()
        ).hexdigest()

    def development_admit(self, role: str) -> dict[str, Any]:
        if role not in {"researcher", "reviewer"}:
            raise ValueError("Unsupported development role")
        _, _, profile = self.declaration()
        LocalRoles(self.directory).paper_guard()  # The entire existing operating guard.
        return profile

    @staticmethod
    def preflight(role: str, packet: dict[str, Any], profile: dict[str, Any]) -> None:
        """Refuse incompatible inputs before reserving an actual development attempt."""
        if packet.get("retrieval_contract") and (
            profile.get("rag_contract") != packet["retrieval_contract"]
        ):
            raise ValueError("RAG development packet requires its separately reviewed profile")
        if len(packet_json(packet).encode()) + len(prompt(role).encode()) > 32768:
            raise ValueError("Role packet exceeds the development transport allowance")

    def infer(self, role: str, packet: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        self.preflight(role, packet, profile)
        cfg, selected, current = self.declaration()
        if current != profile or role not in {"researcher", "reviewer"}:
            raise ValueError("Frozen development profile changed before dispatch")
        serialized = packet_json(packet)
        guard = LocalRoles(self.directory)
        guard.paper_guard()
        if self._cancelled.is_set():
            raise ValueError("Development inference was cancelled before dispatch")
        if available_memory() < profile["max_rss_bytes"] + profile["minimum_available_bytes"]:
            raise ValueError("Available memory cannot cover the frozen child budget and reserve")
        lock = CollectorLock(self.directory / "research-inference.lock")
        lock.acquire()
        child: subprocess.Popen[bytes] | None = None
        owned: ChildOwner | None = None
        started = time.perf_counter()
        peak = 0
        job: Path | None = None
        reason = "Development child did not return a complete receipt"
        last_guard = started
        try:
            root = regular(Path(cfg["private_root"]) / "qtrades-development-inference")
            root.mkdir(exist_ok=True)
            job = root / uuid.uuid4().hex
            job.mkdir()
            request = {
                "config": selected,
                "private_root": cfg["private_root"],
                "settings": PROFILE,
                "lab_source_sha256": cfg["lab_source_sha256"],
                "runner_sha256": profile["runner_sha256"],
                "role": role,
                "system": prompt(role),
                "packet_json": serialized,
            }
            with (job / "request.json").open("x", encoding="utf-8") as out:
                out.write(packet_json(request))
                out.flush()
                os.fsync(out.fileno())
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
            }
            env.update(
                {
                    "PYTHONPATH": os.pathsep.join(
                        [
                            str(Path(__file__).resolve().parents[1]),
                            str(Path(cfg["lab_root"]) / "src"),
                        ]
                    ),
                    "PYTHONNOUSERSITE": "1",
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                    "TOKENIZERS_PARALLELISM": "false",
                    "CUDA_VISIBLE_DEVICES": "",
                    "OMP_NUM_THREADS": "2",
                    "MKL_NUM_THREADS": "2",
                    "OPENBLAS_NUM_THREADS": "2",
                }
            )
            flags = (
                subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS
                if os.name == "nt"
                else 0
            )
            with (
                (job / "stdout.log").open("xb") as stdout,
                (job / "stderr.log").open("xb") as stderr,
            ):
                child = subprocess.Popen(
                    [cfg["python"], "-m", "trading.peft_role_runner", str(job)],
                    cwd=cfg["lab_root"],
                    env=env,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    creationflags=flags,
                )
                owned = ChildOwner(child)
                # The child cannot touch weights until the parent pins its lifetime.
                (job / "owner-ready").write_text("owned", encoding="ascii")
                while child.poll() is None:
                    if self._cancelled.is_set():
                        raise ValueError("Development inference was cancelled")
                    if time.perf_counter() - started >= profile["timeout_seconds"]:
                        raise TimeoutError("Development inference exhausted its frozen wall budget")
                    peak = max(peak, child_rss(child.pid))
                    if peak > profile["max_rss_bytes"]:
                        raise ValueError("Development inference exceeded its memory budget")
                    if available_memory() < profile["minimum_available_bytes"]:
                        raise ValueError(
                            "Available memory reserve interrupted development inference"
                        )
                    if stdout.tell() + stderr.tell() > 262144:
                        raise ValueError("Development child logging exceeded its private bound")
                    if time.perf_counter() - last_guard >= 1:
                        guard.paper_guard()
                        last_guard = time.perf_counter()
                    try:
                        child.wait(timeout=0.25)
                    except subprocess.TimeoutExpired:
                        pass
                result = read(job / "response.json")
            if child.returncode or result.get("request_sha256") != digest(request):
                raise ValueError(
                    "Development response is missing or belongs to a different request"
                )
            if "error" in result:
                raise ValueError("Private model execution failed; inspect the retained job receipt")
            response = result["response"]
            if response.get("identity") != profile["identity"] or (
                response.get("settings_sha256") != digest(PROFILE)
            ):
                raise ValueError(
                    "Actual model/adapter/loader identity differs from the frozen request"
                )
            place = response.get("placement", {})
            if place.get("adapter_weights_verified") is not True or any(
                place.get(k) != v
                for k, v in {
                    "device": "cpu",
                    "precision": "float32",
                    "priority_class": 0x40,
                    "processors_allowed": 2,
                    "adapter_active": ["default"],
                    "trainable_params": 0,
                }.items()
            ):
                raise ValueError("Actual model placement or active frozen adapter differs")
            # Record final health, but preserve the answer even if the guard closed
            # as generation ended. Development gives it no dispatch authority.
            try:
                after_guard: dict[str, Any] = guard.paper_guard()
            except Exception:
                after_guard = {"admitted": False, "reason": "Protected guard closed after response"}
            reason = "answered"
            return dict(response) | {
                "profile_sha256": digest(profile),
                "private_job": job.name,
                "peak_rss_bytes": max(peak, response.get("peak_rss_bytes", 0)),
                "transport_wall_seconds": time.perf_counter() - started,
                "paper_guard_after": after_guard,
                "scope": "Unqualified development answer; no financial or operating authority",
            }
        except Exception as exc:
            reason = type(exc).__name__ + ": " + str(exc)[:250]
            if job:
                raise ValueError(f"Development job {job.name}: {reason}") from exc
            raise
        finally:
            try:
                try:
                    if child and child.poll() is None:
                        child.terminate()  # Original Popen process handle on Windows.
                finally:
                    if owned:
                        owned.close()  # Also kills owned children on parent exit/failure.
                    if child:
                        child.wait(timeout=10)
                if job:
                    (job / "dispatch.json").write_text(
                        packet_json(
                            {
                                "status": reason,
                                "wall_seconds": time.perf_counter() - started,
                                "peak_rss_bytes": peak,
                                "exit_code": child.returncode if child else None,
                                "profile_sha256": digest(profile),
                            }
                        ),
                        encoding="utf-8",
                    )
            finally:
                lock.release()
