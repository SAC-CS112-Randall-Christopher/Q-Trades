"""Managed code/data handoff, using isolated paths and mocked native process operations."""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL = (
    os.environ.get("QTRADES_POWERSHELL") or shutil.which("powershell.exe") or shutil.which("pwsh")
)


def host_module():
    spec = importlib.util.spec_from_file_location(
        "qtrades_test_host", ROOT / "scripts/service_host.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windowless_host_passes_existing_data_root_as_one_argument(monkeypatch, tmp_path):
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    module = host_module()
    runtime = tmp_path / "existing runtime with spaces"
    args = module.supervisor_command("paper", "CpuElastic", runtime)
    assert args[-2:] == ["-RuntimeRoot", str(runtime)]
    assert str(module.ROOT / "scripts/Run-PaperExperiment.ps1") in args
    assert not runtime.exists()


def test_original_paper_and_model_commands_are_retained(monkeypatch):
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    module = host_module()
    assert "-RuntimeRoot" not in module.supervisor_command("paper", "CpuElastic")
    assert module.supervisor_command("models", "CpuElastic")[-2:] == [
        "-RuntimeProfile",
        "CpuElastic",
    ]


def test_paper_update_cannot_redirect_the_independent_model_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    with pytest.raises(ValueError, match="cannot redirect"):
        host_module().supervisor_command("models", "CpuElastic", tmp_path)


IDENTITY = r"""
param([string] $Scripts)
$ErrorActionPreference = 'Stop'
. (Join-Path $Scripts 'PaperStartupIdentity.ps1')
. (Join-Path $Scripts 'PaperProcessOwnership.ps1')
$code = Join-Path $PSScriptRoot 'code release'
$runtime = Join-Path $PSScriptRoot 'existing runtime'
$other = Join-Path $PSScriptRoot 'wrong runtime'
$exe = Join-Path $code '.venv\Scripts\python.exe'
$hostExe = Join-Path $code '.venv\Scripts\pythonw.exe'
$hostArgs = '"'+(Join-Path $code 'scripts\service_host.py')+'" --kind paper'
$hostArgs += ' --runtime-root "'+$runtime+'"'
$task = [pscustomobject]@{Actions=@([pscustomobject]@{
    Execute=$hostExe;WorkingDirectory=$code;Arguments=$hostArgs
})}
if (-not (Test-PaperStartupAction $task $code $runtime)) { throw 'Managed task rejected' }
if (Test-PaperStartupAction $task $code) { throw 'Managed task mistaken for legacy startup' }
if (Test-PaperStartupAction $task $code $other) { throw 'Wrong data root accepted' }
$start = [DateTime]'2026-09-28T20:00:00Z'
$launcher = [pscustomobject]@{
    ProcessId=7;ExecutablePath=$exe;CreationDate=$start
    CommandLine=('"'+$exe+'" -m trading serve --experiment --runtime-root "'+$runtime+'"')
}
if (-not (Test-PaperLauncherIdentity $launcher $exe $start.AddSeconds(1) $runtime)) {
    throw 'Managed launcher rejected'
}
if (Test-PaperLauncherIdentity $launcher $exe $start.AddSeconds(1) $other) {
    throw 'Wrong launcher runtime accepted'
}
$worker = [pscustomobject]@{
    Name='python.exe';ExecutablePath=$exe;ParentProcessId=7;CreationDate=$start.AddSeconds(0.1)
    CommandLine=$launcher.CommandLine
}
if (-not (Test-PaperWorkerIdentity $worker $launcher $runtime)) { throw 'Owned worker rejected' }
if (Test-PaperWorkerIdentity $worker $launcher $other) { throw 'Foreign data root accepted' }
Write-Output 'Managed identity checks passed'
"""

SUPERVISOR = r"""
param([string] $Scripts)
$ErrorActionPreference = 'Stop'
$code = Join-Path $PSScriptRoot 'code release'
$runtime = Join-Path $PSScriptRoot 'existing runtime'
$target = Join-Path $code 'scripts'
New-Item -ItemType Directory -Path $target -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $code '.venv\Scripts') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $runtime 'data') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $code '.venv\Scripts\python.exe'), 'Never executed')
$sentinel = Join-Path $runtime 'data\retained-test-data'
[IO.File]::WriteAllText($sentinel, 'preserved')
$source = [IO.File]::ReadAllText((Join-Path $Scripts 'Run-PaperExperiment.ps1'))
# Only the mutex name changes: never contend with the operating Windows supervisor.
$testMutex = 'QTradesTest'+[Guid]::NewGuid().ToString('N')
$source = $source.Replace('TradingResearchPaper20260927', $testMutex)
[IO.File]::WriteAllText((Join-Path $target 'Run-PaperExperiment.ps1'), $source)
Copy-Item (Join-Path $Scripts 'PaperProcessOwnership.ps1') $target
$global:qtradesTestCalls = [Collections.Generic.List[object]]::new()
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle,
        [switch] $PassThru, [switch] $Wait, $RedirectStandardOutput, $RedirectStandardError)
    $global:qtradesTestCalls.Add([pscustomobject]@{
        exe=$FilePath;args=$ArgumentList;cwd=$WorkingDirectory
        output=$RedirectStandardOutput;error=$RedirectStandardError
    })
    if ($FilePath -eq 'docker.exe') { return [pscustomobject]@{ExitCode=0} }
    return [pscustomobject]@{Id=222;HasExited=$true}
}
function Get-NetTCPConnection { return }
function Get-CimInstance { return $null }
function Stop-Process { throw 'MUST NOT stop a real process' }
function Start-Sleep { throw 'MOCK_SUPERVISOR_DONE' }
try { & (Join-Path $target 'Run-PaperExperiment.ps1') -RuntimeRoot $runtime }
catch { if ($_.Exception.Message -ne 'MOCK_SUPERVISOR_DONE') { throw } }
if ($global:qtradesTestCalls.Count -ne 2) { throw 'Expected one database and one server command' }
if ($global:qtradesTestCalls[0].cwd -ne $runtime) { throw 'Database was redirected' }
$server = $global:qtradesTestCalls[1]
if ($server.cwd -ne $code) { throw 'Code must run from the release directory' }
$expected = '-m trading serve --experiment --runtime-root "'+$runtime+'"'
if ($server.args -ne $expected) { throw 'Incorrect quoted runtime-root argument' }
if (-not $server.output.StartsWith((Join-Path $runtime 'data'))) { throw 'Logs left runtime data' }
if ([IO.File]::ReadAllText($sentinel) -ne 'preserved') { throw 'Runtime file changed' }
Write-Output 'Managed supervisor handoff passed'
"""


@pytest.mark.skipif(not SHELL, reason="PowerShell interpreter is unavailable")
@pytest.mark.parametrize(
    "driver_text,expected",
    [
        (IDENTITY, "Managed identity checks passed"),
        (SUPERVISOR, "Managed supervisor handoff passed"),
    ],
)
def test_managed_powershell_handoff_with_isolated_os_inputs(tmp_path, driver_text, expected):
    driver = tmp_path / "managed-driver.ps1"
    driver.write_text(driver_text, encoding="utf-8")
    result = subprocess.run(
        [SHELL, "-NoProfile", "-NonInteractive", "-File", str(driver), str(ROOT / "scripts")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout
