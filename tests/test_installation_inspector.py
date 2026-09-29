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
    [pscustomobject]@{paper=[pscustomobject]@{
        running=$true;stale=($Scenario -eq 'stale');error=$null
        journal=[pscustomobject]@{balanced=($Scenario -ne 'unbalanced')}
    }}
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
