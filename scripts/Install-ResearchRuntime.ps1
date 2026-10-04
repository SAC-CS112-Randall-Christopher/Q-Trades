[CmdletBinding()]
param(
    [ValidateSet('CpuTwoProcessors', 'CpuElastic')][string] $RuntimeProfile = 'CpuTwoProcessors',
    [switch] $RecoverMissingHost
)
$ErrorActionPreference = 'Stop'
$tradingRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$tradingRunner = Join-Path $PSScriptRoot 'Run-ResearchRuntime.ps1'
$tradingTaskName = 'TradingResearch-Models-20260928'
$tradingIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$tradingHostExecutable = Join-Path $tradingRoot '.venv\Scripts\pythonw.exe'
$tradingLegacyHostScript = Join-Path $PSScriptRoot 'service_host.py'
$tradingCurrentHostScript = Join-Path $PSScriptRoot 'service_host_v2.py'
$tradingHostScript = if (Test-Path -LiteralPath $tradingCurrentHostScript) { $tradingCurrentHostScript } else { $tradingLegacyHostScript }
if (-not (Test-Path -LiteralPath $tradingHostExecutable)) { throw 'Project windowless Python is missing.' }
if (-not (Test-Path -LiteralPath $tradingHostScript)) { throw 'Project model service host is missing.' }
$tradingArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $tradingRunner + '"'
$tradingOwnedArguments = @($tradingArguments, ($tradingArguments + ' -RuntimeProfile CpuTwoProcessors'), ($tradingArguments + ' -RuntimeProfile CpuElastic'))
# Exact arguments from the first locally installed profile revision.
$tradingOwnedArguments += @(($tradingArguments + ' -Profile CpuTwoProcessors'), ($tradingArguments + ' -Profile CpuElastic'))
$tradingHostArguments = '"' + $tradingHostScript + '" --kind models --runtime-profile ' + $RuntimeProfile
$tradingOwnedHostArguments = @(
    ('"' + $tradingLegacyHostScript + '" --kind models --runtime-profile CpuTwoProcessors'),
    ('"' + $tradingLegacyHostScript + '" --kind models --runtime-profile CpuElastic'),
    ('"' + $tradingCurrentHostScript + '" --kind models --runtime-profile CpuTwoProcessors'),
    ('"' + $tradingCurrentHostScript + '" --kind models --runtime-profile CpuElastic')
)
$tradingExisting = Get-ScheduledTask -TaskName $tradingTaskName -ErrorAction SilentlyContinue
$tradingOwnedAction = $tradingExisting -and $tradingExisting.Actions.Count -eq 1 -and $tradingExisting.Actions[0].WorkingDirectory -eq $tradingRoot -and (
    ($tradingExisting.Actions[0].Execute -eq 'powershell.exe' -and $tradingExisting.Actions[0].Arguments -in $tradingOwnedArguments) -or
    ($tradingExisting.Actions[0].Execute -eq $tradingHostExecutable -and $tradingExisting.Actions[0].Arguments -in $tradingOwnedHostArguments)
)
if ($tradingExisting -and -not $tradingOwnedAction) {
    throw 'Task name is already owned by a different action; preserving it.'
}
$tradingExistingUsesCurrentHost = $tradingExisting -and $tradingExisting.Actions[0].Execute -eq $tradingHostExecutable -and
    $tradingExisting.Actions[0].Arguments.StartsWith('"' + $tradingCurrentHostScript + '" ')
if ($tradingExistingUsesCurrentHost -and -not (Test-Path -LiteralPath $tradingCurrentHostScript)) {
    if (-not $RecoverMissingHost) {
        throw 'Current model service host is missing; preserving the task rather than downgrading it. Review ownership and use -RecoverMissingHost only for an explicitly authorized recovery.'
    }
    if (-not $tradingExisting.Actions[0].Arguments.EndsWith(' --runtime-profile ' + $RuntimeProfile)) {
        throw 'Missing-host recovery must preserve the registered CPU profile; select that profile explicitly.'
    }
    if (Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe', 'pythonw.exe') -and $_.CommandLine -match '(evaluate_research_roles|run_qualification_queue|probe-dedicated-runtime|probe_research_runtime)' }) {
        throw 'A research job is active; preserve it and finish it before recovering the runtime task.'
    }
}
if (-not $tradingExisting -or $tradingExisting.Actions[0].Arguments -ne $tradingHostArguments) {
    if (($tradingExisting -and $tradingExisting.State -eq 'Running') -or (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue)) { throw 'Finish research jobs and use Stop-ResearchRuntime.ps1 before changing the runtime profile.' }
    $tradingAction = New-ScheduledTaskAction -Execute $tradingHostExecutable -Argument $tradingHostArguments -WorkingDirectory $tradingRoot
    $tradingTrigger = New-ScheduledTaskTrigger -AtLogOn -User $tradingIdentity
    $tradingPrincipal = New-ScheduledTaskPrincipal -UserId $tradingIdentity -LogonType Interactive -RunLevel Limited
    $tradingSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $tradingTaskName -Action $tradingAction -Trigger $tradingTrigger -Force `
        -Principal $tradingPrincipal -Settings $tradingSettings `
        -Description 'Local CPU-only trading research model runtime on loopback port 11435. No cloud inference or account authority.' | Out-Null
}
Start-ScheduledTask -TaskName $tradingTaskName
Get-ScheduledTask -TaskName $tradingTaskName | Select-Object TaskName, State
