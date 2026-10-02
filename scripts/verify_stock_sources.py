"""One bounded public-source QA investigation; raw sources remain in an owned G: tier."""

import json
import time
import uuid
from pathlib import Path

from trading.experiment_registry import ExperimentRegistry
from trading.research_storage import StoragePlan, save_plan, volume
from trading.stock_research import DEMO, StockQuestion, StockResearch, market_summary

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    directory = ROOT / "data" / "cp21-public"
    directory.mkdir(exist_ok=True)
    if not (directory / "research-storage.json").exists():
        root = Path("G:/Projects") / ("Q-Trades-Data-qa-cp21-" + uuid.uuid4().hex)
        save_plan(directory, StoragePlan(root=str(root), volume_identity=volume(root)["identity"]))
    registry = ExperimentRegistry(directory / "experiments.sqlite")
    started = time.perf_counter()
    receipt = {
        "scope": "Public SEC and official IBM daily example; no accounts/paid services",
        "started": time.time(),
        "data_basis": "Public actual source, not synthetic",
    }
    try:
        research = StockResearch(registry)
        previous = directory / "receipt.json"
        if previous.exists():
            old = json.loads(previous.read_text())
            if "denied/rate-limited" in old.get("blocked", ""):
                with registry.transaction():
                    registry.db.execute(
                        "INSERT OR IGNORE INTO stock_provider_cooldown VALUES('SEC',?,?)",
                        (old["started"] + 600, old["blocked"]),
                    )
        # Provider outage cannot prevent the other declared public research arm.
        try:
            market_source = research.source(DEMO)
            receipt["independent_market"] = market_summary(
                json.loads(market_source["text"]), time.time()
            )
            receipt["independent_market_source"] = {
                k: v for k, v in market_source.items() if k != "text"
            }
        except Exception as exc:
            receipt["market_blocker"] = type(exc).__name__ + ": " + str(exc)[:300]
        study = research.investigate(
            StockQuestion(
                security="0000051143",
                as_of=time.time(),
                market=True,
                hypothesis=(
                    "Compare compatible balance-sheet facts and raw daily prices; "
                    "no causal or total-return inference."
                ),
            )
        )
        (directory / "study-id.txt").write_text(study["id"])
        receipt.update(
            id=study["id"],
            identity=study["identity"],
            facts=study["facts"],
            ratios=study["ratios"],
            timeline=study["timeline"],
            market=study["market"],
            sources=study["sources"],
        )
        try:
            comparison = research.compare_filings(study["id"], "Risk Factors")
            receipt["filing_comparison"] = {
                k: v for k, v in comparison.items() if k not in {"current", "prior"}
            }
            receipt["filing_sources"] = [
                {k: v for k, v in comparison[which].items() if k != "excerpt"}
                for which in ("current", "prior")
            ]
        except Exception as exc:
            receipt["filing_section_blocker"] = type(exc).__name__ + ": " + str(exc)[:300]
        assert research.get(study["id"]) == study
        receipt["reopened_exact_study"] = True
    except Exception as exc:
        receipt["blocked"] = type(exc).__name__ + ": " + str(exc)[:300]
    finally:
        receipt["wall_seconds"] = time.perf_counter() - started
        (directory / ("receipt-" + uuid.uuid4().hex + ".json")).write_text(
            json.dumps(receipt, indent=2)
        )
        print(
            json.dumps(
                {
                    k: v
                    for k, v in receipt.items()
                    if k
                    in {
                        "id",
                        "blocked",
                        "wall_seconds",
                        "reopened_exact_study",
                        "filing_section_blocker",
                        "market",
                        "independent_market",
                        "market_blocker",
                    }
                },
                indent=2,
            )
        )
        registry.close()


if __name__ == "__main__":
    main()
