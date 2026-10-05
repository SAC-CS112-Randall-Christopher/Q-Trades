"""Explicit one-question development dispatch. Does not create or advance paper trials."""

import argparse
import asyncio
import json
from pathlib import Path

from trading.experiment_registry import ExperimentRegistry
from trading.peft_profile import regular
from trading.peft_role_model import PeftDevelopmentRoles
from trading.role_worker import RoleWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Answer one existing development role question")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--authorized-development-inference", action="store_true")
    args = parser.parse_args()
    if not args.authorized_development_inference:
        parser.error("Actual model dispatch requires applicable explicit development authorization")
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
            worker.development_answer(args.task, PeftDevelopmentRoles(path.parent))
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
