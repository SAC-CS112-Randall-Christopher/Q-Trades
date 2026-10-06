"""Explicit one-question development dispatch. Does not create or advance paper trials."""

import argparse
import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

from trading.experiment_registry import ExperimentRegistry
from trading.peft_profile import regular
from trading.peft_role_model import PeftDevelopmentRoles
from trading.role_worker import RoleWorker


async def answer_with_deadline(
    worker: RoleWorker, task: str, transport: Any, cancel_at_monotonic: float | None
) -> Any:
    """Use the existing cancellation/retention owner; never kill its parent."""
    if cancel_at_monotonic is None:
        return await worker.development_answer(task, transport)
    if not math.isfinite(cancel_at_monotonic):
        raise ValueError("Experiment cancellation deadline must be finite")
    remaining = cancel_at_monotonic - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Experiment cancellation deadline expired before dispatch")
    return await asyncio.wait_for(worker.development_answer(task, transport), timeout=remaining)


def main() -> None:
    parser = argparse.ArgumentParser(description="Answer one existing development role question")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--authorized-development-inference", action="store_true")
    parser.add_argument(
        "--cancel-at-monotonic",
        type=float,
        help="Optional same-host experiment deadline; owned cancellation retains the attempt",
    )
    args = parser.parse_args()
    if not args.authorized_development_inference:
        parser.error("Actual model dispatch requires applicable explicit development authorization")
    if args.cancel_at_monotonic is not None and (
        not math.isfinite(args.cancel_at_monotonic) or args.cancel_at_monotonic <= time.monotonic()
    ):
        parser.error("Experiment cancellation deadline must be finite and still in the future")
    path = regular(args.registry.resolve())
    # Require an expressly prepared development directory; never point at the
    # installed registry. The marker also makes the receipt accessible through
    # the development app's normal role detail/history API.
    marker = path.parent / "development-environment.json"
    from trading.peft_profile import read

    declared = read(marker)
    if declared != {"format": "qtrades-owned-development-v1", "registry": str(path)}:
        parser.error("Use the separately declared development registry")
    if (path.parent / "role-policy.json").exists() or not path.is_file():
        parser.error("Development registry must exist with operating role policy absent")
    registry = ExperimentRegistry(path)
    try:
        worker = RoleWorker(registry, None)
        answer = asyncio.run(
            answer_with_deadline(
                worker, args.task, PeftDevelopmentRoles(path.parent), args.cancel_at_monotonic
            )
        )
        print(
            json.dumps(
                {
                    "task": args.task,
                    "answer": answer.model_dump(),
                    "scope": "Development only; question did not advance or create a trial",
                }
            )
        )
    finally:
        registry.close()


if __name__ == "__main__":
    main()
