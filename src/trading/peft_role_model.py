"""Bounded development transport to the private Lab loader; operating admit is refused."""

import hashlib
import os
import subprocess
import time
import uuid
from copy import deepcopy
from pathlib import Path
from threading import Event, Lock
from typing import Any

from trading.lab_role_contract import contract_hash, packet_json, prompt
from trading.local_role_model import LocalRoles
from trading.numerical_resources import constrain_child
from trading.ownership import CollectorLock
from trading.peft_child_owner import ChildOwner, available_memory
from trading.peft_profile import PROFILE, digest, metadata, read, regular
from trading.training_bridge import TrainingBridge


class DevelopmentTransportFailure(ValueError):
    """Measured failed dispatch; private diagnostics stay in the owned job directory."""

    def __init__(self, receipt: dict[str, Any], response: dict[str, Any] | None = None):
        self.receipt = receipt
        self.response = response
        super().__init__(
            f"Development job {receipt['private_job'] or 'unassigned'}: "
            f"transport failed ({receipt['status']}); no invisible retry"
        )


class PeftDevelopmentRoles:
    def __init__(self, directory: Path, *, development_latency_override: bool = False):
        if type(development_latency_override) is not bool:
            raise ValueError("Development latency override must be explicit")
        self.directory = regular(directory.resolve())
        self._cancelled = Event()
        self._latency_mode = development_latency_override
        self._latency_authorization: dict[str, Any] | None = None
        self._latency_used = False
        self._latency_lock = Lock()
        self._guard_observations: list[dict[str, Any]] = []
        self._guard_log: Path | None = None

    def authorize_latency_measurement(
        self,
        role: str,
        packet: dict[str, Any],
        *,
        request_id: str,
        authorized: bool,
    ) -> None:
        """Bind one expressly authorized performance request, never an operating role."""
        purpose = packet.get("evidence", {}).get("e2", {})
        if (
            not self._latency_mode
            or authorized is not True
            or role not in {"researcher", "reviewer"}
            or purpose.get("purpose") != "performance_diagnostic"
            or purpose.get("research_eligible") is not False
            or not 8 <= len(request_id) <= 64
            or not all(char.isascii() and (char.isalnum() or char == "-") for char in request_id)
        ):
            raise ValueError("Explicit single performance-request latency authorization required")
        with self._latency_lock:
            if self._latency_authorization is not None:
                raise ValueError("Development latency authorization cannot be replaced or reset")
            self._latency_authorization = {
                "role": role,
                "request_id": request_id,
                "packet_sha256": digest(packet),
                "authorized_at": time.time(),
                "attempt_limit": 1,
                "scope": "Development performance latency measurement; no operating qualification",
            }

    def guard_observations(self) -> list[dict[str, Any]]:
        with self._latency_lock:
            return deepcopy(self._guard_observations)

    def _paper_guard(self, phase: str) -> dict[str, Any]:
        if not self._latency_mode:
            return LocalRoles(self.directory).paper_guard()
        with self._latency_lock:
            if self._latency_authorization is None:
                raise ValueError("Development latency override has no per-request authorization")
        observed = LocalRoles(self.directory).development_latency_guard() | {"phase": phase}
        with self._latency_lock:
            if len(self._guard_observations) >= 640:
                raise ValueError("Finite development guard observation budget exhausted")
            self._guard_observations.append(observed)
            if self._guard_log is not None:
                self._append_guard_log(observed)
        if observed["admitted"] is not True:
            raise ValueError(
                "Protected development guard refuses: " + ", ".join(observed["reasons"])
            )
        return observed

    def _append_guard_log(self, observed: dict[str, Any]) -> None:
        assert self._guard_log is not None
        encoded = packet_json(observed) + "\n"
        size = self._guard_log.stat().st_size if self._guard_log.exists() else 0
        if size + len(encoded.encode()) > 32 * 1024**2:
            raise ValueError("Finite development guard evidence byte budget exhausted")
        with self._guard_log.open("a", encoding="utf-8") as stream:
            stream.write(encoded)

    def _consume_latency_authorization(self, role: str, packet: dict[str, Any]) -> None:
        if not self._latency_mode:
            return
        with self._latency_lock:
            authorized = self._latency_authorization
            if (
                authorized is None
                or self._latency_used
                or role != authorized["role"]
                or digest(packet) != authorized["packet_sha256"]
            ):
                raise ValueError("Development latency authorization is missing, used or mismatched")
            self._latency_used = True

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
        if self._latency_mode:
            with self._latency_lock:
                if (
                    self._latency_authorization is None
                    or self._latency_used
                    or role != self._latency_authorization["role"]
                ):
                    raise ValueError(
                        "Development latency admission requires its unused bound request"
                    )
        self._paper_guard("admission")
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
        self._consume_latency_authorization(role, packet)
        self.preflight(role, packet, profile)
        cfg, selected, current = self.declaration()
        if current != profile or role not in {"researcher", "reviewer"}:
            raise ValueError("Frozen development profile changed before dispatch")
        serialized = packet_json(packet)
        self._paper_guard("before_dispatch")
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
        rss_observations = 0
        job: Path | None = None
        category = "dispatch"
        failure: Exception | None = None
        answer: dict[str, Any] | None = None
        cleanup_errors: list[str] = []
        cleanup_reasons: list[str] = []
        last_guard = started
        try:
            root = regular(Path(cfg["private_root"]) / "qtrades-development-inference")
            root.mkdir(exist_ok=True)
            job = root / uuid.uuid4().hex
            job.mkdir()
            if self._latency_mode:
                with self._latency_lock:
                    self._guard_log = job / "latency-guard.jsonl"
                    for observed_guard in self._guard_observations:
                        self._append_guard_log(observed_guard)
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
                subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS | 0x4
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
                # CREATE_SUSPENDED keeps the Windows venv launcher from spawning
                # its interpreter before the existing owner attaches the Job.
                category = "child_ownership"
                owned = ChildOwner(
                    child, memory_limit=profile["max_rss_bytes"], suspended=os.name == "nt"
                )
                category = "child_placement"
                if os.name == "nt":
                    constrain_child(child.pid, distinct_cores=True)
                (job / "owner-ready").write_text("owned", encoding="ascii")
                owned.resume()
                while child.poll() is None:
                    if self._cancelled.is_set():
                        category = "cancelled"
                        raise ValueError("Development inference was cancelled")
                    if time.perf_counter() - started >= profile["timeout_seconds"]:
                        category = "timeout"
                        raise TimeoutError("Development inference exhausted its frozen wall budget")
                    category = "resource_observation"
                    observed = owned.rss()
                    if observed > 0:
                        peak = max(peak, observed)
                        rss_observations += 1
                    if peak > profile["max_rss_bytes"]:
                        category = "memory_budget"
                        raise ValueError("Development inference exceeded its memory budget")
                    if available_memory() < profile["minimum_available_bytes"]:
                        category = "memory_reserve"
                        raise ValueError(
                            "Available memory reserve interrupted development inference"
                        )
                    if stdout.tell() + stderr.tell() > 262144:
                        category = "logging_budget"
                        raise ValueError("Development child logging exceeded its private bound")
                    if time.perf_counter() - last_guard >= 1:
                        category = "paper_guard"
                        self._paper_guard("during_inference")
                        last_guard = time.perf_counter()
                    category = "child_wait"
                    try:
                        child.wait(timeout=0.25)
                    except subprocess.TimeoutExpired:
                        pass
                if child.returncode:
                    category = "child_exit"
                    raise ValueError("Development child exited without a successful response")
                category = "response_receipt"
                result = read(job / "response.json")
            if result.get("request_sha256") != digest(request):
                category = "request_identity"
                raise ValueError(
                    "Development response is missing or belongs to a different request"
                )
            if "error" in result:
                category = "child_error"
                raise ValueError("Private model execution failed; inspect the retained job receipt")
            response = result["response"]
            if response.get("identity") != profile["identity"] or (
                response.get("settings_sha256") != digest(PROFILE)
            ):
                category = "model_identity"
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
                category = "placement"
                raise ValueError("Actual model placement or active frozen adapter differs")
            # Record final health, but preserve the answer even if the guard closed
            # as generation ended. Development gives it no dispatch authority.
            try:
                after_guard: dict[str, Any] = self._paper_guard("after_response")
            except Exception:
                after_guard = {"admitted": False, "reason": "Protected guard closed after response"}
            answer = dict(response) | {
                "profile_sha256": digest(profile),
                "private_job": job.name,
                "peak_rss_bytes": max(peak, response.get("peak_rss_bytes", 0)),
                "transport_wall_seconds": time.perf_counter() - started,
                "paper_guard_after": after_guard
                if not self._latency_mode
                else {
                    key: after_guard.get(key)
                    for key in (
                        "admitted",
                        "reasons",
                        "reason",
                        "effective_latency_block_removed",
                        "research_constrained",
                        "observed_at",
                        "phase",
                    )
                },
                "scope": "Unqualified development answer; no financial or operating authority",
            }
            # The existing runner retains its own peak, which can exceed the
            # sampled owner peak. Keep that answer with the failed-budget receipt.
            if answer["peak_rss_bytes"] > profile["max_rss_bytes"]:
                category = "memory_budget"
                raise ValueError("Development inference exceeded its memory budget")
        except Exception as exc:
            failure = exc
            if category == "child_ownership" and owned is None:
                # Constructor-owned handles are unavailable when acquisition
                # raises. Refusing release does not prove their cleanup.
                cleanup_errors.append("OwnerCleanupUnverified")
                cleanup_reasons.append(
                    "Child owner construction did not return; cleanup unverified"
                )
        finally:
            # Try every original-handle cleanup step even if a preceding one fails.
            # Only then freeze the measured receipt, including the actual exit code.
            try:
                if child and child.poll() is None:
                    child.terminate()
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__[:64])
                cleanup_reasons.append(type(exc).__name__ + ": " + str(exc)[:250])
            try:
                if owned:
                    owned.close()
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__[:64])
                cleanup_reasons.append(type(exc).__name__ + ": " + str(exc)[:250])
            try:
                if child:
                    child.wait(timeout=10)
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__[:64])
                cleanup_reasons.append(type(exc).__name__ + ": " + str(exc)[:250])
            try:
                lock.release()
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__[:64])
                cleanup_reasons.append(type(exc).__name__ + ": " + str(exc)[:250])
        receipt = {
            "kind": "development_transport_failure"
            if failure or cleanup_errors
            else "development_dispatch",
            "complete": not (failure or cleanup_errors),
            "status": category if failure else ("cleanup" if cleanup_errors else "answered"),
            "exception_type": type(failure).__name__[:64] if failure else None,
            "private_job": job.name if job else None,
            "wall_seconds": time.perf_counter() - started,
            "peak_rss_bytes": peak if rss_observations else None,
            "rss_observations": rss_observations,
            "exit_code": child.returncode if child else None,
            "child_terminated": child.poll() is not None if child else None,
            "cleanup_complete": not cleanup_errors,
            "cleanup_error_types": cleanup_errors,
            "profile_sha256": digest(profile),
            "private_dispatch_retained": False,
            "scope": "Unqualified development attempt; no financial or operating authority",
        }
        if self._latency_mode:
            evidence = {
                "development_latency_authorization": self._latency_authorization,
                "guard_observations": len(self._guard_observations),
                "guard_observations_sha256": digest(self._guard_observations),
                "guard_log": "latency-guard.jsonl" if self._guard_log is not None else None,
            }
            receipt.update(evidence)
            if answer is not None:
                answer.update(evidence)
        if job:
            try:
                (job / "dispatch.json").write_text(
                    packet_json(
                        receipt
                        | {
                            "private_dispatch_retained": True,
                            "reason": type(failure).__name__ + ": " + str(failure)[:250]
                            if failure
                            else None,
                            "cleanup_reasons": cleanup_reasons,
                        }
                    ),
                    encoding="utf-8",
                )
                receipt["private_dispatch_retained"] = True
            except Exception as exc:
                if not failure and not cleanup_errors:
                    receipt["kind"] = "development_transport_failure"
                    receipt["complete"] = False
                    receipt["status"] = "dispatch_receipt"
                    receipt["exception_type"] = type(exc).__name__[:64]
                failure = failure or exc
        if failure or cleanup_errors:
            raise DevelopmentTransportFailure(receipt, answer) from failure
        assert answer is not None
        return answer
