"""Selection provenance survives verified archive projection; no model or paper calls."""

import asyncio
import copy
import json

import pytest
from test_paper_pilot_worker import question
from test_paper_pilot_worker import workspace as workspace
from test_research_storage import plan_at

from trading.experiment_registry import fingerprint
from trading.research_storage import save_plan
from trading.role_worker import RoleWorker


@pytest.mark.parametrize("metadata", ["selected", "descendant", "legacy", "legacy_missing_policy"])
def test_explicit_selection_authority_and_provenance_survive_archive(
    workspace, monkeypatch, metadata
):
    worker, clock, directory = workspace
    original_state = copy.deepcopy(worker.controller.paper.state)
    save_plan(directory, plan_at(directory))
    task = worker.enqueue(question("synthetic-selection-history"), clock[0])
    context = copy.deepcopy(task["context"])
    authority = {
        "question_policy": "evidence-question-selection-v1",
        "grant_id": "synthetic-selection-grant",
        "grant_sha": "1" * 64,
        "profile_sha": "2" * 64,
        "contract_version": context["contract"],
        "contract_sha": "3" * 64,
    }
    if metadata == "legacy_missing_policy":
        context.pop("policy_sha256")
    if metadata in {"selected", "descendant"}:
        context["selection_authority"] = authority
    if metadata == "selected":
        context["question_selection"] = {
            "authority": authority,
            "scope_sha": fingerprint(authority),
            "method": "r1",
            "horizon": "short",
            "source_sha": "4" * 64,
            "source_start": clock[0] - 3600,
            "source_end": clock[0] - 60,
            "source_count": 60,
            "strategy_sha": "5" * 64,
            "reference_sha": "6" * 64,
            "lesson_watermark": None,
            "reason": "Synthetic eligible range excursion; not measured strategy benefit.",
            "falsification": "Reject benefit without a matched mature after-cost comparison.",
            "limitations": ["Synthetic fixture only", "No model capacity or financial proof"],
        }
    with worker.registry.transaction():
        worker.registry.db.execute(
            "UPDATE role_tasks SET context=? WHERE id=?", (json.dumps(context), task["id"])
        )
        worker.registry.db.execute(
            "INSERT INTO role_attempts(task,stage,attempt,started,finished,status,profile,"
            "packet,response,wall_reserved,tokens_reserved) "
            "VALUES(?,'idea',1,?,?,'answered','{}','{}',?,5,1024)",
            (task["id"], clock[0], clock[0], json.dumps({"answer": {"action": "no_change"}})),
        )
    worker._update(
        worker.get(task["id"]),
        "complete",
        "done",
        result={"action": "no_change", "rationale": "Retained synthetic terminal response."},
    )
    before = worker.get(task["id"])
    allowance_rows = [
        tuple(row) for row in worker.registry.db.execute("SELECT * FROM role_attempt_allowances")
    ]
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    worker.history.rollover()
    compact = worker.registry.db.execute(
        "SELECT context,archive_reference,archive_sha256 FROM role_tasks WHERE id=?",
        (task["id"],),
    ).fetchone()
    stub = json.loads(compact["context"])
    assert compact["archive_reference"] and compact["archive_sha256"]
    for key in ("policy_sha256", "question_selection", "selection_authority"):
        assert (key in stub) == (key in context)
        if key in context:
            assert stub[key] == context[key]
    reopened = RoleWorker(worker.registry, worker.controller, worker.transport)
    retained = reopened.get(task["id"])
    for key in ("context", "result", "proposal", "evaluation", "attempts"):
        assert retained[key] == before[key]
    assert [
        tuple(row) for row in worker.registry.db.execute("SELECT * FROM role_attempt_allowances")
    ] == allowance_rows
    assert not asyncio.run(reopened.step(clock[0] + 1))
    assert worker.transport.calls == []
    assert worker.controller.paper.state == original_state
