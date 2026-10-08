"""Explicit frozen exploratory admissions through the single existing financial writer."""

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from trading.experiment_registry import fingerprint
from trading.numerical_candidates import FAMILIES, validate_artifact

if TYPE_CHECKING:
    from trading.paper_engine import PaperEngine


def admit(
    engine: "PaperEngine",
    experiment: str,
    artifact: dict[str, Any],
    cash: str,
    operating_daily_usd: str | None,
) -> dict[str, Any]:
    from trading.paper_engine import D, account
    from trading.paper_learning import implementation_identity

    validate_artifact(artifact)
    admissions = engine.state.get("challengers", {})
    key = experiment + ":" + artifact["family"]
    if artifact["family"] == "memory_entry":
        key += ":" + artifact["arm"]
    digest = fingerprint(
        {
            "experiment": experiment,
            "artifact": artifact,
            "cash": cash,
            "operating_daily_usd": operating_daily_usd,
        }
    )
    if key in admissions:
        if admissions[key]["spec_sha256"] != digest:
            raise ValueError("The frozen admission already has different funding/cost assumptions")
        return {"status": "already_applied", **admissions[key]}
    implementation = implementation_identity()
    if implementation is None:
        raise ValueError(
            "Execution implementation provenance is unavailable; forward admission waits"
        )
    if len(admissions) >= 4:
        raise ValueError("Four forward admissions retained; preserve history before extending")
    from trading.autonomous_finance import slots

    capacity = slots(engine.state)
    if capacity["used"] + 1 > min(20, capacity["capacity"]):
        raise ValueError("Active paper capacity reached; retained accounts cannot be discarded")
    name = "forward-" + artifact["sha256"][:24]
    if name in engine.state["accounts"]:
        raise ValueError("This artifact already has a forward account")
    a = account("numeric-" + artifact["sha256"][:24], engine.now, cash)
    a.update(
        numerical_artifact=deepcopy(artifact),
        strategy_implementation_sha256=implementation,
        memory_entry_contract=artifact["version"] if artifact["family"] == "memory_entry" else None,
        experiment_id=experiment,
        label=(
            "Historical entry filter"
            if artifact["family"] == "memory_entry"
            else FAMILIES[artifact["family"]]["name"]
        )
        + " · exploratory",
        campaign_id="forward-research",
        symbols=["BTCUSD"],
        benchmark_symbols=["BTCUSD"],
        admitted_at=engine.now,
        operating_daily_usd=operating_daily_usd,
        entries_paused=False,
        control_version=0,
    )
    receipt = {
        "account": name,
        "artifact_sha256": artifact["sha256"],
        "spec_sha256": digest,
        "experiment_id": experiment,
        "at": engine.now,
        "qualification": "Exploratory only; no primary promotion",
        "prior_policy_preserved": True,
    }
    engine.state.setdefault("challengers", {})[key] = receipt
    engine.state["accounts"][name] = a
    engine.emit(
        "forward_account_funded",
        name,
        {**receipt, "amount": cash, "artifact": artifact},
        [engine.line("USD", "cash", D(cash)), engine.line("USD", "fake_funding", -D(cash))],
    )
    return {"status": "created", **receipt}
