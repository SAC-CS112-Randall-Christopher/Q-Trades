[CmdletBinding()]
param([ValidateSet('CpuTwoProcessors', 'CpuElastic')][string] $RuntimeProfile = 'CpuTwoProcessors')
$ErrorActionPreference = 'Stop'
$tradingRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$tradingRunner = Join-Path $PSScriptRoot 'Run-ResearchRuntime.ps1'
$tradingTaskName = 'TradingResearch-Models-20260928'
$tradingIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$tradingHostExecutable = Join-Path $tradingRoot '.venv\Scripts\pythonw.exe'
$tradingHostScript = Join-Path $PSScriptRoot 'service_host.py'
if (-not (Test-Path -LiteralPath $tradingHostExecutable)) { throw 'Project windowless Python is missing.' }
$tradingArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $tradingRunner + '"'
$tradingOwnedArguments = @($tradingArguments, ($tradingArguments + ' -RuntimeProfile CpuTwoProcessors'), ($tradingArguments + ' -RuntimeProfile CpuElastic'))
# Exact arguments from the first locally installed profile revision.
$tradingOwnedArguments += @(($tradingArguments + ' -Profile CpuTwoProcessors'), ($tradingArguments + ' -Profile CpuElastic'))
$tradingHostArguments = '"' + $tradingHostScript + '" --kind models --runtime-profile ' + $RuntimeProfile
$tradingOwnedHostArguments = @(
    ('"' + $tradingHostScript + '" --kind models --runtime-profile CpuTwoProcessors'),
    ('"' + $tradingHostScript + '" --kind models --runtime-profile CpuElastic')
)
$tradingExisting = Get-ScheduledTask -TaskName $tradingTaskName -ErrorAction SilentlyContinue
$tradingOwnedAction = $tradingExisting -and $tradingExisting.Actions.Count -eq 1 -and $tradingExisting.Actions[0].WorkingDirectory -eq $tradingRoot -and (
    ($tradingExisting.Actions[0].Execute -eq 'powershell.exe' -and $tradingExisting.Actions[0].Arguments -in $tradingOwnedArguments) -or
    ($tradingExisting.Actions[0].Execute -eq $tradingHostExecutable -and $tradingExisting.Actions[0].Arguments -in $tradingOwnedHostArguments)
)
if ($tradingExisting -and -not $tradingOwnedAction) {
    throw 'Task name is already owned by a different action; preserving it.'
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
