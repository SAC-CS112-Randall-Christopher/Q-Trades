"""Explicit prospective original-account rule changes through the financial owner."""

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading.autonomous_spec import ORIGINALS
from trading.redesign_strategy import STRATEGIES

if TYPE_CHECKING:
    from trading.paper_engine import PaperEngine


class StrategyChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,64}$")
    strategy: str = Field(min_length=1, max_length=80)
    expected_strategy: str = Field(min_length=1, max_length=80)
    expected_control_version: int = Field(ge=0)

    @field_validator("strategy")
    @classmethod
    def reviewed_strategy(cls, value: str) -> str:
        if value not in STRATEGIES:
            raise ValueError("Select one frozen exploratory replacement rule")
        return value


def change_strategy(engine: "PaperEngine", name: str, spec: StrategyChange) -> dict[str, Any]:
    if name not in ORIGINALS:
        raise ValueError(
            "Only original spot baselines can change; lab and campaign contracts stay frozen"
        )
    a = engine.state["accounts"][name]
    if (
        a.get("control_version", 0) != spec.expected_control_version
        or a["version"] != spec.expected_strategy
    ):
        raise ValueError("This account changed; refresh its current rule and control version")
    if a["positions"] or a["pending"]:
        raise ValueError("Wait until this account is flat with no pending orders")
    if a.get("fault") or a.get("execution_uncertain") or not a["valuation_fresh"]:
        raise ValueError(
            "Resolve the account's processing, execution or valuation uncertainty first"
        )
    if a["version"] == spec.strategy:
        raise ValueError("This account already uses the selected replacement rule")
    engine.assert_account(a)
    receipt = {
        **spec.model_dump(),
        "from": a["version"],
        "to": spec.strategy,
        "at": engine.now,
        "version": spec.expected_control_version + 1,
        "baseline": {
            key: deepcopy(a[key])
            for key in ("cash", "funding", "fees", "realized", "closed", "wins")
        },
        "qualification": "Exploratory paper rule; no profitability or promotion claim",
    }
    a["version"] = spec.strategy
    a["control_version"] = receipt["version"]
    a.pop("last_control", None)
    a["last_strategy_change"] = deepcopy(receipt)
    engine.emit("account_strategy_changed", name, receipt)
    return {"status": "applied", "account": name, **receipt}
