"""Run the native driver with simulated Windows APIs and disposable files only."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SHELL = (
    os.environ.get("QTRADES_POWERSHELL") or shutil.which("powershell.exe") or shutil.which("pwsh")
)
pytestmark = pytest.mark.skipif(not SHELL, reason="PowerShell is unavailable")
ROOT = Path(__file__).resolve().parents[1]

DRIVER = r"""
param([string] $Scripts, [string] $Scenario, [string] $Operation)
$ErrorActionPreference='Stop'
$runtime=Join-Path $PSScriptRoot 'runtime space'
$target=Join-Path $PSScriptRoot 'new release'
New-Item -ItemType Directory -Path (Join-Path $runtime 'data') -Force | Out-Null
New-Item -ItemType Directory -Path $target -Force | Out-Null
$stamp=[DateTime]::UtcNow.AddSeconds(-5)
$global:qtest_code=$runtime
$global:qtest_listening=$Operation -eq 'stop' -or $Operation -eq 'inspect'
$global:qtest_enabled=$global:qtest_listening
$global:qtest_taskState=if ($global:qtest_listening) {'Running'} else {'Disabled'}
if($Scenario -eq 'already_stopped'){
    $global:qtest_listening=$false;$global:qtest_enabled=$false;$global:qtest_taskState='Disabled'
}
$global:calls=[Collections.Generic.List[string]]::new()
$env:SystemRoot=Join-Path $PSScriptRoot 'Windows'
$hostExe=Join-Path $runtime '.venv\Scripts\pythonw.exe'
$paperExe=Join-Path $runtime '.venv\Scripts\python.exe'
$shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
function Quoted($s) { if ($s -match '\s') {'"'+$s+'"'} else {$s} }
$supervisorCommand=(Quoted $shell)+' -NoProfile -NonInteractive -File '
$supervisorCommand+=(Quoted (Join-Path $runtime 'scripts\Run-PaperExperiment.ps1'))
$global:qtest_arguments='"'+(Join-Path $runtime 'scripts\service_host.py')+'" --kind paper'
$global:qtest_execute=$hostExe
$hostRecord=@{host_pid=41;supervisor_pid=42;started_at=$stamp.ToString('o')}
$hostRecord|ConvertTo-Json|Set-Content (Join-Path $runtime 'data\service-host-paper.json')
$pidPath=Join-Path $runtime 'data\server.pid'
[IO.File]::WriteAllText($pidPath,'31')
[IO.File]::SetLastWriteTimeUtc($pidPath,$stamp.AddSeconds(1))
function Get-ScheduledTask {
    if ($Scenario -eq 'foreign_task') {$global:qtest_arguments='--other-application'}
    [pscustomobject]@{TaskName='TradingResearch-Paper-20260927';State=$global:qtest_taskState
        Settings=[pscustomobject]@{Enabled=$global:qtest_enabled};Actions=@([pscustomobject]@{
            Execute=$global:qtest_execute;Arguments=$global:qtest_arguments;WorkingDirectory=$global:qtest_code})}
}
function Export-ScheduledTask {
    '<Task><Settings><Enabled>true</Enabled></Settings><Actions/><Principals><Principal>test-user</Principal></Principals></Task>'
}
function Get-NetTCPConnection {
    if ($global:qtest_listening) {
        $address=if($Scenario -eq 'public_listener'){'0.0.0.0'}else{'127.0.0.1'}
        [pscustomobject]@{LocalAddress=$address;OwningProcess=32}
    }
}
function Get-CimInstance {
    param($ClassName,$Filter)
    if (-not $global:qtest_listening) {return $null}
    $number=[int]($Filter -split '=')[1]
    $exe=$paperExe;$line='"'+$paperExe+'" -m trading serve --experiment'
    $name='python.exe';$parent=1
    if($number -eq 32){$parent=31}
    if($number -eq 41){
        $exe=$hostExe;$name='pythonw.exe';$line='"'+$hostExe+'" '+$global:qtest_arguments
    }
    if($number -eq 42){$exe=$shell;$name='powershell.exe';$parent=41;$line=$supervisorCommand}
    if($Scenario -eq 'foreign_host' -and $number -eq 41){$line+=' --other'}
    if($Scenario -eq 'foreign_worker' -and $number -eq 32){$parent=99}
    [pscustomobject]@{ProcessId=$number;ParentProcessId=$parent;Name=$name;ExecutablePath=$exe;CommandLine=$line;CreationDate=$stamp}
}
function Get-Process {
    param($Id)
    $started=if($Scenario -eq 'reused_handle'){$stamp.AddSeconds(1)}else{$stamp}
    $p=[pscustomobject]@{Id=$Id;Handle=1;StartTime=$started;HasExited=$false}
    $p|Add-Member ScriptMethod Kill {
        $global:calls.Add('kill-'+$this.Id);$this.HasExited=$true;$global:qtest_listening=$false
    }
    $p|Add-Member ScriptMethod WaitForExit {param($timeout) return $true}
    $p|Add-Member ScriptMethod Dispose {}
    return $p
}
function Disable-ScheduledTask {$global:calls.Add('disable');$global:qtest_enabled=$false}
function Stop-ScheduledTask {$global:calls.Add('stop-task');$global:qtest_taskState='Disabled'}
function Enable-ScheduledTask {$global:calls.Add('enable');$global:qtest_enabled=$true}
function Start-ScheduledTask {$global:calls.Add('start-task')}
function New-ScheduledTaskAction {
    param($Execute,$Argument,$WorkingDirectory)
    [pscustomobject]@{Execute=$Execute;Arguments=$Argument;WorkingDirectory=$WorkingDirectory}
}
function Set-ScheduledTask {
    param($TaskName,$TaskPath,$Action)
    $global:calls.Add('configure');$global:qtest_code=$Action.WorkingDirectory
    $global:qtest_execute=$Action.Execute;$global:qtest_arguments=$Action.Arguments
}
$plan=@{runtime_root=$runtime;old_root=$runtime;target_root=$target;id='test-operation';launch=@{code_root=$runtime}}
if($Operation -eq 'configure_previous'){
    $plan.previous=@{action=@{Execute=$hostExe;Arguments=$global:qtest_arguments;WorkingDirectory=$runtime}}
    [xml]$x=Export-ScheduledTask
    foreach($n in @($x.SelectNodes('//Actions | //Enabled'))){[void]$n.ParentNode.RemoveChild($n)}
    $plan.previous.signature=$x.OuterXml
}
if($Scenario -eq 'active_configure'){$global:qtest_enabled=$true}
$request=Join-Path $PSScriptRoot 'request.json'
$plan|ConvertTo-Json -Depth 8|Set-Content $request
# Never contend with the operating machine's supervisor mutex, even on Windows.
$driver=Join-Path $PSScriptRoot 'QTradesNativeUpdate.ps1'
$text=[IO.File]::ReadAllText((Join-Path $Scripts 'QTradesNativeUpdate.ps1'))
$text=$text.Replace('TradingResearchPaper20260927',('QTradesIsolatedTest'+[Guid]::NewGuid().ToString('N')))
[IO.File]::WriteAllText($driver,$text)
Copy-Item (Join-Path $Scripts 'PaperStartupIdentity.ps1') $PSScriptRoot
Copy-Item (Join-Path $Scripts 'PaperProcessOwnership.ps1') $PSScriptRoot
try {
    $output=& $driver -Action $Operation -Request $request | ConvertFrom-Json
    @{ok=$true;calls=@($global:calls.ToArray());output=$output;code=$global:qtest_code} |
        ConvertTo-Json -Depth 10 -Compress
} catch {
    @{ok=$false;calls=@($global:calls.ToArray());error=$_.Exception.Message;
      stack=$_.ScriptStackTrace} | ConvertTo-Json -Depth 10 -Compress
}
"""


def run(tmp_path, scenario="normal", action="stop"):
    driver = tmp_path / "fixture.ps1"
    driver.write_text(DRIVER, encoding="utf-8")
    result = subprocess.run(
        [
            SHELL,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(driver),
            str(ROOT / "scripts"),
            scenario,
            action,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_inspection_never_changes_task_or_processes(tmp_path):
    result = run(tmp_path, action="inspect")
    assert result["ok"], result
    assert result["output"]["owned"] and not result["calls"]


def test_stop_only_retains_and_terminates_verified_handles(tmp_path):
    result = run(tmp_path)
    assert result["ok"], result
    assert result["calls"] == ["disable", "stop-task", "kill-42", "kill-41", "kill-32", "kill-31"]


@pytest.mark.parametrize(
    "scenario",
    ["foreign_task", "public_listener", "foreign_host", "foreign_worker", "reused_handle"],
)
def test_foreign_or_reused_processes_are_preserved_before_any_mutation(tmp_path, scenario):
    result = run(tmp_path, scenario)
    assert not result["ok"] and not result["calls"], result


@pytest.mark.parametrize("action", ["configure_target", "configure_previous"])
def test_configure_preserves_native_task_identity(tmp_path, action):
    result = run(tmp_path, action=action)
    assert result["ok"], result
    assert result["calls"] == ["configure"]


def test_reconfiguration_refuses_an_enabled_task(tmp_path):
    result = run(tmp_path, "active_configure", "configure_target")
    assert not result["ok"] and not result["calls"]


def test_start_only_enables_and_starts_the_selected_task(tmp_path):
    result = run(tmp_path, action="start")
    assert result["ok"], result
    assert result["calls"] == ["enable", "start-task"]


def test_recovery_after_task_already_stopped_does_not_stop_a_nonexistent_instance(tmp_path):
    result = run(tmp_path, "already_stopped", "stop")
    assert result["ok"], result
    assert result["calls"] == ["disable"]
