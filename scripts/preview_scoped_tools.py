"""Isolated CP17 browser preview: synthetic inputs, owned QA database and research subtree."""

import asyncio
import json
import sys
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import uvicorn
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.api import create_app  # noqa: E402
from trading.config import Settings  # noqa: E402
from trading.market import parse_book  # noqa: E402
from trading.paper_engine import account  # noqa: E402
from trading.paper_store import PaperStore, load_dsn  # noqa: E402
from trading.paper_strategy import Bar  # noqa: E402
from trading.research_storage import StoragePlan, save_plan, volume  # noqa: E402
from trading.tiered_runtime import TieredPaperRuntime  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def make_app() -> Any:
    dsn = load_dsn(ROOT / "data/paper-database.json")
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("port") != "55641":
        raise ValueError("Preview requires separately owned QA PostgreSQL port 55641")
    token = uuid.uuid4().hex
    folder = ROOT / "data" / ("cp17-preview-" + token)
    folder.mkdir()
    research = Path("G:/Projects") / ("Q-Trades-Data-qa-cp17-preview-" + token)
    if not research.parent.exists():
        raise OSError("Disposable G: preview target is unavailable; no bulk C: fallback")
    plan = StoragePlan(
        root=str(research),
        volume_identity=volume(research)["identity"],
        temporary_bytes=16 * 1024**2,
        research_bytes=16 * 1024**2,
        scratch_bytes=256 * 1024,
        segment_bytes=64 * 1024,
        free_reserve_bytes=0,
    )
    save_plan(folder, plan)
    schema = "cp17_preview_" + token
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    store = PaperStore(make_conninfo(dsn, options=f"-c search_path={schema}"), owner=True)
    now = time.time()
    store.initialize(now)
    frozen_features = {"close": "100.1234567890123456789", "atr": "2", "note": "Synthetic Δ"}

    def seed(engine: Any) -> None:
        for name, saved in engine.state["accounts"].items():
            saved["last_decision"]["BTCUSD"] = {
                "at": now,
                "bar": 1,
                "version": saved["version"],
                "reason": f"Synthetic {name}: no closed-bar entry",
                "features": frozen_features,
            }
        for _i in range(45):
            engine.emit(
                "trade_closed",
                "breakout-v1",
                {
                    "symbol": "BTCUSD",
                    "opened_at": now - 120,
                    "closed_at": now - 60,
                    "pnl": "-0.13",
                    "fees": "0.10",
                    "cost": "10",
                    "proceeds": "9.87",
                    "reason": "Synthetic read-model receipt; no observed economic result",
                },
            )

    store.transact(now, seed)
    retired = account("breakout-v1", now, "100")
    retired["label"] = "Synthetic retired identity"
    retired["last_decision"]["BTCUSD"] = {
        "at": now - 500,
        "reason": "Synthetic retired decision",
        "features": frozen_features,
    }
    store.transact(
        now,
        lambda e: e.emit(
            "initial_funding",
            "retired-preview",
            {"amount": "100", "currency": "USD"},
            [e.line("USD", "cash", Decimal(100)), e.line("USD", "fake_funding", Decimal(-100))],
        ),
    )
    store.transact(
        now,
        lambda e: e.emit(
            "lab_account_archived",
            "retired-preview",
            {"trial_id": "synthetic-trial", "state": retired},
        ),
    )
    assert store.reconcile()["balanced"]
    runtime = TieredPaperRuntime(store, None, folder / "capture.sqlite3")
    runtime.running, runtime.disk_free = True, 10 * 1024**3
    runtime.instruments["BTCUSD"] = {
        "base": "BTC",
        "quote": "USD",
        "venue_status": "TRADING",
        "spot_allowed": True,
        "minimum_notional": "1",
        "filters": [
            {
                "filterType": "PRICE_FILTER",
                "tickSize": "0.01",
                "minPrice": "0.01",
                "maxPrice": "1000000",
            },
            {
                "filterType": "LOT_SIZE",
                "stepSize": "0.00001",
                "minQty": "0.00001",
                "maxQty": "1000",
            },
        ],
    }
    runtime.stream.plan = {"BTCUSD": 100}
    runtime.stream.trade_tape["BTCUSD"] = deque(maxlen=40)
    runtime.universe.rows = [
        {
            "symbol": "BTCUSD",
            "eligible": True,
            "confirmed": True,
            "reason": "Synthetic verification input",
        }
    ]
    runtime.universe.selected = ["BTCUSD"]
    minute = int(now // 60) * 60000
    runtime.history["BTCUSD"] = [
        Bar(
            minute - (600 - i) * 60000,
            Decimal(100),
            Decimal(102),
            Decimal(99),
            Decimal("100.1234567890123456789"),
            Decimal("5.123456789"),
            minute - (599 - i) * 60000 - 1,
        )
        for i in range(600)
    ]
    app = create_app(
        Settings(), folder / "monitor.sqlite3", ROOT / "apps/web/dist", background=False
    )
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: Any):
        async with original_lifespan(application):
            application.state.paper = runtime

            async def heartbeat() -> None:
                while True:
                    at = time.time()
                    runtime.metadata_at = runtime.universe.scanned_at = at
                    runtime._fallback["BTCUSD"] = {
                        "book": parse_book(
                            {
                                "lastUpdateId": int(at),
                                "bids": [["99.90", "20"]],
                                "asks": [["100.10", "20"]],
                            }
                        ),
                        "observed": at,
                        "received_mono": time.monotonic(),
                        "source": "synthetic-preview",
                        "exchange_event_ms": None,
                    }
                    runtime.state["last_tick"] = at
                    await asyncio.sleep(1)

            task = asyncio.create_task(heartbeat())
            (folder / "identity.json").write_text(
                json.dumps(
                    {
                        "schema": schema,
                        "research_root": str(research),
                        "dataset": "synthetic-cp17-preview",
                        "code": "working-tree",
                        "operating_data_used": False,
                    }
                )
            )
            try:
                yield
            finally:
                task.cancel()
                await runtime.stream.close()
                store.close()
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                admin.close()

    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    uvicorn.run(make_app(), host="127.0.0.1", port=8877, log_level="warning")
