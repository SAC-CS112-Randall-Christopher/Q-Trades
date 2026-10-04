"""Preview the approved 400 GB temporary storage successor; --apply requires a stopped writer."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.paper_store import load_dsn  # noqa: E402
from trading.research_storage_expansion import expand_temporary_storage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--temporary-gb", type=int, required=True)
    parser.add_argument("--expected-temporary-gb", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        # Do not let a settings file from another installation guard this root.
        if args.settings.absolute() != (args.directory / "paper-database.json").absolute():
            raise ValueError("The settings and storage plan must belong to the same installation")
        report = expand_temporary_storage(
            args.directory,
            load_dsn(args.settings),
            target_gb=args.temporary_gb,
            expected_gb=args.expected_temporary_gb,
            apply=args.apply,
        )
        print(json.dumps(report))
        return 0
    except RuntimeError as error:
        print(json.dumps({"mode": "refused", "reason": str(error)}))
    except (OSError, ValueError):
        print(json.dumps({"mode": "refused", "reason": "Storage successor validation failed"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
