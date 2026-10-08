"""Owned trained-v2 requests; explicit paper pilot and development remain distinct."""

import hashlib
import math
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import Event, Lock, RLock
from typing import Any

import httpx

from trading.lab_role_contract import (
    CAPABILITY_VERSION,
    PATTERN_METHOD_QUESTION_POLICY,
    PATTERN_VERSION,
    TOOL_REQUEST_VERSION,
    VERSION,
    contract_hash,
    packet_json,
    pattern_method_policy_sha,
    prompt,
)
from trading.local_role_model import LocalRoles, check_role_contract
from trading.numerical_resources import constrain_child
from trading.ownership import CollectorLock
from trading.peft_child_owner import ChildOwner, available_memory
from trading.peft_profile import NAME, PROFILE, digest, metadata, read, regular
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
    paper_pilot = False

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

    @property
    def role_contract(self) -> str:
        return VERSION

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

    def _guard_authority(self) -> dict[str, Any]:
        return {"development_latency_authorization": self._latency_authorization}

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
        version = check_role_contract(packet, profile)
        if packet.get("retrieval_contract") and (
            profile.get("rag_contract") != packet["retrieval_contract"]
        ):
            raise ValueError("RAG development packet requires its separately reviewed profile")
        if len(packet_json(packet).encode()) + len(prompt(role, version).encode()) > 32768:
            raise ValueError("Role packet exceeds the development transport allowance")

    def _dispatch_checkpoint(self, phase: str) -> None:
        """Optional finite pilot fence; historical transports have no new guard."""

    def infer(self, role: str, packet: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        self.preflight(role, packet, profile)
        self._consume_latency_authorization(role, packet)
        version = check_role_contract(packet, profile)
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
            self._dispatch_checkpoint("after_ownership")
            root = regular(Path(cfg["private_root"]) / "qtrades-development-inference")
            root.mkdir(exist_ok=True)
            job = root / uuid.uuid4().hex
            job.mkdir()
            if self._latency_mode or self.paper_pilot:
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
                "system": prompt(role, version),
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
                self._dispatch_checkpoint("before_child")
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
                self._dispatch_checkpoint("before_resume")
                (job / "owner-ready").write_text("owned", encoding="ascii")
                owned.resume()
                while child.poll() is None:
                    self._dispatch_checkpoint("during_inference")
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
                if not (self._latency_mode or self.paper_pilot)
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
                "scope": (
                    "Experimental paper research pilot; unqualified, no direct financial authority"
                    if self.paper_pilot
                    else "Unqualified development answer; no financial or operating authority"
                ),
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
            "scope": (
                "Experimental paper research pilot; unqualified, no direct financial authority"
                if self.paper_pilot
                else "Unqualified development attempt; no financial or operating authority"
            ),
        }
        if self._latency_mode or self.paper_pilot:
            evidence = self._guard_authority() | {
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


PAPER_PILOT_FORMAT = "qtrades-peft-paper-pilot-v1"
PAPER_PILOT_TOOL_FORMAT = "qtrades-peft-paper-pilot-v2"
PAPER_PILOT_CAPABILITY_FORMAT = "qtrades-peft-paper-pilot-v3"
PAPER_PILOT_SELECTION_FORMAT = "qtrades-peft-paper-pilot-v4"
QUESTION_SELECTION_POLICY = "evidence-question-selection-v1"
PAPER_PILOT_PATTERN_FORMAT = "qtrades-peft-paper-pilot-v5"
PATTERN_QUESTION_POLICY = "pattern-question-selection-v1"
PAPER_PILOT_FINITE_FORMAT = "qtrades-peft-paper-pilot-v6"
PAPER_PILOT_PATTERN_LEARNING_FORMAT = "qtrades-peft-paper-pilot-v7"
PATTERN_LEARNING_QUESTION_POLICY = "outcome-conditioned-pattern-question-v1"
PAPER_PILOT_PATTERN_METHOD_FORMAT = "qtrades-peft-paper-pilot-v8"


def _role_policy(path: Path) -> dict[str, Any]:
    regular(path)
    if path.stat().st_size > 16384:
        raise ValueError("Role policy exceeds its bounded metadata limit")
    return read(path)


def _finite_epoch(value: Any) -> bool:
    if type(value) not in (int, float) or value <= 0:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class PeftPaperPilotRoles(PeftDevelopmentRoles):
    """Explicit unqualified paper grant in the existing policy and inference owners."""

    paper_pilot = True

    def __init__(self, policy_directory: Path):
        # Startup must remain independent of optional private-volume availability.
        super().__init__(policy_directory)
        self.policy_path = policy_directory.resolve() / "role-policy.json"
        self._policy_lock = RLock()
        self._request_lock = Lock()
        self._model_directory: Path | None = None
        self._pilot_active = False
        self._pending_admission: dict[str, Any] | None = None
        self._dispatch_grant: dict[str, Any] | None = None
        self.finite_request_verifier: Callable[..., None] | None = None
        self._finite_dispatch: tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]] | None = (
            None
        )
        self._finite_claimed = False

    def _grant(self) -> dict[str, Any]:
        grant = _role_policy(self.policy_path)
        expected = {
            "format",
            "enabled",
            "grant_id",
            "development_directory",
            "profile_sha256",
            "roles",
            "latency_admission",
            "scope",
        }
        if grant.get("format") in (
            PAPER_PILOT_TOOL_FORMAT,
            PAPER_PILOT_CAPABILITY_FORMAT,
            PAPER_PILOT_SELECTION_FORMAT,
            PAPER_PILOT_PATTERN_FORMAT,
            PAPER_PILOT_FINITE_FORMAT,
            PAPER_PILOT_PATTERN_LEARNING_FORMAT,
            PAPER_PILOT_PATTERN_METHOD_FORMAT,
        ):
            expected.add("role_contract")
        if grant.get("format") in (
            PAPER_PILOT_SELECTION_FORMAT,
            PAPER_PILOT_PATTERN_FORMAT,
            PAPER_PILOT_FINITE_FORMAT,
            PAPER_PILOT_PATTERN_LEARNING_FORMAT,
            PAPER_PILOT_PATTERN_METHOD_FORMAT,
        ):
            expected.add("question_policy")
        if grant.get("format") == PAPER_PILOT_PATTERN_METHOD_FORMAT:
            expected.add("method_policy_sha256")
        if grant.get("format") == PAPER_PILOT_FINITE_FORMAT:
            expected.add("finite_test")
        if set(grant) != expected or (
            grant.get("format")
            not in (
                PAPER_PILOT_FORMAT,
                PAPER_PILOT_TOOL_FORMAT,
                PAPER_PILOT_CAPABILITY_FORMAT,
                PAPER_PILOT_SELECTION_FORMAT,
                PAPER_PILOT_PATTERN_FORMAT,
                PAPER_PILOT_FINITE_FORMAT,
                PAPER_PILOT_PATTERN_LEARNING_FORMAT,
                PAPER_PILOT_PATTERN_METHOD_FORMAT,
            )
            or (
                grant.get("format") == PAPER_PILOT_TOOL_FORMAT
                and grant.get("role_contract") != TOOL_REQUEST_VERSION
            )
            or (
                grant.get("format") in (PAPER_PILOT_CAPABILITY_FORMAT, PAPER_PILOT_SELECTION_FORMAT)
                and grant.get("role_contract") != CAPABILITY_VERSION
            )
            or (
                grant.get("format") == PAPER_PILOT_SELECTION_FORMAT
                and grant.get("question_policy") != QUESTION_SELECTION_POLICY
            )
            or (
                grant.get("format") in (PAPER_PILOT_PATTERN_FORMAT, PAPER_PILOT_FINITE_FORMAT)
                and (
                    grant.get("role_contract") != PATTERN_VERSION
                    or grant.get("question_policy") != PATTERN_QUESTION_POLICY
                )
            )
            or (
                grant.get("format") == PAPER_PILOT_PATTERN_LEARNING_FORMAT
                and (
                    grant.get("role_contract") != PATTERN_VERSION
                    or grant.get("question_policy") != PATTERN_LEARNING_QUESTION_POLICY
                )
            )
            or (
                grant.get("format") == PAPER_PILOT_PATTERN_METHOD_FORMAT
                and (
                    grant.get("role_contract") != PATTERN_VERSION
                    or grant.get("question_policy") != PATTERN_METHOD_QUESTION_POLICY
                    or grant.get("method_policy_sha256") != pattern_method_policy_sha()
                )
            )
            or type(grant.get("enabled")) is not bool
            or grant.get("scope") != "prospective-paper-only"
            or grant.get("latency_admission") != "advisory"
            or grant.get("roles") != ["researcher", "reviewer"]
            or not isinstance(grant.get("grant_id"), str)
            or not 8 <= len(grant["grant_id"]) <= 64
            or not all(c.isascii() and (c.isalnum() or c in "-_") for c in grant["grant_id"])
            or not isinstance(grant.get("profile_sha256"), str)
            or len(grant["profile_sha256"]) != 64
            or not isinstance(grant.get("development_directory"), str)
        ):
            raise ValueError("Declare the explicit bounded trained-v2 paper-pilot grant")
        if grant["format"] == PAPER_PILOT_FINITE_FORMAT:
            from trading.pattern_comparisons import PatternFindingSelection

            finite = grant["finite_test"]
            if (
                type(finite) is not dict
                or set(finite)
                != {"not_before", "expires_at", "max_requests", "selection", "finding_sha256"}
                or any(not _finite_epoch(finite.get(key)) for key in ("not_before", "expires_at"))
                or not 0 < finite["expires_at"] - finite["not_before"] <= 30 * 3600
                or type(finite["max_requests"]) is not int
                or finite["max_requests"] != 3
                or not isinstance(finite["finding_sha256"], str)
                or re.fullmatch(r"[a-f0-9]{64}", finite["finding_sha256"]) is None
                or type(finite["selection"]) is not dict
            ):
                raise ValueError("Declare the exact finite native-pattern test bounds")
            selection = PatternFindingSelection.model_validate(finite["selection"])
            if (
                selection.model_dump() != finite["selection"]
                or selection.symbol != "BTCUSD"
                or selection.timeframe != "5m"
            ):
                raise ValueError("Finite pilot requires one exact BTCUSD native-5m finding")
        return grant

    @staticmethod
    def _finite_time(grant: dict[str, Any]) -> None:
        now = time.time()
        finite = grant["finite_test"]
        if not math.isfinite(now) or now < finite["not_before"]:
            raise ValueError("Finite paper pilot has not reached its original start")
        if now >= finite["expires_at"]:
            raise ValueError("Finite paper pilot original deadline expired")

    def finite_test(self) -> dict[str, Any] | None:
        """Cheap grant/time identity only; no model, resource or registry observation."""
        with self._policy_lock:
            grant = self._grant()
            if grant["format"] != PAPER_PILOT_FINITE_FORMAT:
                return None
            self._finite_time(grant)
            return {
                "grant_id": grant["grant_id"],
                "grant_sha": digest(grant),
                "profile_sha": grant["profile_sha256"],
                "contract_version": PATTERN_VERSION,
                "contract_sha": contract_hash(PATTERN_VERSION),
                "question_policy": PATTERN_QUESTION_POLICY,
                "finite_test": deepcopy(grant["finite_test"]),
            }

    @contextmanager
    def finite_operation(self, expected_scope: dict[str, Any]) -> Iterator[Callable[[], None]]:
        """Fence an already-owned paper operation; never enter registry from here.

        The caller holds the paper writer before entry, and uses the yielded
        cheap guard before financial effects/persistence/commit. A successful
        admitted commit may drain past expiry; do not report it as rolled back.
        """
        with self._policy_lock:

            def guard() -> None:
                authority = self.finite_test()
                if authority is None:
                    raise ValueError("Finite operation requires the explicit finite grant")
                finite = authority["finite_test"]
                observed = {key: value for key, value in authority.items() if key != "finite_test"}
                observed |= {
                    "finite_test_sha": digest(finite),
                    "not_before": finite["not_before"],
                    "expires_at": finite["expires_at"],
                }
                if (
                    type(expected_scope) is not dict
                    or any(
                        key not in expected_scope or expected_scope[key] != value
                        for key, value in observed.items()
                    )
                    or any(
                        type(expected_scope[key]) is not str
                        for key in observed
                        if key not in {"not_before", "expires_at"}
                    )
                    or any(
                        type(expected_scope[key]) not in (int, float)
                        for key in ("not_before", "expires_at")
                    )
                    or self._grant()["enabled"] is not True
                    or self._cancelled.is_set()
                ):
                    raise ValueError("Finite operation scope changed or pilot paused")

            guard()
            yield guard

    @property
    def role_contract(self) -> str:
        with self._policy_lock:
            return str(self._grant().get("role_contract", VERSION))

    def selection_authority(self) -> dict[str, str] | None:
        """Only an explicit selection grant authorizes prospective question production."""
        with self._policy_lock:
            grant = self._grant()
            if grant["format"] not in (
                PAPER_PILOT_SELECTION_FORMAT,
                PAPER_PILOT_PATTERN_FORMAT,
                PAPER_PILOT_FINITE_FORMAT,
                PAPER_PILOT_PATTERN_LEARNING_FORMAT,
                PAPER_PILOT_PATTERN_METHOD_FORMAT,
            ):
                return None
            if grant["format"] == PAPER_PILOT_FINITE_FORMAT:
                self._finite_time(grant)
            self.declaration()
            if self._grant() != grant:
                raise ValueError("Question-selection grant changed while verifying authority")
            pattern = grant["format"] in (
                PAPER_PILOT_PATTERN_FORMAT,
                PAPER_PILOT_FINITE_FORMAT,
                PAPER_PILOT_PATTERN_LEARNING_FORMAT,
                PAPER_PILOT_PATTERN_METHOD_FORMAT,
            )
            version = PATTERN_VERSION if pattern else CAPABILITY_VERSION
            authority = {
                "question_policy": (
                    PATTERN_METHOD_QUESTION_POLICY
                    if grant["format"] == PAPER_PILOT_PATTERN_METHOD_FORMAT
                    else PATTERN_LEARNING_QUESTION_POLICY
                    if grant["format"] == PAPER_PILOT_PATTERN_LEARNING_FORMAT
                    else PATTERN_QUESTION_POLICY
                    if pattern
                    else QUESTION_SELECTION_POLICY
                ),
                "grant_id": grant["grant_id"],
                "grant_sha": digest(grant),
                "profile_sha": grant["profile_sha256"],
                "contract_version": version,
                "contract_sha": contract_hash(version),
            }
            if grant["format"] == PAPER_PILOT_PATTERN_METHOD_FORMAT:
                authority["method_policy_sha256"] = grant["method_policy_sha256"]
            return authority

    def declaration(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        with self._policy_lock:
            grant = self._grant()
            private = regular(Path(grant["development_directory"]))
            private = regular(private.resolve())
            if self._model_directory is not None and private != self._model_directory:
                raise ValueError("Paper-pilot private owner changed; stop before reconnecting")
            original = self.directory
            self.directory = private
            try:
                result = super().declaration()
                if grant.get("role_contract") in (
                    TOOL_REQUEST_VERSION,
                    CAPABILITY_VERSION,
                    PATTERN_VERSION,
                ):
                    result = (
                        result[0],
                        result[1],
                        result[2]
                        | {
                            "role_contract": grant["role_contract"],
                            "contract_sha256": contract_hash(grant["role_contract"]),
                        },
                    )
                if digest(result[2]) != grant["profile_sha256"]:
                    raise ValueError("Paper-pilot grant does not match the frozen model/profile")
            except Exception:
                self.directory = original
                raise
            self._model_directory = private
            return result

    def policy(self) -> dict[str, Any]:
        with self._policy_lock:
            grant = self._grant()
            if grant["format"] == PAPER_PILOT_FINITE_FORMAT:
                self._finite_time(grant)
            self.declaration()
            return grant | {
                "configured_enabled": grant["enabled"],
                "enabled": grant["enabled"] and not self._cancelled.is_set(),
                "paper_pilot": True,
                "experimental": True,
                "qualified": False,
                "qualification_valid": False,
                "model": NAME,
            }

    def _observation(self) -> dict[str, Any]:
        try:
            return LocalRoles(self.directory).development_latency_guard()
        except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
            return {
                "admitted": False,
                "reasons": ["paper_pilot_observation_unavailable"],
                "observation_error_type": type(exc).__name__,
                "research_constrained": None,
                "effective_latency_block_removed": False,
            }

    def _protected(self) -> dict[str, Any]:
        observed = self._observation()
        if available_memory() < PROFILE["max_rss_bytes"] + PROFILE["minimum_available_bytes"]:
            observed = observed | {
                "admitted": False,
                "reasons": [*observed["reasons"], "pilot_prelaunch_memory_reserve"],
            }
        return observed

    def can_research(self) -> bool:
        try:
            return self.policy()["enabled"] is True and self._protected()["admitted"] is True
        except (ValueError, OSError, KeyError):
            return False

    def readiness(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "paper_pilot": True,
            "experimental": True,
            "qualified": False,
            "qualification_valid": False,
            "ready": False,
            "enabled": False,
            "runtime_available": False,
            "mode": "paper_research_pilot",
            "stages": {
                "qualification": {
                    "state": "unqualified",
                    "next_action": "Explicit paper pilot; no qualification or promotion is claimed",
                }
            },
        }
        try:
            policy = self.policy()
            profile = self.declaration()[2]
            result.update(
                profile=profile,
                enabled=policy["enabled"],
                runtime_available=True,
                configured_enabled=policy["configured_enabled"],
                grant_id=policy["grant_id"],
            )
            result["ready"] = self.can_research()
            result["stages"].update(
                policy={"state": "declared", "next_action": "Existing explicit paper-pilot grant"},
                runtime={
                    "state": "declaration_verified",
                    "next_action": "Cold requests use the existing owned loader",
                },
                activation={
                    "state": "enabled" if policy["enabled"] else "disabled",
                    "next_action": "Pause/resume only this explicit paper pilot",
                },
            )
            if not result["ready"]:
                result["reason"] = "Paper pilot paused or protected admission unavailable"
        except (ValueError, OSError, KeyError) as exc:
            result["reason"] = str(exc)[:500]
            result["stages"]["policy"] = {"state": "unavailable", "next_action": result["reason"]}
        return result

    def cancel(self) -> None:
        with self._policy_lock:
            # Latched until explicit resume: a scheduled request cannot erase shutdown/pause.
            super().cancel()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        if type(enabled) is not bool:
            raise ValueError("Paper-pilot activation must be explicit")
        if not enabled:
            self.cancel()
        if enabled and not self._request_lock.acquire(blocking=False):
            raise ValueError("Owned paper-pilot request is still stopping; reopen its receipt")
        try:
            with self._policy_lock:
                grant = self._grant()
                if enabled:
                    if grant["format"] == PAPER_PILOT_FINITE_FORMAT:
                        self._finite_time(grant)
                    self.declaration()
                    if self._protected()["admitted"] is not True:
                        raise ValueError("Protected paper-pilot admission refuses resume")
                changed = grant | {"enabled": enabled}
                temporary = self.policy_path.with_name("role-policy-" + uuid.uuid4().hex + ".tmp")
                try:
                    with temporary.open("x", encoding="utf-8") as stream:
                        stream.write(packet_json(changed))
                        stream.flush()
                        os.fsync(stream.fileno())
                    temporary.replace(self.policy_path)
                    try:
                        if self._grant() != changed:
                            raise ValueError("Paper-pilot activation receipt differs")
                    except (ValueError, OSError) as exc:
                        raise OSError(
                            "Paper-pilot control acknowledgment unknown; reopen policy"
                        ) from exc
                finally:
                    temporary.unlink(missing_ok=True)
                if enabled:
                    self._cancelled.clear()
                return changed
        finally:
            if enabled:
                self._request_lock.release()

    def development_admit(self, role: str) -> dict[str, Any]:
        raise ValueError("Paper pilot cannot reinterpret retained development requests")

    def _paper_guard(self, phase: str) -> dict[str, Any]:
        try:
            policy = self.policy()
            current_grant = self._grant()
            observed = (
                self._protected()
                if phase in {"admission", "before_dispatch"}
                else self._observation()
            ) | {
                "grant_id": policy["grant_id"],
                "grant_sha256": digest(current_grant),
                "grant_enabled": policy["enabled"],
            }
            if policy["enabled"] is not True:
                observed = observed | {
                    "admitted": False,
                    "reasons": [*observed["reasons"], "paper_pilot_paused"],
                }
            if self._pilot_active and current_grant != self._dispatch_grant:
                observed = observed | {
                    "admitted": False,
                    "reasons": [*observed["reasons"], "paper_pilot_grant_changed"],
                }
        except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
            observed = {
                "admitted": False,
                "reasons": ["paper_pilot_authority_unavailable"],
                "observation_error_type": type(exc).__name__,
                "research_constrained": None,
                "effective_latency_block_removed": False,
            }
        observed |= {
            "phase": phase,
            "paper_pilot": True,
            "experimental": True,
            "qualified": False,
        }
        with self._latency_lock:
            if phase == "admission" and not self._pilot_active:
                self._pending_admission = deepcopy(observed)
            else:
                if len(self._guard_observations) >= 640:
                    raise ValueError("Finite paper-pilot guard observation budget exhausted")
                self._guard_observations.append(observed)
                if self._guard_log is not None:
                    self._append_guard_log(observed)
        if observed["admitted"] is not True:
            raise ValueError(
                "Protected paper-pilot guard refuses: " + ", ".join(observed["reasons"])
            )
        return observed

    def _guard_authority(self) -> dict[str, Any]:
        grant = self._dispatch_grant
        result = {
            "paper_pilot_grant": (
                {key: grant[key] for key in ("grant_id", "profile_sha256", "scope")}
                | {"sha256": digest(grant)}
                if grant
                else None
            ),
            "paper_pilot": True,
            "experimental": True,
            "qualified": False,
        }
        if self._finite_dispatch is not None:
            result |= {
                "finite_request": deepcopy(self._finite_dispatch[3]),
                "finite_dispatch_claimed": self._finite_claimed,
            }
        return result

    def admit(self, role: str) -> dict[str, Any]:
        if role not in {"researcher", "reviewer"}:
            raise ValueError("Unsupported paper-pilot role")
        self._paper_guard("admission")
        return self.declaration()[2]

    @staticmethod
    def preflight(role: str, packet: dict[str, Any], profile: dict[str, Any]) -> None:
        if "retrieval_contract" in packet or "knowledge" in packet:
            raise ValueError("Paper-pilot profile does not authorize retrieval input")
        if packet.get("evidence", {}).get("e2", {}).get("purpose") == "performance_diagnostic":
            raise ValueError("Performance diagnostic request is outside paper research")
        PeftDevelopmentRoles.preflight(role, packet, profile)

    def instance_preflight(
        self, role: str, packet: dict[str, Any], profile: dict[str, Any]
    ) -> None:
        if "selection_authority" not in packet:
            with self._policy_lock:
                grant_format = self._grant()["format"]
                if grant_format == PAPER_PILOT_PATTERN_LEARNING_FORMAT:
                    raise ValueError("Pattern learning requires its exact current v7 authority")
                if grant_format == PAPER_PILOT_PATTERN_METHOD_FORMAT:
                    raise ValueError(
                        "Pattern method learning requires its exact current v8 authority"
                    )
        if "selection_authority" in packet:
            with self._policy_lock:
                authority = self.selection_authority()
                supplied = packet["selection_authority"]
                if (
                    authority is None
                    or type(supplied) is not dict
                    or supplied != authority
                    or any(type(value) is not str for value in supplied.values())
                    or digest(profile) != authority["profile_sha"]
                ):
                    version = (
                        "v8"
                        if authority is not None
                        and authority["question_policy"] == PATTERN_METHOD_QUESTION_POLICY
                        else "v7"
                        if authority is not None
                        and authority["question_policy"] == PATTERN_LEARNING_QUESTION_POLICY
                        else "v5"
                        if packet.get("contract") == PATTERN_VERSION
                        else "v4"
                    )
                    raise ValueError(
                        f"Question selection requires its exact current {version} authority"
                    )
                if self.policy()["enabled"] is not True:
                    raise ValueError("Question-selection grant is paused or cancelled")
        self.preflight(role, packet, profile)

    def infer(self, role: str, packet: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        return self._infer(role, packet, profile, None)

    def infer_reserved(
        self,
        role: str,
        packet: dict[str, Any],
        profile: dict[str, Any],
        reservation: dict[str, Any],
    ) -> dict[str, Any]:
        """Only an existing worker's exact reserved attempt can spend a finite dispatch."""
        return self._infer(role, deepcopy(packet), deepcopy(profile), deepcopy(reservation))

    def _verify_finite_dispatch(self, *, claim: bool = False) -> None:
        bound = self._finite_dispatch
        if bound is None:
            raise ValueError("Finite pilot has no reserved worker attempt")
        role, packet, profile, reservation = bound
        authority = self.finite_test()
        if authority is None:
            raise ValueError("Reserved finite dispatch lost its finite grant")
        finite = authority["finite_test"]
        selected = {key: value for key, value in authority.items() if key != "finite_test"}
        if (
            type(reservation) is not dict
            or set(reservation)
            != {
                "grant_id",
                "grant_sha",
                "root_task",
                "task",
                "stage",
                "attempt",
                "packet_sha256",
                "expires_at",
                "finite_test_sha",
            }
            or reservation["grant_id"] != authority["grant_id"]
            or reservation["grant_sha"] != authority["grant_sha"]
            or reservation["expires_at"] != finite["expires_at"]
            or type(reservation["expires_at"]) not in (int, float)
            or reservation["finite_test_sha"] != digest(finite)
            or reservation["packet_sha256"] != digest(packet)
            or digest(profile) != authority["profile_sha"]
            or packet.get("selection_authority") != selected
            or role not in {"researcher", "reviewer"}
            or any(
                type(reservation[key]) is not str
                for key in (
                    "grant_id",
                    "grant_sha",
                    "root_task",
                    "task",
                    "stage",
                    "packet_sha256",
                    "finite_test_sha",
                )
            )
            or reservation["stage"] not in {"idea", "review", "followup"}
            or (role == "reviewer") != (reservation["stage"] == "review")
            or type(reservation["attempt"]) is not int
            or not 1 <= reservation["attempt"] <= 3
            or self._cancelled.is_set()
        ):
            raise ValueError("Finite pilot requires its exact reserved worker attempt")
        with self._policy_lock:
            if self._grant()["enabled"] is not True:
                raise ValueError("Finite paper pilot is paused")
        verifier = self.finite_request_verifier
        if not callable(verifier):
            raise ValueError("Finite pilot requires the existing worker reservation verifier")
        # The worker may acquire policy while holding its registry transaction.
        # Never call that registry hook under this transport's policy mutex.
        verifier(role, packet, profile, reservation, claim=claim)
        if claim:
            self._finite_claimed = True
        if self.finite_test() != authority or self._cancelled.is_set():
            raise ValueError("Finite grant changed during reserved-attempt verification")

    def _dispatch_checkpoint(self, phase: str) -> None:
        if self._finite_dispatch is not None:
            self._verify_finite_dispatch(claim=phase == "before_child")

    def _infer(
        self,
        role: str,
        packet: dict[str, Any],
        profile: dict[str, Any],
        reservation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.instance_preflight(role, packet, profile)
        if not self._request_lock.acquire(blocking=False):
            raise ValueError("Existing paper-pilot request already owns this transport")
        try:
            if self._cancelled.is_set():
                raise ValueError(
                    "Paper-pilot cancellation remains latched; explicit resume required"
                )
            policy = self.policy()
            if policy["enabled"] is not True:
                raise ValueError("Paper-pilot grant is paused")
            current_grant = self._grant()
            if (
                current_grant["format"] == PAPER_PILOT_PATTERN_LEARNING_FORMAT
                and "selection_authority" not in packet
            ):
                raise ValueError("Pattern learning requires its exact current v7 authority")
            if (
                current_grant["format"] == PAPER_PILOT_PATTERN_METHOD_FORMAT
                and "selection_authority" not in packet
            ):
                raise ValueError("Pattern method learning requires its exact current v8 authority")
            if current_grant["format"] == PAPER_PILOT_FINITE_FORMAT:
                if reservation is None:
                    raise ValueError("Finite pilot requires a verified reserved worker attempt")
                self._finite_dispatch = (role, packet, profile, reservation)
                self._finite_claimed = False
                self._verify_finite_dispatch()
            elif reservation is not None:
                raise ValueError("Reserved dispatch requires the explicit finite grant")
            if "selection_authority" in packet and packet["selection_authority"][
                "grant_sha"
            ] != digest(current_grant):
                raise ValueError("Question-selection grant changed before dispatch")
            with self._latency_lock:
                if self._pending_admission is not None and self._pending_admission.get(
                    "grant_sha256"
                ) != digest(current_grant):
                    raise ValueError("Paper-pilot grant changed between admission and dispatch")
                self._guard_log = None
                self._guard_observations = (
                    [deepcopy(self._pending_admission)] if self._pending_admission else []
                )
                self._pending_admission = None
                self._dispatch_grant = current_grant
                self._pilot_active = True
            return super().infer(role, packet, profile)
        finally:
            self._finite_dispatch = None
            self._finite_claimed = False
            with self._latency_lock:
                self._pilot_active = False
                self._guard_log = None
            self._request_lock.release()


def local_role_transport(directory: Path) -> LocalRoles | PeftPaperPilotRoles:
    """Select the existing configured owner; optional unreadiness cannot stop paper startup."""
    policy_path = directory.resolve() / "role-policy.json"
    try:
        if not policy_path.exists():
            return LocalRoles(directory)
        policy = _role_policy(policy_path)
    except (ValueError, OSError):
        return PeftPaperPilotRoles(directory)
    if "format" in policy:
        return PeftPaperPilotRoles(directory)
    return LocalRoles(directory)
