"""Bounded product reads over existing owners; no dispatch or evidence-detail access."""

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from trading.experiment_registry import fingerprint


class SupervisedStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    environment: Literal["paper"] = "paper"

    scope_identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    control_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    comparison_revision: int = Field(ge=0)
    resume_comparisons: bool = False


class ModelConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    development_directory: str = Field(min_length=3, max_length=512)


class ModelConfiguration(ModelConnection):
    review_identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    approve_recurring_scope: bool


def preview_configuration(directory: Path, command: ModelConnection) -> dict[str, Any]:
    from trading.peft_role_model import prepare_paper_scope

    prepared = prepare_paper_scope(directory, command.development_directory)
    profile = prepared["profile"]
    return {
        "review_identity": prepared["review_identity"],
        "methods": ["Breakout retest", "Trend pullback"],
        "markets": ["BTCUSD"],
        "model": "qtrades-crypto-researcher-4b-v2",
        "duration": "Recurring until explicitly paused; two fixed comparison methods",
        "concurrency": 1,
        "hourly_tokens": profile["hourly_tokens"],
        "hourly_wall_seconds": profile["hourly_wall_seconds"],
        "timeout_seconds": profile["timeout_seconds"],
        "model_cost_usd": None,
    }


def observation(read: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"available": True, "observed_at": time.time(), "data": read()}
    except (ValueError, OSError, LookupError, RuntimeError, sqlite3.Error, psycopg.Error) as exc:
        return {
            "available": False,
            "observed_at": time.time(),
            "data": None,
            "reason": f"{type(exc).__name__}: current observation unavailable",
        }


def comparison_status(controller: Any) -> dict[str, Any]:
    if controller is None:
        raise ValueError("Paper comparison owner unavailable")
    # This is the same public snapshot owner as /api/autonomous. No bundle,
    # task.view(), lesson retrieval or protected outcome disclosure is performed.
    saved = controller.snapshot()
    lab = saved.get("lab")
    return {
        "configured": lab is not None,
        "policy": lab["policy"] if lab else None,
        "policy_identity": fingerprint(lab["policy"]) if lab else None,
        "control_revision": lab.get("control_revision", 0) if lab else None,
        "proposals_paused": lab["proposals_paused"] if lab else None,
        "entries_paused": lab["entries_paused"] if lab else None,
        "phase": lab.get("phase") if lab else None,
        "reason": lab.get("reason") if lab else None,
        "next_check_at": lab.get("next_action_at") if lab else None,
        "last_score_at": lab.get("last_score_at") if lab else None,
        "slots": saved["slots"],
        "last_error": saved.get("last_error"),
    }


def scanner_status(scanner: Any) -> dict[str, Any]:
    if scanner is None:
        raise ValueError("Market analysis owner unavailable")
    saved = scanner.snapshot()
    campaign = saved.get("campaign") or {}
    return {
        key: saved.get(key)
        for key in (
            "enabled",
            "status",
            "reason",
            "current_campaign_id",
            "progress_counts",
            "progress_total",
            "progress_omitted",
            "daily_selection",
        )
    } | {"symbols": campaign.get("symbols", []), "timeframes": campaign.get("timeframes", [])}


def scope_status(roles: Any) -> dict[str, Any]:
    transport = roles.transport if roles else None
    read = getattr(transport, "reviewed_scope", None)
    if callable(read):
        return dict(read()) | {"requires_restart": False}
    if roles is not None:
        from trading.peft_role_model import PeftPaperPilotRoles

        path = roles.registry.path.parent
        if (path / "role-policy.json").is_file():
            return PeftPaperPilotRoles(path).reviewed_scope() | {"requires_restart": True}
    raise ValueError("An explicit approved automatic paper-research scope is required")


def research_status(roles: Any) -> dict[str, Any]:
    if roles is None:
        return _missing()
    saved = roles.page()
    # Status needs selection metadata, never its possibly large original
    # evidence/learning packet. Those sources retain their exact detail reads.
    selection = saved["question_selection"]
    return {
        key: saved[key]
        for key in (
            "enabled",
            "paper_pilot",
            "execution_mode",
            "current_task",
            "activity",
            "contract",
            "tasks",
            "history",
            "supervision",
            "readiness",
        )
    } | {
        "active_tasks": saved.get("active_tasks", []),
        "question_selection": {
            key: selection.get(key)
            for key in (
                "state",
                "reason",
                "policy",
                "task",
                "retry_at",
            )
        }
    }


def snapshot(lab: Any, scanner: Any) -> dict[str, Any]:
    roles = lab.roles if lab else None
    notices = lab.notices if lab else None
    return {
        "queried_at": time.time(),
        "environment": "paper",
        "research": observation(lambda: research_status(roles)),
        "scope": observation(lambda: scope_status(roles)),
        "comparisons": observation(lambda: comparison_status(lab.autonomous if lab else None)),
        "markets": observation(lambda: scanner_status(scanner)),
        "attention": observation(
            lambda: (
                dict(notices.snapshot(time.time())) | {"detector_error": lab.notice_error}
                if notices
                else _missing()
            )
        ),
    }


def _missing() -> dict[str, Any]:
    raise ValueError("Existing owner unavailable")


def start(lab: Any, command: SupervisedStart) -> dict[str, Any]:
    if lab is None or lab.roles is None or lab.autonomous is None:
        raise ValueError("Configure the existing model and paper comparison owners first")
    scope = scope_status(lab.roles)
    comparisons = comparison_status(lab.autonomous)
    if scope["identity"] != command.scope_identity:
        raise ValueError("Approved research scope changed; review its saved settings again")
    if not scope["automatic_questions"]:
        raise ValueError("This grant requires manual questions; approve an automatic scope first")
    if scope["requires_restart"]:
        raise ValueError(
            "Restart the application to load the saved model connection, then reopen setup"
        )
    if scope["start_refusal"]:
        raise ValueError(scope["start_refusal"])
    if not scope["configured_enabled"] and scope["control_revision"] != command.control_revision:
        raise ValueError("A newer research control is saved; review it before startup")
    if comparisons["policy_identity"] != command.policy_identity:
        raise ValueError("Saved paper comparison policy changed or is not configured")
    if comparisons["proposals_paused"] and not command.resume_comparisons:
        raise ValueError("The saved comparison policy is paused; explicitly review its resumption")
    results = []
    if command.resume_comparisons and comparisons["proposals_paused"]:
        try:
            lab.autonomous.control(
                "resume_proposals",
                None,
                expected_policy_identity=command.policy_identity,
                expected_control_revision=command.comparison_revision,
            )
            results.append({"component": "comparisons", "state": "saved"})
        except (ValueError, OSError, RuntimeError) as exc:
            return {
                "components": [
                    {
                        "component": "comparisons",
                        "state": "rejected" if isinstance(exc, ValueError) else "unconfirmed",
                        "reason": str(exc)[:500],
                    }
                ]
            }
    try:
        lab.roles.transport.start_reviewed_scope(command.scope_identity, command.control_revision)
        results.append({"component": "model_research", "state": "saved"})
    except (ValueError, OSError, RuntimeError) as exc:
        results.append(
            {
                "component": "model_research",
                "state": "rejected" if isinstance(exc, ValueError) else "unconfirmed",
                "reason": str(exc)[:500],
            }
        )
    # Absolute controls reconcile through saved owner state after partial failure.
    # No new policy, grant, question, model attempt, account or scheduler is created.
    return {"components": results}
