"""Project real JSON types before Windows PowerShell, without account or service writes."""

import copy
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trading import local_activation as a

ROOT = Path(__file__).resolve().parents[1]
SHELL = (
    os.environ.get("QTRADES_POWERSHELL") or shutil.which("powershell.exe") or shutil.which("pwsh")
)
STATUS = {
    "paper": {
        "enabled": True,
        "running": True,
        "stale": False,
        "error": None,
        "journal": {"balanced": True, "revision": 17},
        "events": [
            {
                "observation": {
                    "raw_update": {"e": "depthUpdate", "E": 1790652291858, "u": 16, "U": 15}
                }
            }
        ],
    }
}


def test_reader_preserves_case_sensitive_evidence_then_projects_only_health(monkeypatch):
    original = copy.deepcopy(STATUS)
    requests = []
    handlers = []

    class Client:
        def open(self, url, timeout):
            requests.append((url, timeout))
            return io.BytesIO(json.dumps(original).encode())

    def opener(*values):
        handlers.extend(values)
        return Client()

    monkeypatch.setattr(a.urllib.request, "build_opener", opener)
    status = a.local_json("status")
    assert status == original and requests == [("http://127.0.0.1:8780/api/status", 5)]
    assert handlers[0].proxies == {} and isinstance(handlers[1], a.NoRedirect)
    projected = a.paper_health_projection(status)
    assert projected == {
        "paper": {
            "enabled": True,
            "running": True,
            "stale": False,
            "error": None,
            "journal": {"balanced": True},
        }
    }
    assert status == original and len(json.dumps(projected)) < 300


@pytest.mark.parametrize("value", [None, "true", 1, [], {"running": True}])
def test_invalid_paper_object_is_not_normalized_to_healthy(value):
    if isinstance(value, dict):
        projected = a.paper_health_projection({"paper": value})["paper"]
        assert projected["enabled"] is None and projected["journal"]["balanced"] is None
        assert "error" not in projected
    else:
        with pytest.raises(a.UpdateError, match="missing or invalid"):
            a.paper_health_projection({"paper": value})


@pytest.mark.parametrize("value", [None, "true", 1, [], {}])
def test_wrong_health_types_stay_unknown(value):
    status = copy.deepcopy(STATUS)
    status["paper"].update(enabled=value, running=value, stale=value, journal={"balanced": value})
    result = a.paper_health_projection(status)["paper"]
    assert all(result[key] is None for key in ("enabled", "running", "stale"))
    assert result["journal"]["balanced"] is None


@pytest.mark.parametrize(
    "error,expected", [(None, None), ("", ""), ("PRIVATE-EXCEPTION", "Reported engine error")]
)
def test_error_text_is_redacted_without_hiding_reported_failure(error, expected):
    status = copy.deepcopy(STATUS)
    status["paper"]["error"] = error
    projected = a.paper_health_projection(status)
    assert projected["paper"]["error"] == expected
    assert "PRIVATE" not in json.dumps(projected)


def test_invalid_error_type_is_unknown_not_no_error():
    for value in (False, 0, ["PRIVATE"], {"PRIVATE": True}):
        status = copy.deepcopy(STATUS)
        status["paper"]["error"] = value
        assert "error" not in a.paper_health_projection(status)["paper"]


@pytest.mark.skipif(not SHELL, reason="PowerShell interpreter unavailable")
def test_full_exchange_json_collides_but_projected_health_parses_in_powershell():
    # Execute the real serializer, not a mock; e/E and u/U occur in stream evidence.
    script = """
$ErrorActionPreference='Stop'
try {
    $value=ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
    @{parsed=$true;paper=$value.paper}|ConvertTo-Json -Depth 8 -Compress
} catch { @{parsed=$false}|ConvertTo-Json -Compress }
"""

    def parse(value):
        result = subprocess.run(
            [SHELL, "-NoProfile", "-NonInteractive", "-Command", script],
            input=json.dumps(value),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    assert parse(STATUS) == {"parsed": False}
    projected = a.paper_health_projection(STATUS)
    assert parse(projected) == {"parsed": True, **projected}


@pytest.mark.parametrize(
    "body,exit_code", [(json.dumps(STATUS), 0), ("{PRIVATE-MALFORMED", 1), ("{}", 1)]
)
def test_actual_probe_entrypoint_uses_projection_and_redacts_failures(body, exit_code):
    # Only the network reader is replaced. Run the actual CLI; no OS or database mutations.
    driver = """
import json, runpy, sys
from trading import local_activation as a
body=sys.stdin.read()
a.local_json=lambda endpoint: json.loads(body)
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", driver, str(ROOT / "scripts/qtrades_health.py")],
        input=body,
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == exit_code, result.stderr
    assert "PRIVATE" not in result.stdout + result.stderr
    projected = json.loads(result.stdout)
    if exit_code == 0:
        assert projected == a.paper_health_projection(STATUS)
    else:
        assert projected == {"health_read_error": "Local status could not be read or parsed"}
