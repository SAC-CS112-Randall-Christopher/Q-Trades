import argparse
import json
from pathlib import Path

import uvicorn

from trading.api import create_app
from trading.config import load_settings
from trading.paper_store import PaperStore, load_dsn
from trading.replay import replay_capture


def main() -> None:
    parser = argparse.ArgumentParser(description="Local paper-only market research monitor")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run public collector and dashboard on loopback")
    serve.add_argument("--config", type=Path, default=Path("configs/paper.toml"))
    serve.add_argument("--database", type=Path, default=Path("data/monitor.sqlite3"))
    serve.add_argument("--port", type=int, default=8780)
    serve.add_argument(
        "--experiment", action="store_true", help="Enable authorized Tier 3 paper loop"
    )
    serve.add_argument("--paper-database", type=Path, default=Path("data/paper-database.json"))
    serve.add_argument(
        "--runtime-root",
        type=Path,
        help="Existing runtime folder; preserve its config, data and research evidence",
    )
    report = commands.add_parser(
        "paper-report", help="Read durable paper results and reconciliation"
    )
    report.add_argument("--paper-database", type=Path, default=Path("data/paper-database.json"))
    replay = commands.add_parser("replay", help="Validate a downloaded public capture offline")
    replay.add_argument("capture", type=Path)
    args = parser.parse_args()
    if args.command == "paper-report":
        store = PaperStore(load_dsn(args.paper_database))
        try:
            state = store.read()
            print(
                json.dumps(
                    {"state": state, "journal": store.reconcile(), "events": store.recent()},
                    indent=2,
                )
            )
        finally:
            store.close()
    elif args.command == "replay":
        if args.capture.stat().st_size > 100_000_000:
            parser.error("Capture exceeds 100 MB")
        result = replay_capture(json.loads(args.capture.read_text(encoding="utf-8")))
        print(json.dumps(result, indent=2))
    else:
        runtime = args.runtime_root.resolve() if args.runtime_root else None
        if runtime:
            if (
                args.config != Path("configs/paper.toml")
                or args.database != Path("data/monitor.sqlite3")
                or args.paper_database != Path("data/paper-database.json")
            ):
                parser.error("Do not combine --runtime-root with individual data/config overrides")
            if not (runtime / "data/monitor.sqlite3").is_file():
                parser.error(
                    "Existing runtime monitor database is missing; refusing a fresh account"
                )
            if args.experiment and not (runtime / "data/paper-database.json").is_file():
                parser.error("Existing paper database configuration is missing")
            args.config = runtime / "configs/paper.toml"
            args.database = runtime / "data/monitor.sqlite3"
            args.paper_database = runtime / "data/paper-database.json"
        if runtime and args.experiment:
            # Read-only preflight: a settings file alone is not evidence of existing history.
            existing = PaperStore(load_dsn(args.paper_database))
            try:
                existing.read()
                if not existing.reconcile()["balanced"]:
                    parser.error("Existing paper history does not reconcile; startup is blocked")
            finally:
                existing.close()
        settings = load_settings(args.config)
        app = create_app(
            settings,
            args.database,
            Path("apps/web/dist"),
            paper_database=args.paper_database if args.experiment else None,
            research_evidence=runtime / "docs/evidence" if runtime else None,
            source_root=Path.cwd(),
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, access_log=False)


if __name__ == "__main__":
    main()
