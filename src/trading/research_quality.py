"""Recorded software activity and explicit unmeasured matched research value."""

from typing import Any

from trading.role_worker import RoleWorker


def quality_report(worker: RoleWorker) -> dict[str, Any]:
    with worker.registry.lock:
        counts = {
            r["status"]: r["n"]
            for r in worker.registry.db.execute(
                "SELECT status,count(*) AS n FROM role_tasks GROUP BY status"
            )
        }
        attempts = worker.registry.db.execute(
            "SELECT count(*) AS n,"
            "sum(CASE WHEN actor IS NOT NULL "
            "THEN 1 ELSE 0 END) AS external,"
            "sum(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,"
            "sum(CASE WHEN input_tokens IS NOT NULL AND output_tokens IS NOT NULL "
            "THEN 1 ELSE 0 END) AS measured,"
            "sum(input_tokens) AS input_tokens,sum(output_tokens) AS output_tokens,"
            "sum(measured_wall_seconds) AS measured_wall_seconds,"
            "sum(CASE WHEN status IS NULL THEN 1 ELSE 0 END) AS unknown_status "
            "FROM role_attempt_usage"
        ).fetchone()
    native_tokens = {
        "attempts_with_counts": attempts["measured"] or 0,
        "input_tokens": attempts["input_tokens"],
        "output_tokens": attempts["output_tokens"],
        "unknown_attempts": attempts["n"] - (attempts["measured"] or 0),
        "measured_wall_seconds": attempts["measured_wall_seconds"],
        "basis": (
            "Recorded endpoint counts only; absent counts remain unknown, "
            "failed reservations retained"
        ),
    }
    return {
        "assessment": "Insufficient matched qualified-role observation",
        "activity": counts,
        "attempts": attempts["n"],
        "failed_attempts": attempts["failed"] or 0,
        "unknown_status_attempts": attempts["unknown_status"] or 0,
        "external_attempts": attempts["external"] or 0,
        "native_usage": native_tokens,
        "allowance": worker.selection_metrics(),
        "matched_research_arms": [
            {
                "arm": arm,
                "method": method,
                "useful_completions": None,
                "defect_detection": None,
                "false_rejection": None,
                "evidence_correctness": None,
                "quality_per_budget": None,
                "reason": "No frozen matched cohort with qualified eligible role evidence",
            }
            for arm, method in (
                ("A", "Existing deterministic generator"),
                ("B", "Qualified researcher plus required review"),
                ("C", "Same qualified roles plus supported lesson retrieval"),
                ("D", "Optional extra skeptic; unconfigured and disabled"),
            )
        ],
        "economic_value": {
            "supported": False,
            "subsequent_matched_windows": None,
            "net_benefit": None,
            "independent_support": None,
            "hardware_dollars": None,
            "reason": (
                "Software/stub activity is not prospective matched whole-account economic evidence"
            ),
        },
        "recommendation": (
            "Keep optional model/external activation off pending current qualification, "
            "host allowance and an authorized matched study. Retain deterministic research/tools."
        ),
        "selection_warning": (
            "All attempts/search variants remain recorded. Correlated siblings and retrospective "
            "LLM knowledge are not fresh independent confirmation. "
            "Required review stays in every arm."
        ),
    }
