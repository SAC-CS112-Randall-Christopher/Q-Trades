"""Execute the actual PowerShell inspector with simulated OS inputs, never real services."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SHELL = (
    os.environ.get("QTRADES_POWERSHELL") or shutil.which("powershell.exe") or shutil.which("pwsh")
)
pytestmark = pytest.mark.skipif(not SHELL, reason="PowerShell interpreter is unavailable")

DRIVER = r"""
param([string] $Inspector, [string] $Scenario)
$ErrorActionPreference = 'Stop'
if (-not (Get-PSDrive C -ErrorAction SilentlyContinue)) {
    New-PSDrive -Name C -PSProvider FileSystem -Root $PSScriptRoot | Out-Null
}
$root = 'C:\trading-app'
$stamp = [DateTime]'2026-09-28T20:00:00Z'
$python = Join-Path $root '.venv\Scripts\python.exe'
$global:qtradesTestHttpRequests = 0
function Get-ScheduledTask {
    $command = '"' + (Join-Path $root 'scripts\service_host.py') + '" --kind paper'
    if ($Scenario -eq 'foreign_task') { $command += ' --other-app' }
    [pscustomobject]@{State='Running';Actions=@([pscustomobject]@{
        Execute=(Join-Path $root '.venv\Scripts\pythonw.exe')
        Arguments=$command;WorkingDirectory=$root
    })}
}
function Get-NetTCPConnection {
    if ($Scenario -eq 'no_listener') { return }
    $address = if ($Scenario -eq 'public_listener') { '0.0.0.0' } else { '127.0.0.1' }
    [pscustomobject]@{LocalAddress=$address;OwningProcess=8}
}
function Get-Item { [pscustomobject]@{LastWriteTimeUtc=$stamp.AddSeconds(1)} }
function Get-Content { '7' }
function Get-CimInstance {
    param($ClassName, $Filter)
    if ($Filter -eq 'ProcessId=7') {
        $created = if ($Scenario -eq 'reused_pid') { $stamp.AddSeconds(50) } else { $stamp }
        return [pscustomobject]@{
            ProcessId=7;Name='python.exe';ExecutablePath=$python;CreationDate=$created
            CommandLine=('"'+$python+'" -m trading serve --experiment')
        }
    }
    $parent = if ($Scenario -eq 'foreign_worker') { 99 } else { 7 }
    $executable = Join-Path 'C:\Python' 'python.exe'
    [pscustomobject]@{
        ProcessId=8;ParentProcessId=$parent;Name='python.exe';ExecutablePath=$executable
        CreationDate=$stamp.AddMilliseconds(100)
        CommandLine=('"'+$executable+'" -m trading serve --experiment')
    }
}
function Get-Process { [pscustomobject]@{Id=7} }
function Invoke-RestMethod {
    $global:qtradesTestHttpRequests++
    if ($Scenario -eq 'health_unavailable') { throw 'Synthetic unavailable service' }
    $response = [pscustomobject]@{paper=[pscustomobject]@{
        enabled=$true;running=$true;stale=($Scenario -eq 'stale');error=$null
        journal=[pscustomobject]@{balanced=($Scenario -ne 'unbalanced')}
    }}
    switch ($Scenario) {
        'json_text' { return ($response | ConvertTo-Json -Depth 5 -Compress) }
        'no_paper' { return [pscustomobject]@{detail='Private diagnostic not for output'} }
        'null_body' { return $null }
        'null_paper' { $response.paper=$null }
        'array_paper' { $response.paper=@($response.paper, $response.paper) }
        'malformed_json' { return '{PRIVATE-UNPARSED-BODY' }
        'json_scalar' { return '"PRIVATE-STRING-NOT-A-STATUS-OBJECT"' }
        'missing_running' { $response.paper.PSObject.Properties.Remove('running') }
        'missing_error' { $response.paper.PSObject.Properties.Remove('error') }
        'null_journal' { $response.paper.journal=$null }
        'stopped' { $response.paper.running=$false }
        'engine_error' { $response.paper.error='PRIVATE-ENGINE-ERROR' }
        'string_bools' {
            $response.paper.running='true';$response.paper.stale='false'
            $response.paper.journal.balanced='true';$response.paper.error=@('PRIVATE-ERROR')
        }
        'numeric_bools' {
            $response.paper.running=1;$response.paper.stale=0
            $response.paper.journal.balanced=1;$response.paper.error=0
        }
    }
    return $response
}
function Stop-Process { throw 'MUTATION FORBIDDEN' }
function Stop-ScheduledTask { throw 'MUTATION FORBIDDEN' }
function Start-ScheduledTask { throw 'MUTATION FORBIDDEN' }
function Set-ScheduledTask { throw 'MUTATION FORBIDDEN' }
function Register-ScheduledTask { throw 'MUTATION FORBIDDEN' }
$expected = if ($Scenario -eq 'wrong_expected_root') { 'C:\other' } else { $root }
$result = & $Inspector -ExpectedRuntimeRoot $expected | ConvertFrom-Json
[ordered]@{result=$result;http_requests=$global:qtradesTestHttpRequests} | ConvertTo-Json -Depth 6
"""


def invoke(tmp_path, scenario):
    driver = tmp_path / "inspect-fixture.ps1"
    driver.write_text(DRIVER, encoding="utf-8")
    inspector = Path(__file__).resolve().parents[1] / "scripts/Get-QTradesInstallation.ps1"
    assert SHELL
    return subprocess.run(
        [SHELL, "-NoProfile", "-NonInteractive", "-File", str(driver), str(inspector), scenario],
        capture_output=True,
        text=True,
        timeout=25,
    )


def test_verified_identity_reads_only_health_and_does_not_change_services(tmp_path):
    result = invoke(tmp_path, "healthy")
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["http_requests"] == 1
    assert receipt["result"]["verified_launcher_pid"] == 7
    assert receipt["result"]["current_health"]["paper_running"] is True
    assert receipt["result"]["current_health"]["journal_balanced"] is True


@pytest.mark.parametrize(
    "scenario", ["no_listener", "public_listener", "reused_pid", "foreign_worker"]
)
def test_unverified_listener_never_receives_an_application_request(tmp_path, scenario):
    result = invoke(tmp_path, scenario)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["http_requests"] == 0
    assert receipt["result"]["verified_launcher_pid"] is None
    assert receipt["result"]["current_health"] is None


@pytest.mark.parametrize("scenario", ["foreign_task", "wrong_expected_root"])
def test_wrong_registration_stops_readonly_inspection(tmp_path, scenario):
    result = invoke(tmp_path, scenario)
    assert result.returncode != 0
    assert "MUTATION FORBIDDEN" not in result.stderr


@pytest.mark.parametrize("scenario", ["health_unavailable", "stale", "unbalanced"])
def test_health_failures_remain_visible_without_restart(tmp_path, scenario):
    result = invoke(tmp_path, scenario)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)["result"]
    assert receipt["verified_launcher_pid"] == 7
    if scenario == "health_unavailable":
        assert receipt["health_error"] and receipt["current_health"] is None
    elif scenario == "stale":
        assert receipt["current_health"]["paper_stale"] is True
    else:
        assert receipt["current_health"]["journal_balanced"] is False


def parsed_receipt(tmp_path, scenario):
    result = invoke(tmp_path, scenario)
    assert result.returncode == 0, result.stderr
    assert "PRIVATE-" not in result.stdout + result.stderr
    return json.loads(result.stdout)["result"]


def test_json_text_response_is_parsed_not_reported_as_an_unhealthy_account(tmp_path):
    receipt = parsed_receipt(tmp_path, "json_text")
    health = receipt["current_health"]
    assert health["paper_running"] is True
    assert health["paper_stale"] is False
    assert health["journal_balanced"] is True
    assert health["reported_engine_error"] is False
    assert health["complete"] is True and not receipt["health_error"]


@pytest.mark.parametrize(
    "scenario",
    ["no_paper", "null_body", "null_paper", "array_paper", "malformed_json", "json_scalar"],
)
def test_unusable_status_is_unknown_not_a_false_account_failure(tmp_path, scenario):
    receipt = parsed_receipt(tmp_path, scenario)
    assert receipt["current_health"] is None
    assert receipt["health_error"]


@pytest.mark.parametrize(
    "scenario,unknown",
    [
        ("missing_running", {"paper_running"}),
        ("missing_error", {"reported_engine_error"}),
        ("null_journal", {"journal_balanced"}),
        (
            "string_bools",
            {"paper_running", "paper_stale", "journal_balanced", "reported_engine_error"},
        ),
        (
            "numeric_bools",
            {"paper_running", "paper_stale", "journal_balanced", "reported_engine_error"},
        ),
    ],
)
def test_missing_or_wrong_types_keep_unknown_separate_from_reported_false(
    tmp_path, scenario, unknown
):
    receipt = parsed_receipt(tmp_path, scenario)
    health = receipt["current_health"]
    assert health["complete"] is False and receipt["health_error"]
    assert set(health["unknown_fields"]) == unknown
    assert all(health[key] is None for key in unknown)
    assert health["paper_enabled"] is True


@pytest.mark.parametrize(
    "scenario,key,value",
    [
        ("stopped", "paper_running", False),
        ("stale", "paper_stale", True),
        ("unbalanced", "journal_balanced", False),
        ("engine_error", "reported_engine_error", True),
    ],
)
def test_real_negative_status_is_retained_not_normalized_to_healthy(tmp_path, scenario, key, value):
    receipt = parsed_receipt(tmp_path, scenario)
    assert receipt["current_health"][key] is value
    assert receipt["current_health"]["complete"] is True
    assert receipt["health_error"] is None  # Read succeeded; this is not a health endorsement.
