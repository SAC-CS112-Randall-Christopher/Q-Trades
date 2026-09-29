"""Declare a minimal role interface before any withheld model evaluation."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root / "docs/research/crypto-agent-eval-v2.json").read_bytes()
corpus = json.loads(source)
corpus["version"] = "crypto-agent-eval-v3"
corpus["source_corpus_sha256"] = hashlib.sha256(source).hexdigest()
corpus["interface_change"] = (
    "Application owns tool routing and immutable training/review parameters. "
    "Scientific decisions and issue expectations are unchanged. "
    "Evidence identifiers are opaque; scenario names are never sent to models."
)
for index, case in enumerate(corpus["cases"], 1):
    evidence_id = f"E{index:04d}"
    case["evidence"][0]["id"] = evidence_id
    case["checks"]["evidence_ids"] = [evidence_id]
    for field in ("tools", "change_primary"):
        del case["checks"][field]
    if case["role"] != "researcher":
        for field in ("feature", "horizon_minutes"):
            del case["checks"][field]
with (root / "docs/research/crypto-agent-eval-v3.json").open("x", encoding="utf-8") as stream:
    json.dump(corpus, stream, indent=2)
    stream.write("\n")
print("Declared v3 interface: same 12 development and 36 still-unseen withheld scenarios")
