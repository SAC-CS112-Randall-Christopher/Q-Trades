"""Disposable normal-UI fixture. Synthetic trades only; no venue or installed access."""

import argparse
import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import uvicorn
from fastapi import Request
from fastapi.responses import HTMLResponse
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trading.api import create_app
from trading.config import Settings
from trading.market import parse_book
from trading.paper_store import PaperStore, load_dsn
from trading.paper_strategy import VARIANTS
from trading.tiered_runtime import TieredPaperRuntime

ROOT = Path(__file__).resolve().parents[1]


def market(now: float, sequence: int, price: str = "100") -> dict[str, Any]:
    from decimal import Decimal as D

    raw = {
        "lastUpdateId": sequence,
        "bids": [[price, "100"]],
        "asks": [[str(D(price) + D("0.02")), "100"]],
    }
    return {
        "book": parse_book(raw),
        "raw": raw,
        "observed": now,
        "base": "BTC",
        "source": "synthetic-disposable-qa",
        "received_mono": time.monotonic(),
        "instrument": {"symbol": "BTCUSD"},
        "rules": {
            "step": D("0.00001"),
            "tick": D("0.01"),
            "min_qty": D("0.00001"),
            "max_qty": D(100),
            "min_notional": D(1),
            "min_price": D("0.01"),
            "max_price": D(1000000),
        },
    }


def study(sequence: int) -> dict[str, Any]:
    return {
        "BTCUSD": {
            v: {
                "eligible": True,
                "bar_open_ms": sequence,
                "atr": "1",
                "reason": "Synthetic UI verification",
                "version": v,
            }
            for v in VARIANTS
        }
    }


def serve(port: int) -> None:
    if port != 8798:
        raise ValueError("This fixture is restricted to the dedicated QA port 8798")
    dsn = load_dsn(ROOT / "data/paper-database.json")
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("port") != "55633":
        raise ValueError("Requires the separately owned disposable PostgreSQL cluster")
    directory = ROOT / "data" / ("trade-history-browser-" + uuid.uuid4().hex)
    directory.mkdir()
    app = create_app(
        Settings(),
        directory / "monitor.sqlite3",
        ROOT / "apps/web/dist",
        background=False,
        research_evidence=directory / "evidence",
    )
    original = app.router.lifespan_context
    controls = {"stale": False, "history_error": False}

    @asynccontextmanager
    async def lifespan(app: Any):
        schema = "trade_history_qa_" + uuid.uuid4().hex
        admin = psycopg.connect(dsn, autocommit=True)
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        store = PaperStore(make_conninfo(dsn, options=f"-c search_path={schema}"), owner=True)
        base = time.time() - 13000
        store.initialize(base)
        store.transact(base, lambda e: e.universe_experiment(["BTCUSD", "ETHUSD"]))
        try:
            async with original(app):
                seq = 0

                def tick(at: float, price: str, eligible: bool = False) -> None:
                    nonlocal seq
                    seq += 1
                    store.transact(
                        at,
                        lambda e: e.tick(
                            {"BTCUSD": market(at, seq, price)}, study(seq) if eligible else {}
                        ),
                    )

                for i in range(12):
                    at = base + i * 1000
                    tick(at, "100", True)
                    tick(at + 2, "100")
                    if i % 2:
                        tick(at + 5, "108", True)
                        tick(at + 7, "106", True)
                        tick(at + 9, "106")
                    else:
                        tick(at + 5, "98")
                        tick(at + 7, "98")
                now = time.time()
                tick(now - 2, "100", True)
                tick(now, "100")
                runtime = TieredPaperRuntime(store, None, directory / "capture.sqlite3")
                runtime.running = True
                runtime.stream.plan = {"BTCUSD": 100}
                runtime.instruments = {
                    "BTCUSD": {
                        "base": "BTC",
                        "quote": "USD",
                        "venue_status": "TRADING",
                        "spot_allowed": True,
                        "minimum_notional": "1",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.00001",
                                "maxQty": "100",
                                "stepSize": "0.00001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "1000000",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "1"},
                        ],
                    }
                }
                app.state.paper = runtime

                async def observations() -> None:
                    nonlocal seq
                    while True:
                        seq += 1
                        observed = time.time()
                        runtime.state = store.transact(
                            observed,
                            lambda e, observed=observed, seq=seq: e.tick(
                                {"BTCUSD": market(observed, seq)}, {}
                            ),
                        )
                        runtime._fallback = (
                            {} if controls["stale"] else {"BTCUSD": market(observed, seq)}
                        )
                        await asyncio.sleep(0.5)

                task = asyncio.create_task(observations())
                print("Synthetic disposable trade-history UI ready on QA port 8798", flush=True)
                try:
                    yield
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    # The offline fixture never starts an evidence recorder.
        finally:
            store.close()
            assert schema.startswith("trade_history_qa_") and len(schema) == 49
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            admin.close()

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def labelled_fixture(request: Request, call_next: Any) -> Any:
        if request.url.path == "/api/paper/trades" and controls["history_error"]:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Synthetic retry verification"}, status_code=503)
        if request.url.path == "/":
            source = (ROOT / "apps/web/dist/index.html").read_text()
            return HTMLResponse(
                source.replace(
                    "<body>",
                    '<body><div style="padding:8px;background:#352a1a;color:#f6c76c;'
                    'text-align:center;font:12px sans-serif">'
                    "Synthetic QA · disposable paper trades · no installed data</div>",
                )
            )
        return await call_next(request)

    @app.post("/qa/control")
    async def control(request: Request) -> dict[str, bool]:
        if request.headers.get("X-QA-Fixture") != "1":
            return {"qa_only": True}
        body = await request.json()
        for name in controls:
            if name in body and isinstance(body[name], bool):
                controls[name] = body[name]
        return {"qa_only": True, **controls}

    @app.post("/qa/stop")
    async def stop(request: Request) -> dict[str, bool]:
        if request.headers.get("X-QA-Fixture") == "1":
            server.should_exit = True
        return {"qa_only": True}

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8798)
    serve(parser.parse_args().port)
