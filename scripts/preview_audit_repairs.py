"""Owned native/browser audit fixture; synthetic answers, no network/model acquisition."""

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi.responses import JSONResponse
from preview_scoped_tools import make_app

from trading.local_role_model import LocalRoles
from trading.research_quality import quality_report
from trading.role_worker import Question, RoleWorker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
COMMAND = ROOT / "data/audit-ui-command.json"
RECEIPT = ROOT / "data/audit-ui-receipt.json"
app = make_app(start_at=time.time() - 8000)
prior = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async with prior(application):
        from test_research_acceptance import seed_memory_result

        runtime = application.state.paper
        folder = runtime.capture_path.parent
        clock = [time.time() - 8000]
        with patch("trading.role_worker.time.time", side_effect=lambda: clock[0]):
            worker, task, artifact, lesson = await asyncio.to_thread(
                seed_memory_result, runtime.store, folder, clock
            )
            with patch("trading.role_history.ROLLOVER_BYTES", 0):
                worker.history.rollover()
        assert clock[0] < time.time(), "Synthetic mature fixture must already be available"
        controller = worker.controller
        assert controller is not None
        worker = RoleWorker(controller.registry, controller, LocalRoles(folder))
        application.state.lab.roles = worker
        application.state.lab.autonomous = controller
        runtime.state = controller.paper.state
        application.state.drop_ack = False
        COMMAND.write_text("{}")

        async def controls():
            while True:
                try:
                    command = json.loads(COMMAND.read_text())
                except (ValueError, OSError):
                    command = {}
                if command:
                    COMMAND.write_text("{}")
                if command.get("fill"):
                    for i in range(worker.page()["history"]["active"], 8):
                        worker.enqueue(
                            Question(
                                question=f"Synthetic queue fixture {time.time()} {i}."
                            )
                        )
                if command.get("release"):
                    with worker.registry.lock:
                        row = worker.registry.db.execute(
                            "SELECT id FROM role_tasks "
                            "WHERE status NOT IN ('done','failed') LIMIT 1"
                        ).fetchone()
                    if row:
                        worker._update(
                            worker.get(row[0]),
                            "complete",
                            "done",
                            reason="Synthetic slot released; no inference or financial action",
                        )
                if command.get("drop_ack"):
                    application.state.drop_ack = True
                if command.get("stop"):
                    server.should_exit = True
                with worker.registry.lock:
                    requests = [
                        dict(r) for r in worker.registry.db.execute("SELECT * FROM role_requests")
                    ]
                RECEIPT.write_text(
                    json.dumps(
                        {
                            "folder": str(folder),
                            "memory_task": task["id"],
                            "lesson": lesson,
                            "component_sha256": artifact["sha256"],
                            "questions": worker.page(),
                            "requests": requests,
                            "qualified": False,
                            "enabled": False,
                            "inference_calls": 0,
                            "public_requests": 0,
                            "quality": quality_report(worker),
                            "fixture": "Synthetic memory trial; accelerated inconclusive outcome",
                            "balanced": runtime.store.reconcile()["balanced"],
                        },
                        indent=2,
                    )
                )
                await asyncio.sleep(0.25)

        control = asyncio.create_task(controls())
        try:
            yield
        finally:
            control.cancel()
            controller.registry.close()


app.router.lifespan_context = lifespan


@app.middleware("http")
async def drop_after_save(request, call_next):
    response = await call_next(request)
    if (
        request.url.path == "/api/lab/roles/questions"
        and response.status_code == 200
        and app.state.drop_ack
    ):
        app.state.drop_ack = False
        return JSONResponse(
            {"detail": "Owned fixture lost its saved acknowledgment."}, status_code=503
        )
    return response


if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8882, log_level="warning"))
    server.run()
