"""Read and project local health only; never start a service or open account storage."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.local_activation import local_json, paper_health_projection  # noqa: E402


def main() -> int:
    try:
        print(json.dumps(paper_health_projection(local_json("status")), allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError):
        # Never send source bodies, credentials or arbitrary exception strings to the shell.
        print('{"health_read_error":"Local status could not be read or parsed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
