[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'Run-PaperExperiment.ps1'
$taskName = 'TradingResearch-Paper-20260927'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '"'
$hostExecutable = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$hostScript = Join-Path $PSScriptRoot 'service_host.py'
$hostArguments = '"' + $hostScript + '" --kind paper'
if (-not (Test-Path -LiteralPath $hostExecutable)) { throw 'Project windowless Python is missing.' }
$action = New-ScheduledTaskAction -Execute $hostExecutable -Argument $hostArguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$ownedAction = $existing -and $existing.Actions.Count -eq 1 -and $existing.Actions[0].WorkingDirectory -eq $projectRoot -and (
    ($existing.Actions[0].Execute -eq 'powershell.exe' -and $existing.Actions[0].Arguments -eq $arguments) -or
    ($existing.Actions[0].Execute -eq $hostExecutable -and $existing.Actions[0].Arguments -eq $hostArguments)
)
if ($existing -and -not $ownedAction) {
    throw 'A task with this name points to another command; preserving it.'
}
if ($existing -and $existing.State -eq 'Running') { throw 'The paper supervisor is already running; preserve it before changing its host.' }
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Local fake-money Tier 3 experiment. Never submits real orders.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
