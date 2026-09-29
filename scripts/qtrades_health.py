"""Read the small loopback health endpoint; no database or task operations."""

import json
import re
import sys
import urllib.request
from typing import Any


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("Health redirect refused")


def healthy(value: dict[str, Any], commit: str) -> bool:
    return (
        value.get("service") == "running"
        and value.get("mode") == "paper"
        and value.get("paper") == "running"
        and value.get("paper_fresh") is True
        and value.get("journal_balanced") is True
        and value.get("paper_error_reported") is False
        and value.get("code_commit") == commit
    )


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"[0-9a-f]{40}", sys.argv[1]):
        print("Exact expected commit required")
        return 1
    try:
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with client.open("http://127.0.0.1:8780/api/health", timeout=3) as response:
            raw = response.read(65_537)
        if len(raw) > 65_536:
            raise ValueError("Oversize health response")
        value = json.loads(raw)
        ready = isinstance(value, dict) and healthy(value, sys.argv[1])
        print(json.dumps({"ready": ready, "expected_commit": sys.argv[1]}))
        return 0 if ready else 2
    except (OSError, ValueError):
        print('{"ready": false, "health": "unavailable"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
