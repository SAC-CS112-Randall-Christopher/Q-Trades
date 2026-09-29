"""Bounded, explicit paper campaigns using the existing financial writer and journal."""

import hashlib
import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading.execution_profiles import PROFILES, execution
from trading.paper_strategy import VARIANTS

if TYPE_CHECKING:
    from trading.paper_engine import PaperEngine


class AccountSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str = Field(min_length=1, max_length=40)
    starting_cash: Literal["50", "100"]
    strategy: Literal["breakout-v1", "responsive-v1", "selective-v1"]
    execution_profile: str = Field(min_length=1, max_length=80)
    operating_daily_usd: str | None = Field(default=None, pattern=r"^\d{1,4}(\.\d{1,6})?$")

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Use a visible account name")
        return value

    @field_validator("execution_profile")
    @classmethod
    def known_execution(cls, value: str) -> str:
        if value not in PROFILES:
            raise ValueError("Select a supported paper execution profile")
        return value


class CampaignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,64}$")
    name: str = Field(min_length=1, max_length=60)
    accounts: list[AccountSpec] = Field(min_length=10, max_length=10)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return AccountSpec.clean_label(value)

    @field_validator("accounts")
    @classmethod
    def unique_labels(cls, value: list[AccountSpec]) -> list[AccountSpec]:
        if len({a.label.casefold() for a in value}) != len(value):
            raise ValueError("Each campaign account needs a distinct name")
        return value


def create_campaign(engine: "PaperEngine", spec: CampaignSpec) -> dict[str, Any]:
    from trading.paper_engine import HARD_STOP_POLICY, D, account

    payload = spec.model_dump()
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    campaigns = engine.state.setdefault("campaigns", {})
    previous = campaigns.get(spec.request_id)
    if previous:
        if previous["spec_sha256"] != digest:
            raise ValueError("This launch request already names a different configuration")
        return {"status": "already_applied", "campaign": previous}
    if campaigns:
        raise ValueError(
            "This checkpoint supports one ten-account campaign; history cannot be reset"
        )
    members = [f"campaign-{spec.request_id}-{i + 1:02d}" for i in range(10)]
    if any(name in engine.state["accounts"] for name in members):
        raise ValueError("Account identity already exists; no funding was added")
    campaign = {
        "id": spec.request_id,
        "name": spec.name,
        "created_at": engine.now,
        "version": "paper-campaign-v1",
        "spec_sha256": digest,
        "spec": payload,
        "accounts": members,
        "risk_policy": HARD_STOP_POLICY,
        "comparison": "Separate counterfactual accounts; shared prices, no pooled capital",
    }
    campaigns[spec.request_id] = campaign
    engine.emit("campaign_created", "system", deepcopy(campaign))
    for name, config in zip(members, spec.accounts, strict=True):
        a = account(config.strategy, engine.now, config.starting_cash, config.execution_profile)
        a.update(
            campaign_id=spec.request_id,
            label=config.label,
            operating_daily_usd=config.operating_daily_usd,
            symbols=["BTCUSD", "ETHUSD"],
            entries_paused=False,
            control_version=0,
        )
        engine.state["accounts"][name] = a
        amount = D(config.starting_cash)
        engine.emit(
            "campaign_account_funded",
            name,
            {
                **config.model_dump(),
                "campaign_id": spec.request_id,
                "amount": str(amount),
                "risk_policy": HARD_STOP_POLICY,
                "purpose": "Initial hypothetical funding only",
            },
            [engine.line("USD", "cash", amount), engine.line("USD", "fake_funding", -amount)],
        )
    return {"status": "created", "campaign": campaign}


def control_account(
    engine: "PaperEngine",
    name: str,
    action: str,
    expected_version: int,
    frames: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    a = engine.state["accounts"][name]
    command = {"action": action, "expected_version": expected_version}
    if a.get("last_control") == command:
        return {"status": "already_applied", "version": a["control_version"]}
    if a.get("control_version", 0) != expected_version:
        raise ValueError("Account controls changed; refresh before retrying")
    if action == "recover":
        if not a.get("fault"):
            raise ValueError("This account has no processing failure to recover")
        candidate = deepcopy(a)
        execution(candidate)
        if candidate.get("numerical_artifact"):
            from trading.numerical_candidates import validate_artifact

            validate_artifact(candidate["numerical_artifact"])
        elif candidate["version"] not in VARIANTS:
            raise ValueError("Account strategy needs repair before recovery")
        if engine.state.get("campaigns"):
            frames = engine.campaign_frames(frames)
        if not engine.value(candidate, frames):
            raise ValueError("Wait for fresh executable prices for every holding")
        engine.assert_account(candidate)
        candidate.pop("fault", None)
        # Retain funding, risk stops, reservations and the independent operator pause.
        engine.state["accounts"][name] = a = candidate
    elif action in {"pause", "resume"}:
        a["entries_paused"] = action == "pause"
        if action == "pause":
            for symbol, order in list(a["pending"].items()):
                if order["side"] == "buy":
                    engine.cancel(name, a, symbol, "Operator paused this account's entries")
    else:
        raise ValueError("Unknown account control")
    a["control_version"] = expected_version + 1
    a["last_control"] = command
    engine.emit(
        "account_control",
        name,
        {
            **command,
            "version": a["control_version"],
            "note": "Funding, loss limits and global entry pause are unchanged",
        },
    )
    return {"status": "applied", "version": a["control_version"]}
