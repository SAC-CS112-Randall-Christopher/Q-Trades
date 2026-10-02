"""Normal browser fixture: two ordinary synthetic generations and actual public IBM study."""

import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from preview_scoped_tools import make_app

from trading.evidence_runtime import EvidenceRecorder
from trading.local_role_model import LocalRoles
from trading.role_worker import Question, RoleWorker
from trading.stock_research import StockQuestion, StockResearch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))


def preview():
    base = time.time() - 8000
    app = make_app(start_at=base)
    prior = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with prior(application):
            from unittest.mock import patch

            import test_autonomous_lab as fixture
            from test_research_lessons import FollowupStub

            runtime = application.state.paper
            folder = runtime.capture_path.parent
            lab = fixture.make_lab(
                runtime.store, folder, now=base, horizon_seconds=3600, hourly_compute_seconds=60
            )
            clock = [base]
            model = FollowupStub()
            worker = RoleWorker(lab.registry, lab, model)
            worker.enabled = True
            with patch("trading.role_worker.time.time", side_effect=lambda: clock[0]):
                lab.paper.state = runtime.store.transact(
                    base,
                    lambda e: e.state.update(evidence_kind="synthetic-cp23-browser-model-stub"),
                )

                async def complete(task):
                    at = clock[0]
                    recorder = EvidenceRecorder(folder / "research-evidence.sqlite")
                    recorder.enqueue({"kind": "wire", "at": at, "source": "synthetic-cp23-browser"})
                    await recorder.flush()
                    for _ in range(5):
                        assert await worker.step(at), worker.get(task["id"])["reason"]
                    trial = None
                    for i in range(1, 31):
                        fixture.tick_lab(lab, at + i * 2)
                        lab.step(at + i * 2)
                        trial = next(
                            (
                                t
                                for t in lab.paper.state["autonomous_lab"]["trials"].values()
                                if t["proposal_id"] == "role-proposal-" + task["id"][5:]
                            ),
                            None,
                        )
                        if trial and trial["status"] == "active":
                            break
                    assert trial and trial["status"] == "active"
                    score = fixture.close_window(lab, trial, "inconclusive")
                    assert await worker.step(score["available_at"] + 1)
                    assert await worker.step(score["available_at"] + 2)
                    clock[0] = score["available_at"] + 3

                first = worker.enqueue(
                    Question(
                        question=(
                            "Synthetic QA: compare two supported mechanisms; "
                            "no qualified model or market value."
                        )
                    ),
                    base,
                )
                await complete(first)
                assert worker.select_followups() == {"selected": 1, "waiting": 0}
                second = worker.get(
                    worker.lessons.retrieve()["lessons"][0]["selection"]["next_task"]
                )
                await complete(second)
                assert worker.select_followups() == {"selected": 0, "waiting": 1}
                assert runtime.store.reconcile()["balanced"]
            runtime.state = lab.paper.state
            application.state.lab.autonomous = lab
            # Restore the actual off/unqualified transport after fixture seeding.
            application.state.lab.roles = RoleWorker(lab.registry, lab, LocalRoles(folder))
            receipt = {
                "first": first["id"],
                "second": second["id"],
                "model": "Synthetic final-answer stub only",
                "outcome": "Accelerated disposable inconclusive paper comparison",
                "processing_location": "Local only",
                "source": "working-tree",
            }
            try:
                study = StockResearch(lab.registry).market_study(
                    StockQuestion(
                        security="IBM",
                        as_of=time.time(),
                        market=True,
                        hypothesis=(
                            "Actual public IBM daily research; no as-seen vintage or execution."
                        ),
                    )
                )
                receipt["actual_public_study"] = study["id"]
            except Exception as exc:
                receipt["public_study_blocker"] = str(exc)[:250]
            (ROOT / "data/cp23-preview-folder.txt").write_text(str(folder))
            (folder / "cp23-fixture.json").write_text(json.dumps(receipt, indent=2))
            try:
                yield
            finally:
                lab.registry.close()

    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    uvicorn.run(preview(), host="127.0.0.1", port=8880, log_level="warning")
