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
from trading.role_worker import ResourceRetestAuthorization, RoleWorker


async def answer_with_deadline(
    worker: RoleWorker,
    task: str,
    transport: Any,
    cancel_at_monotonic: float | None,
    resource_retest_authorization: ResourceRetestAuthorization | None = None,
) -> Any:
    """Use the existing cancellation/retention owner; never kill its parent."""
    if resource_retest_authorization is not None:
        resource_retest_authorization.remaining(cancel_at_monotonic)
    elif cancel_at_monotonic is None:
        return await worker.development_answer(task, transport)
    assert cancel_at_monotonic is not None
    if not math.isfinite(cancel_at_monotonic):
        raise ValueError("Experiment cancellation deadline must be finite")
    remaining = cancel_at_monotonic - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Experiment cancellation deadline expired before dispatch")
    answer = (
        worker.development_answer(
            task,
            transport,
            resource_retest_authorization=resource_retest_authorization,
            cancel_at_monotonic=cancel_at_monotonic,
        )
        if resource_retest_authorization is not None
        else worker.development_answer(task, transport)
    )
    # The retest worker owns its deadline and waits for transport cleanup. Do not
    # send a second timeout cancellation while that cleanup is already running.
    return (
        await answer
        if resource_retest_authorization is not None
        else await asyncio.wait_for(answer, timeout=remaining)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Answer one existing development role question")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--authorized-development-inference", action="store_true")
    parser.add_argument(
        "--resource-repair-retest-authorization",
        type=Path,
        help="Reviewed caller evidence for one resource-repair retest; not a human grant",
    )
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
    authorization = None
    if args.resource_repair_retest_authorization is not None:
        try:
            # Validate the supplied path before resolving any redirected entry.
            authorization_path = regular(args.resource_repair_retest_authorization.absolute())
            with authorization_path.open("rb") as stream:
                raw = stream.read(8193)
            if len(raw) > 8192:
                parser.error("Resource-repair retest authorization exceeds its 8-KiB bound")
            authorization = ResourceRetestAuthorization.model_validate_json(raw)
            authorization.remaining(args.cancel_at_monotonic)
        except (OSError, ValueError):
            parser.error("Resource-repair retest requires valid unexpired bounded caller evidence")
        if authorization.task != args.task:
            parser.error("Resource-repair retest authorization belongs to a different task")
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
                worker,
                args.task,
                PeftDevelopmentRoles(path.parent),
                args.cancel_at_monotonic,
                authorization,
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
