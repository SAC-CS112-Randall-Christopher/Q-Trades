"""Real PowerShell helpers with disposable files and mocked OS/service operations."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from trading.ownership import CollectorLock

ROOT = Path(__file__).resolve().parents[1]
SHELL = os.environ.get("QTRADES_POWERSHELL") or shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows task ownership")

DRIVER = r"""param([string]$Mode,[string]$Scenario,[string]$Profile,[switch]$RecoverMissingHost)
$ErrorActionPreference='Stop'
# The real ScheduledTasks/CimCmdlets modules must never be loaded by this fixture.
Import-Module Microsoft.PowerShell.Management
Import-Module Microsoft.PowerShell.Utility
$PSModuleAutoLoadingPreference='None'
$testRoot=$PSScriptRoot
$global:operations=New-Object 'System.Collections.Generic.List[string]'
$global:taskRunning=$false
$global:taskStopped=$false
function Get-ScheduledTask {
    $name=if($Scenario -in @('legacy','legacy_busy','legacy_listener')){
        'service_host.py'
    }else{'service_host_v2.py'}
    $command='"'+(Join-Path $testRoot ('scripts\'+$name))+'" --kind models --runtime-profile '+
        $Profile
    if($Scenario -eq 'recovery_profile_mismatch'){
        $command=$command.Replace('CpuTwoProcessors','CpuElastic')
    }
    $exe=Join-Path $testRoot '.venv\Scripts\pythonw.exe'
    $directory=$testRoot
    if($Scenario -eq 'foreign_root'){$directory+='-other'}
    if($Scenario -eq 'foreign_executable'){$exe='C:\foreign\pythonw.exe'}
    if($Scenario -eq 'paper_kind'){$command=$command.Replace('--kind models','--kind paper')}
    if($Scenario -eq 'extra_arguments'){$command+=' --other-project'}
    if($Scenario -eq 'wrong_profile'){$command=$command.Replace($Profile,'Gpu')}
    $actions=@([pscustomobject]@{Execute=$exe;Arguments=$command;WorkingDirectory=$directory})
    if($Scenario -eq 'multiple_actions'){$actions+= $actions[0]}
    $state=if($global:taskRunning -or $Scenario -in @('legacy_busy','modern_busy')){
        'Running'
    }else{'Ready'}
    [pscustomobject]@{TaskName='TradingResearch-Models-20260928';State=$state;Actions=$actions;
        Triggers=@([pscustomobject]@{Original=$true});
        Principal=[pscustomobject]@{UserId='fixture-original-principal';LogonType='Interactive';RunLevel='Limited'}}
}
function Get-NetTCPConnection {
    if($Scenario -in @('legacy_listener','modern_listener','listener_remains')){
        [pscustomobject]@{LocalPort=11435}
    }
}
function New-ScheduledTaskAction {
    param($Execute,$Argument,$WorkingDirectory)
    if(-not $Argument.EndsWith(' --kind models --runtime-profile '+$Profile)){
        throw 'Wrong fixture action'
    }
    [pscustomobject]@{Execute=$Execute;Arguments=$Argument;WorkingDirectory=$WorkingDirectory}
}
function New-ScheduledTaskTrigger {[pscustomobject]@{Fixture=$true}}
function New-ScheduledTaskPrincipal {
    param($UserId,$LogonType,$RunLevel)
    if($RunLevel -ne 'Limited'){throw 'Do not elevate'}
    [pscustomobject]@{Fixture=$true}
}
function New-ScheduledTaskSettingsSet {[pscustomobject]@{Fixture=$true}}
function Register-ScheduledTask {
    param($TaskName,$Action,$Principal,$Trigger)
    if($TaskName -ne 'TradingResearch-Models-20260928'){throw 'Wrong task'}
    if($Principal.UserId -ne 'fixture-original-principal'){throw 'Original principal lost'}
    if(-not $Trigger[0].Original){throw 'Original trigger lost'}
    if($Scenario -eq 'admission_at_registration'){
        $probe=[IO.File]::Open((Join-Path $testRoot 'data\research-inference.lock'),
            [IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
        try {
            try {$probe.Lock(0,1);throw 'New research could enter during task mutation'}
            catch [IO.IOException] {$global:operations.Add('admission_blocked')}
        } finally {$probe.Dispose()}
    }
    $global:operations.Add('register:'+($Action.Arguments))
}
function Start-ScheduledTask {
    param($TaskName)
    if($TaskName -ne 'TradingResearch-Models-20260928'){throw 'Wrong task'}
    $global:operations.Add('start');$global:taskRunning=$true
}
function Stop-ScheduledTask {
    param($TaskName)
    if($TaskName -ne 'TradingResearch-Models-20260928'){throw 'Wrong task'}
    $global:operations.Add('stop');$global:taskRunning=$false
    $global:taskStopped=$true
}
function Get-CimInstance {
    param($ClassName,$Filter)
    if(-not $Filter){
        if($Scenario -eq 'active_job'){
            [pscustomobject]@{
                Name='pythonw.exe';CommandLine='pythonw scripts.run_qualification_queue'
            }
        }
    }elseif($Filter.StartsWith('ProcessId=') -and
            $Scenario -in @('resident','reused_pid','owned_server','late_server_reuse',
                'late_child_reuse','late_both_reuse','late_exit_at_kill','foreign_server_path',
                'foreign_server_parent','foreign_child','child_reused_before_pin','partial_shutdown')){
        $exe=if($Scenario -eq 'foreign_server_path'){'C:\foreign\ollama.exe'}
            else{'C:\fixture\ollama.exe'}
        $parent=if($Scenario -eq 'foreign_server_parent'){3000}else{2000}
        [pscustomobject]@{ExecutablePath=$exe;ParentProcessId=$parent;ProcessId=1000;
            CreationDate=[datetime]'2026-09-28T14:24:00Z'}
    }elseif($Filter.StartsWith('ParentProcessId=') -and
            $Scenario -in @('late_child_reuse','late_both_reuse','foreign_child',
                'child_reused_before_pin','partial_shutdown')){
        $exe=if($Scenario -eq 'foreign_child'){'C:\foreign\worker.exe'}
            else{'C:\fixture\lib\ollama\llama-server.exe'}
        [pscustomobject]@{ExecutablePath=$exe;
            ParentProcessId=1000;ProcessId=1001;CreationDate=[datetime]'2026-09-28T14:25:00Z'}
    }
}
function Get-Process {
    param($Id)
    $start=[datetime]'2026-09-28T14:24:00Z'
    if($Id -eq 1001){$start=$start.AddMinutes(1)}
    if($Scenario -eq 'reused_pid'){$start=$start.AddMinutes(1)}
    if($Scenario -eq 'child_reused_before_pin' -and $Id -eq 1001){$start=$start.AddMinutes(1)}
    $process=[pscustomobject]@{Id=$Id;StartTime=$start;Handle=($Id+10000)}
    $process | Add-Member -MemberType ScriptProperty -Name HasExited -Value {
        $global:taskStopped -and (
            $Scenario -eq 'late_both_reuse' -or
            $Scenario -eq 'late_server_reuse' -and $this.Id -eq 1000 -or
            $Scenario -eq 'late_child_reuse' -and $this.Id -eq 1001)
    }
    $process | Add-Member -MemberType ScriptMethod -Name Kill -Value {
        if($Scenario -eq 'late_exit_at_kill'){
            $global:operations.Add('pinned_original_exit_at_kill')
            return
        }
        if($Scenario -eq 'partial_shutdown' -and $this.Id -eq 1000){
            throw 'Owned server stop failed'
        }
        $global:operations.Add('stop_process:'+$this.Id)
    }
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {return $true}
    $process | Add-Member -MemberType ScriptMethod -Name Dispose -Value {}
    $process
}
function Invoke-RestMethod {
    if($Scenario -eq 'resident'){
        [pscustomobject]@{models=@([pscustomobject]@{name='protected model'})}
    }
    else{[pscustomobject]@{models=@()}}
}
function Stop-Process {
    param($Id)
    if($global:taskStopped -and $Scenario -like 'late_*'){
        $global:operations.Add('replacement_killed:'+$Id)
        return
    }
    if($Scenario -ne 'owned_server' -or $Id -ne 1000){throw 'Unexpected process stop'}
    $global:operations.Add('stop_process:1000')
}
$errorText=$null
try {
    if($Mode -eq 'install'){
        $null=& (Join-Path $testRoot 'scripts\Install-ResearchRuntime.ps1') `
            -RuntimeProfile $Profile -RecoverMissingHost:$RecoverMissingHost
    }
    else{$null=& (Join-Path $testRoot 'scripts\Stop-ResearchRuntime.ps1')}
}catch{$errorText=$_.Exception.Message}
$retainedState=Get-Content -LiteralPath (Join-Path $testRoot 'data\research-runtime.json') -Raw |
    ConvertFrom-Json
[pscustomobject]@{
    operations=@($global:operations);error=$errorText;state=$retainedState.state
} | ConvertTo-Json -Compress
"""


def run_helper(
    tmp_path,
    mode,
    scenario="modern",
    modern_available=True,
    legacy_available=True,
    profile="CpuElastic",
    recover_missing=False,
):
    assert SHELL
    root = tmp_path / "model workspace"
    for directory in ("scripts", "data", ".venv/Scripts"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name in (
        "Install-ResearchRuntime.ps1",
        "Stop-ResearchRuntime.ps1",
        "ResearchRuntimeOwnership.ps1",
    ):
        shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
    (root / ".venv/Scripts/pythonw.exe").write_text("Never executed", encoding="utf-8")
    if legacy_available:
        (root / "scripts/service_host.py").write_text("Never executed", encoding="utf-8")
    if modern_available:
        (root / "scripts/service_host_v2.py").write_text("Never executed", encoding="utf-8")
    state = {
        "state": "failed",
        "origin": "http://127.0.0.1:11435",
        "server_pid": 1000,
        "supervisor_pid": 2000,
        "executable": r"C:\fixture\ollama.exe",
        "server_started_at": "2026-09-28T14:24:00Z",
        "updated_at": "2026-09-28T14:24:00Z",
    }
    state_file = root / "data/research-runtime.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    driver = root / "driver.ps1"
    driver.write_text(DRIVER, encoding="utf-8")
    command = [
        SHELL,
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(driver),
        mode,
        scenario,
        profile,
    ]
    if recover_missing:
        command.append("-RecoverMissingHost")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), json.loads(state_file.read_text(encoding="utf-8"))


@pytest.mark.parametrize("profile", ["CpuElastic", "CpuTwoProcessors"])
def test_existing_modern_task_starts_without_rewriting_or_downgrading(tmp_path, profile):
    result, state = run_helper(tmp_path, "install", profile=profile)
    assert result["error"] is None and result["operations"] == ["start"]
    assert state["state"] == "failed"  # Starting a task is not proof of a ready runtime.


@pytest.mark.parametrize("profile", ["CpuElastic", "CpuTwoProcessors"])
def test_existing_modern_task_stops_only_owned_task_and_retains_previous_receipt(tmp_path, profile):
    result, state = run_helper(tmp_path, "stop", profile=profile)
    assert result["error"] is None and result["operations"] == ["stop"]
    assert state["state"] == "stopped"
    previous = tmp_path / "model workspace/data/research-runtime.json.previous"
    assert json.loads(previous.read_text())["state"] == "failed"


@pytest.mark.parametrize("mode", ["install", "stop"])
@pytest.mark.parametrize(
    "scenario",
    [
        "foreign_root",
        "foreign_executable",
        "paper_kind",
        "extra_arguments",
        "wrong_profile",
        "multiple_actions",
    ],
)
def test_other_actions_are_rejected_before_service_or_process_mutation(tmp_path, mode, scenario):
    result, state = run_helper(tmp_path, mode, scenario)
    assert result["error"] and not result["operations"]
    assert state["state"] == "failed"


@pytest.mark.parametrize("scenario", ["active_job", "resident", "reused_pid"])
def test_stop_retains_active_work_and_rejects_reused_server_identity(tmp_path, scenario):
    result, state = run_helper(tmp_path, "stop", scenario)
    assert result["error"] and not result["operations"]
    assert state["state"] == "failed"


def test_stop_empty_verified_server_targets_only_its_original_pid(tmp_path):
    result, state = run_helper(tmp_path, "stop", "owned_server")
    assert result["error"] is None and result["operations"] == ["stop", "stop_process:1000"]
    assert state["state"] == "stopped"


@pytest.mark.parametrize("scenario", ["late_server_reuse", "late_child_reuse", "late_both_reuse"])
def test_stop_never_targets_replacement_lifetimes_after_task_stop(tmp_path, scenario):
    result, _ = run_helper(tmp_path, "stop", scenario)
    assert not any(op.startswith("replacement_killed:") for op in result["operations"]), result


def test_live_listener_prevents_false_stopped_receipt(tmp_path):
    result, state = run_helper(tmp_path, "stop", "listener_remains")
    assert "listener remains" in result["error"] and state["state"] == "failed"


@pytest.mark.parametrize("scenario", ["legacy_busy", "legacy_listener"])
def test_legacy_migration_refuses_active_task_or_listener(tmp_path, scenario):
    result, state = run_helper(tmp_path, "install", scenario)
    assert result["error"] and not result["operations"]
    assert state["state"] == "failed"


def test_legacy_idle_task_uses_available_modern_host_and_still_stops(tmp_path):
    result, _ = run_helper(tmp_path, "install", "legacy")
    assert result["error"] is None and len(result["operations"]) == 2
    assert "service_host_v2.py" in result["operations"][0]
    assert result["operations"][1] == "start"
    stop, state = run_helper(tmp_path / "stop", "stop", "legacy")
    assert stop["error"] is None and stop["operations"] == ["stop"]
    assert state["state"] == "stopped"


def test_legacy_install_without_modern_host_retains_supported_legacy_action(tmp_path):
    result, _ = run_helper(tmp_path, "install", "legacy", modern_available=False)
    assert result["error"] is None and result["operations"] == ["start"]


def test_current_task_missing_its_host_is_preserved_instead_of_downgraded(tmp_path):
    result, state = run_helper(tmp_path, "install", modern_available=False)
    assert "rather than downgrading" in result["error"] and not result["operations"]
    assert state["state"] == "failed"


def test_missing_project_hosts_fail_before_any_task_mutation(tmp_path):
    result, state = run_helper(tmp_path, "install", modern_available=False, legacy_available=False)
    assert "service host is missing" in result["error"] and not result["operations"]
    assert state["state"] == "failed"


def test_explicit_recovery_reconciles_idle_owned_task_to_existing_shipped_host(tmp_path):
    result, state = run_helper(tmp_path, "install", modern_available=False, recover_missing=True)
    assert result["error"] is None and len(result["operations"]) == 2
    assert "service_host.py" in result["operations"][0]
    assert "service_host_v2.py" not in result["operations"][0]
    assert result["operations"][1] == "start"
    assert state["state"] == "failed"


@pytest.mark.parametrize("scenario", ["modern_busy", "modern_listener", "active_job"])
def test_missing_host_recovery_preserves_running_task_listener_and_research_work(
    tmp_path, scenario
):
    result, state = run_helper(
        tmp_path, "install", scenario, modern_available=False, recover_missing=True
    )
    assert result["error"] and not result["operations"]
    assert state["state"] == "failed"


@pytest.mark.parametrize("scenario", ["foreign_root", "foreign_executable"])
def test_explicit_recovery_never_claims_a_foreign_missing_host_task(tmp_path, scenario):
    result, state = run_helper(
        tmp_path, "install", scenario, modern_available=False, recover_missing=True
    )
    assert "different action" in result["error"] and not result["operations"]
    assert state["state"] == "failed"


def test_missing_host_recovery_cannot_implicitly_change_the_registered_cpu_profile(tmp_path):
    result, state = run_helper(
        tmp_path,
        "install",
        "recovery_profile_mismatch",
        modern_available=False,
        recover_missing=True,
        profile="CpuTwoProcessors",
    )
    assert "preserve the registered CPU profile" in result["error"]
    assert not result["operations"] and state["state"] == "failed"


def test_recovery_blocks_new_admission_at_registration_and_preserves_principal(tmp_path):
    result, _ = run_helper(
        tmp_path,
        "install",
        "admission_at_registration",
        modern_available=False,
        recover_missing=True,
    )
    assert result["error"] is None, result
    assert result["operations"][0] == "admission_blocked"
    assert result["operations"][-1] == "start"


@pytest.mark.parametrize(
    "scenario",
    ["foreign_server_path", "foreign_server_parent", "foreign_child", "child_reused_before_pin"],
)
def test_uncertain_server_or_child_is_preserved_before_task_stop(tmp_path, scenario):
    result, state = run_helper(tmp_path, "stop", scenario)
    assert result["error"] and not result["operations"]
    assert state["state"] == "failed"


def test_exit_in_final_check_to_kill_window_never_reopens_a_numeric_pid(tmp_path):
    result, state = run_helper(tmp_path, "stop", "late_exit_at_kill")
    assert result["error"] is None and state["state"] == "stopped"
    assert result["operations"] == ["stop", "pinned_original_exit_at_kill"]


def test_partial_shutdown_never_publishes_false_stopped_receipt(tmp_path):
    result, state = run_helper(tmp_path, "stop", "partial_shutdown")
    assert result["error"] and state["state"] == "failed"
    assert result["operations"] == ["stop", "stop_process:1001"]


def test_native_pinned_handle_survives_original_exit_and_rebound_pid_lookup(tmp_path):
    """Two owned sleeping Python processes; no task, model, port or operating service."""
    original = subprocess.Popen(
        [sys.executable, "-B", "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    replacement = subprocess.Popen(
        [sys.executable, "-B", "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    script = tmp_path / "pinned-native.ps1"
    script.write_text(
        r"""
param($Helper,$OriginalId,$ReplacementId)
$ErrorActionPreference='Stop'
. $Helper
$original=Get-Process -Id $OriginalId
$start=$original.StartTime.ToUniversalTime()
$candidate=[pscustomobject]@{ProcessId=$OriginalId;ParentProcessId=123;
    ExecutablePath='fixture-native';CreationDate=$start}
$pinned=Get-ResearchProcessHandle $candidate $start 123 @('fixture-native')
$original.Kill();$null=$original.WaitForExit(5000)
function Get-Process {throw 'Numeric PID lookup after validation must never occur'}
Stop-ResearchProcessHandle $pinned
$replacement=[Diagnostics.Process]::GetProcessById($ReplacementId)
if($replacement.HasExited){throw 'Replacement was interrupted'}
$pinned.Dispose();$original.Dispose();$replacement.Dispose()
Write-Output 'Original lifetime exited; replacement preserved'
""",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [
                SHELL,
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(script),
                str(ROOT / "scripts/ResearchRuntimeOwnership.ps1"),
                str(original.pid),
                str(replacement.pid),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert "replacement preserved" in result.stdout and replacement.poll() is None
    finally:
        for child in (original, replacement):
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


def test_native_maintenance_blocks_python_admission_and_releases_both_locks(tmp_path):
    """A disposable PowerShell process owns two QA locks; no research job is run."""
    script = tmp_path / "maintenance.ps1"
    ready = tmp_path / "ready.txt"
    script.write_text(
        r"""
param($Helper,$Directory,$Ready)
$ErrorActionPreference='Stop'
. $Helper
$held=Enter-ResearchMaintenance $Directory
try {
    [IO.File]::WriteAllText($Ready,'Both admission boundaries held')
    $null=[Console]::ReadLine()
} finally {foreach($handle in $held){$handle.Dispose()}}
""",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            SHELL,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script),
            str(ROOT / "scripts/ResearchRuntimeOwnership.ps1"),
            str(tmp_path),
            str(ready),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.025)
        assert ready.exists()
        for name in ("research-qualification-queue.lock", "research-inference.lock"):
            lock = CollectorLock(tmp_path / name)
            with pytest.raises(RuntimeError, match="Another collector"):
                lock.acquire()
            assert lock.handle is None
        _, errors = process.communicate("release\n", timeout=5)
        assert process.returncode == 0, errors
        for name in ("research-qualification-queue.lock", "research-inference.lock"):
            lock = CollectorLock(tmp_path / name)
            lock.acquire()
            lock.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
