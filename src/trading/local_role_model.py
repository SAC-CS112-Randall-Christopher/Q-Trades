"""Actual dedicated local-model transport; qualified profiles never confer financial authority."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from trading.experiment_registry import fingerprint
from trading.lab_role_contract import contract_hash, packet_json, prompt, schema
from trading.ownership import CollectorLock
from trading.research_inference import cpu_placement_valid
from trading.research_resources import (
    ELASTIC_CPU_RUNTIME,
    capture_resources,
    elastic_resources_valid,
)

ORIGIN = "http://127.0.0.1:11435"


class LocalRoles:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "role-policy.json"

    def policy(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"enabled": False}
        raw = self.path.read_bytes()
        if len(raw) > 16384:
            raise ValueError("Role policy exceeds its bounded metadata limit")
        value: dict[str, Any] = json.loads(raw)
        if value.get("origin") != ORIGIN or value.get("runtime_profile") != ELASTIC_CPU_RUNTIME:
            raise ValueError("Role policy requires the approved dedicated CPU runtime")
        if value.get("model") not in {"qwen3.5:4b", "qwen3.5:9b", "qwen3:14b"}:
            raise ValueError("Use approved installed weights; this transport never downloads")
        options = value["options"]
        if options.get("num_gpu") != 0 or options.get("num_thread") != 6:
            raise ValueError("Model decoding changes approved CPU placement")
        if not 1 <= value["timeout_seconds"] <= 600 or not 256 <= options["num_ctx"] <= 8192:
            raise ValueError("Model time/context limits differ from supported bounded profiles")
        if not 1 <= options["num_predict"] <= 4096:
            raise ValueError("Model output allowance exceeds the bounded profile")
        if (
            not 1 <= value["hourly_wall_seconds"] <= 1800
            or not 1 <= value["hourly_tokens"] <= 65536
        ):
            raise ValueError("Separate role allowance must be explicitly declared and bounded")
        value["token_allowance"] = options["num_ctx"]
        value["contract_sha256"] = contract_hash()
        return value

    def observe(self, profile: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(trust_env=False, timeout=8) as client:
            version = client.get(ORIGIN + "/api/version")
            version.raise_for_status()
            tags = client.get(ORIGIN + "/api/tags")
            tags.raise_for_status()
            model = next((m for m in tags.json()["models"] if m["name"] == profile["model"]), None)
            if model is None or model["digest"] != profile["model_digest"]:
                raise ValueError("Approved model missing or digest changed; qualification stale")
            show = client.post(ORIGIN + "/api/show", json={"model": profile["model"]})
            show.raise_for_status()
            template = hashlib.sha256(show.json()["template"].encode()).hexdigest()
            if (
                template != profile["template_sha256"]
                or version.json()["version"] != profile["server_version"]
            ):
                raise ValueError("Model template/server version changed; qualification stale")
        resources = capture_resources(
            self.directory / "research-runtime.json", include_worker=False
        )
        if not elastic_resources_valid(resources, include_worker=False):
            raise ValueError(
                "Actual dedicated CPU priority/affinity is outside the approved profile"
            )
        return {"version": version.json(), "template_sha256": template, "resources": resources}

    def paper_guard(self) -> dict[str, Any]:
        with httpx.Client(trust_env=False, timeout=8) as client:
            response = client.get("http://127.0.0.1:8780/api/status")
            response.raise_for_status()
            paper = response.json()["paper"]
        sample = {k: paper.get(k) for k in ("running", "error", "stale", "research_constrained")}
        if (
            sample["running"] is not True
            or sample["error"]
            or sample["stale"] is not False
            or sample["research_constrained"] is not False
        ):
            raise ValueError("Operating paper health/resource guard constrains optional inference")
        return sample

    def qualification(self, role: str, profile: dict[str, Any]) -> None:
        path = self.directory / "role-qualification.json"
        raw = path.read_bytes()
        if (
            len(raw) > 2_000_000
            or hashlib.sha256(raw).hexdigest() != profile["qualification_sha256"]
        ):
            raise ValueError("Role qualification receipt identity changed")
        report = json.loads(raw)
        identity = {
            k: v for k, v in profile.items() if k not in {"enabled", "qualification_sha256"}
        }
        if report["profile_sha256"] != fingerprint(identity):
            raise ValueError("Task-specific model/protocol/decoding qualification is stale")
        rows = [r for r in report["rows"] if r["role"] == role]
        seeds = {92811, 92823, 92837}
        cases = {r["case"] for r in rows}
        if (
            report.get("split") != "holdout"
            or report.get("contract_sha256") != contract_hash()
            or len(cases) != 12
            or {(r["case"], r["seed"]) for r in rows} != {(c, s) for c in cases for s in seeds}
        ):
            raise ValueError("Role qualification does not contain the frozen 36-case population")
        q = {
            "complete": sum(r.get("complete", False) for r in rows),
            "passed": sum(r["passed"] for r in rows),
            "critical": sum(r["critical"] for r in rows),
            "placement_valid": all(r["placement_valid"] for r in rows),
        }
        if q != report["roles"].get(role):
            raise ValueError("Role summary differs from the original attempt receipts")
        if (
            not q
            or q["complete"] != 36
            or q["passed"] < 34
            or q["critical"]
            or not q["placement_valid"]
        ):
            raise ValueError("Required role lacks complete 34/36 task-specific qualification")

    def admit(self, role: str) -> dict[str, Any]:
        profile = self.policy()
        if not profile.get("enabled"):
            raise ValueError("Optional local role policy is disabled")
        self.observe(profile)
        self.qualification(role, profile)
        self.paper_guard()
        return profile

    def readiness(self) -> dict[str, Any]:
        """Report independent prerequisites without loading or activating a model."""
        stages: dict[str, Any] = {
            "policy": {
                "state": "absent",
                "next_action": (
                    "Declare and verify the exact approved model/profile before qualification"
                ),
            },
            "runtime": {
                "state": "unverified",
                "next_action": "Verify the owned dedicated CPU listener and model identity",
            },
            "qualification": {
                "state": "unverified",
                "next_action": (
                    "Complete current independent development and both role qualifications"
                ),
            },
            "activation": {
                "state": "disabled",
                "next_action": "Operating activation requires its separate explicit authorization",
            },
        }
        result: dict[str, Any] = {"qualified": False, "enabled": False, "stages": stages}
        try:
            profile = self.policy()
            if "model" not in profile:
                result["reason"] = "No declared model policy or current contract qualification"
                return result
            stages["policy"]["state"] = "verified"
            stages["activation"]["state"] = "enabled" if profile["enabled"] else "disabled"
            result.update(
                enabled=profile["enabled"],
                model=profile["model"],
                digest=profile["model_digest"],
                profile={k: v for k, v in profile.items() if k != "qualification_sha256"},
            )
            ready: dict[str, Any] = {}
            for role in ("researcher", "reviewer"):
                try:
                    self.qualification(role, profile)
                    ready[role] = {"qualified": True}
                except (ValueError, OSError, KeyError) as exc:
                    ready[role] = {"qualified": False, "reason": str(exc)[:300]}
            result["roles"] = ready
            qualified = all(r["qualified"] for r in ready.values())
            stages["qualification"]["state"] = "qualified" if qualified else "unqualified"
            # A stopped listener must not hide missing or independently valid receipts.
            try:
                result["observed"] = self.observe(profile)
                stages["runtime"]["state"] = "verified"
                result["qualified"] = qualified
            except httpx.HTTPError as exc:
                stages["runtime"]["state"] = "unavailable"
                result["reason"] = str(exc)[:300]
            except (ValueError, OSError, KeyError) as exc:
                stages["runtime"]["state"] = "mismatch"
                result["reason"] = str(exc)[:300]
            return result
        except (httpx.HTTPError, ValueError, OSError, KeyError) as exc:
            stages["policy"]["state"] = "invalid"
            result["reason"] = str(exc)[:300]
            return result

    @staticmethod
    def preflight(role: str, packet: dict[str, Any], profile: dict[str, Any]) -> dict[str, int]:
        """Size the actual system/schema and serialized packet, without runtime access."""
        measured = {
            "system_schema_bytes": len(prompt(role).encode()),
            "packet_bytes": len(packet_json(packet).encode()),
            "output_reserve": profile["options"]["num_predict"],
            "template_reserve": 512,
            "context_allowance": profile["options"]["num_ctx"],
        }
        measured["reserved_total"] = sum(
            measured[k]
            for k in ("system_schema_bytes", "packet_bytes", "output_reserve", "template_reserve")
        )
        # prompt() includes the complete schema; the identical format object
        # constrains output grammar rather than adding another textual prompt.
        if measured["reserved_total"] > measured["context_allowance"]:
            raise ValueError(
                "Packet exceeds conservative context allowance; request bounded evidence"
            )
        return measured

    def infer(self, role: str, packet: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        lock = CollectorLock(self.directory / "research-inference.lock")
        lock.acquire()
        started = time.perf_counter()
        dispatched = False
        try:
            self.preflight(role, packet, profile)
            before = self.observe(profile)
            before["paper_guard"] = self.paper_guard()
            with httpx.Client(trust_env=False, timeout=profile["timeout_seconds"]) as client:
                dispatched = True
                response = client.post(
                    ORIGIN + "/api/generate",
                    json={
                        "model": profile["model"],
                        "system": prompt(role),
                        "prompt": packet_json(packet),
                        "format": schema(role),
                        "think": profile["thinking"],
                        "stream": False,
                        "keep_alive": "60s",
                        "options": profile["options"],
                    },
                )
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError("Model response exceeds the declared transport bound")
                result = response.json()
                if not result.get("done") or result.get("done_reason") != "stop":
                    raise ValueError("Incomplete model answer; no executable proposal inferred")
                after = self.observe(profile)
                resident = client.get(ORIGIN + "/api/ps")
                resident.raise_for_status()
                resources = capture_resources(self.directory / "research-runtime.json")
                placement = {
                    "model_runtime_after": resident.json()["models"],
                    "settings": profile["options"],
                    "resource_state_after": resources,
                }
                if not cpu_placement_valid(
                    placement, profile["model"], profile["model_digest"], ELASTIC_CPU_RUNTIME
                ):
                    raise ValueError(
                        "Actual model digest/GPU/worker priority differs from the profile"
                    )
                return {
                    "answer": json.loads(result["response"]),
                    "profile_sha256": fingerprint(profile),
                    "wall_seconds": time.perf_counter() - started,
                    "before": before,
                    "after": after,
                    "placement": placement,
                    "tokens": {k: result.get(k) for k in ("prompt_eval_count", "eval_count")},
                    "durations_ns": {
                        k: result.get(k)
                        for k in ("load_duration", "prompt_eval_duration", "eval_duration")
                    },
                }
        finally:
            # Only this admitted dedicated server/model; ArcGIS is never called/unloaded.
            try:
                if dispatched:
                    with httpx.Client(trust_env=False, timeout=8) as client:
                        client.post(
                            ORIGIN + "/api/generate",
                            json={"model": profile["model"], "keep_alive": 0},
                        )
            finally:
                lock.release()
