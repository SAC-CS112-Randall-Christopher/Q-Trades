"""Explicit operator compression decision; preview unless --apply is supplied."""

import argparse
import json
import sys
from pathlib import Path

# The updater can preview fetched source before installing its editable package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.paper_projection import METHODS, configure_projection_compression  # noqa: E402
from trading.paper_store import load_dsn  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--compression", choices=METHODS, required=True)
    parser.add_argument("--expected", choices=METHODS, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        report = configure_projection_compression(
            load_dsn(args.settings),
            target=args.compression,
            expected=args.expected,
            apply=args.apply,
        )
        print(json.dumps(report))
        return 0
    except RuntimeError as error:
        # The helper emits fixed reasons; database exceptions are redacted there.
        print(json.dumps({"mode": "refused", "reason": str(error)}))
        return 1
    except (OSError, ValueError):
        print(json.dumps({"mode": "refused", "reason": "Projection compression checks failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
