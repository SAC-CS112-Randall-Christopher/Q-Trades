"""Fixed replay child; no financial connection, provider, credentials or user code."""

import json
import sys
from pathlib import Path
from typing import Any

from trading.execution_replay import MAX_INPUT_BYTES, MAX_RESULT_BYTES, run_replay
from trading.numerical_resources import own_limits
from trading.research_evidence import canonical


def main(input_file: Path, output_file: Path) -> None:
    output: dict[str, Any]
    try:
        if input_file.stat().st_size > MAX_INPUT_BYTES + 8192:
            raise ValueError("Replay input exceeded its frozen budget")
        inputs = json.loads(input_file.read_text(encoding="utf-8"))
        result = run_replay(inputs["records"], inputs["source_files"])
        result.setdefault("resources", {})["child_limits"] = own_limits()
        output = {"result": result, "error": None}
    except (ValueError, KeyError, TypeError, ArithmeticError):
        output = {
            "result": None,
            "error": "Frozen source, causal inputs or baseline outcome could not be reconciled",
        }
    body = canonical(output)
    if len(body.encode()) > MAX_RESULT_BYTES:
        body = canonical(
            {"result": None, "error": "Replay result exceeded its frozen evidence budget"}
        )
    output_file.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
