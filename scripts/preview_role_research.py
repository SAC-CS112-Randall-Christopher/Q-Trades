"""Disposable CP18 browser QA; synthetic software trace, never a qualified model."""

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from preview_scoped_tools import make_app

from trading import autonomous_finance as finance
from trading.autonomous_lab import AutonomousLab
from trading.autonomous_spec import LabPolicy
from trading.role_worker import Question, RoleWorker

ROOT = Path(__file__).resolve().parents[1]


def preview():
    app = make_app()
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application):
            paper = application.state.paper
            registry = application.state.lab.registry
            now = time.time()

            def setup(engine):
                engine.state["evidence_kind"] = "synthetic-cp18-browser-software-fixture"
                finance.start(
                    engine,
                    LabPolicy(request_id="cp18-browser-software-policy", horizon_seconds=3600),
                )

            paper.state = paper.store.transact(now, setup)
            controller = AutonomousLab(registry, paper, lambda: not paper.constrained())
            application.state.lab.autonomous = controller
            application.state.lab.roles.controller = controller
            # Actual model transport is absent/disabled in this owned fixture.
            # Seed a retained software-orchestration trace with explicit stub output.
            import sys

            sys.path.insert(0, str(ROOT / "tests"))
            from test_role_worker import ModelStub

            fixture_worker = RoleWorker(registry, controller, ModelStub())
            fixture_worker.enabled = True
            await asyncio.sleep(1.1)
            task = fixture_worker.enqueue(
                Question(
                    question="Synthetic QA: reproduce matched rules; no model qualification."
                )
            )
            for _ in range(5):
                await fixture_worker.step()
            await paper.evidence.flush()
            for _ in range(4):
                now = time.time()
                paper.state = paper.store.transact(
                    now, lambda engine: engine.tick(paper.control_frames(), {})
                )
                controller.step(now)
                await asyncio.sleep(0.3)
            await fixture_worker.step()
            (paper.capture_path.parent / "cp18-task.txt").write_text(task["id"])
            yield

    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    uvicorn.run(preview(), host="127.0.0.1", port=8878, log_level="warning")
