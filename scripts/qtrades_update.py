"""Check, prepare, activate or recover a local release. Native changes require --apply."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading.local_updates import MainUpdates  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "activate", "recover"))
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        required=True,
        help="Verified working directory of the actual Windows paper task",
    )
    parser.add_argument(
        "--releases", type=Path, help="Separate local release directory, required for prepare"
    )
    parser.add_argument("--release", type=Path, help="Exact prepared release directory")
    parser.add_argument("--commit", help="Exact main commit selected for activation")
    parser.add_argument(
        "--apply", action="store_true", help="Explicitly apply native activation/recovery"
    )
    args = parser.parse_args()
    if sys.version_info < (3, 12):  # noqa: UP036 - standalone pre-install entry point
        parser.error("Use Python 3.12 or newer for the Q-Trades release environment")
    if not (args.runtime_root / "data").is_dir():
        parser.error("Verified runtime data directory is missing; no new account will be created")
    if args.action == "prepare" and args.releases is None:
        parser.error("--releases is required for prepare")
    try:
        if args.action in {"activate", "recover"}:
            from trading.local_activation import LocalActivation

            native = LocalActivation(args.source, args.runtime_root)
            if args.action == "activate":
                if args.release is None or not args.commit:
                    parser.error("Activation requires --release and --commit")
                result = native.activate(args.release, args.commit, apply=args.apply)
            else:
                result = native.recover(apply=args.apply)
            print(json.dumps(result, indent=2))
            return 0
        if args.apply:
            parser.error("--apply is only valid for activate or recover")
        updater = MainUpdates(args.source, args.runtime_root / "data")
        result = updater.check() if args.action == "check" else updater.prepare(args.releases)
        print(json.dumps(result, indent=2))
        print(
            "No native changes. Review the prepared release before using activate --apply."
        )
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"STOPPED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
