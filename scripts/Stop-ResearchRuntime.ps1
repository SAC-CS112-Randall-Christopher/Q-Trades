[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$tradingRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$tradingStatePath = Join-Path $tradingRoot 'data\research-runtime.json'
$tradingRunner = Join-Path $PSScriptRoot 'Run-ResearchRuntime.ps1'
$tradingTask = Get-ScheduledTask -TaskName 'TradingResearch-Models-20260928' -ErrorAction Stop
$tradingExpectedArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $tradingRunner + '"'
$tradingOwnedArguments = @($tradingExpectedArguments, ($tradingExpectedArguments + ' -RuntimeProfile CpuTwoProcessors'), ($tradingExpectedArguments + ' -RuntimeProfile CpuElastic'))
$tradingOwnedArguments += @(($tradingExpectedArguments + ' -Profile CpuTwoProcessors'), ($tradingExpectedArguments + ' -Profile CpuElastic'))
$tradingHostExecutable = Join-Path $tradingRoot '.venv\Scripts\pythonw.exe'
$tradingHostScript = Join-Path $PSScriptRoot 'service_host.py'
$tradingCurrentHostScript = Join-Path $PSScriptRoot 'service_host_v2.py'
$tradingOwnedHostArguments = @(
    ('"' + $tradingHostScript + '" --kind models --runtime-profile CpuTwoProcessors'),
    ('"' + $tradingHostScript + '" --kind models --runtime-profile CpuElastic'),
    ('"' + $tradingCurrentHostScript + '" --kind models --runtime-profile CpuTwoProcessors'),
    ('"' + $tradingCurrentHostScript + '" --kind models --runtime-profile CpuElastic')
)
$tradingOwnedAction = $tradingTask.Actions.Count -eq 1 -and $tradingTask.Actions[0].WorkingDirectory -eq $tradingRoot -and (
    ($tradingTask.Actions[0].Execute -eq 'powershell.exe' -and $tradingTask.Actions[0].Arguments -in $tradingOwnedArguments) -or
    ($tradingTask.Actions[0].Execute -eq $tradingHostExecutable -and $tradingTask.Actions[0].Arguments -in $tradingOwnedHostArguments)
)
if (-not $tradingOwnedAction) { throw 'Scheduled task ownership differs.' }
$tradingState = Get-Content -LiteralPath $tradingStatePath -Raw | ConvertFrom-Json
if ($tradingState.origin -ne 'http://127.0.0.1:11435') { throw 'Unexpected runtime origin.' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe', 'pythonw.exe') -and $_.CommandLine -match '(evaluate_research_roles|run_qualification_queue|probe-dedicated-runtime|probe_research_runtime)' }) { throw 'A research job is active; preserve it and finish it before stopping the runtime.' }
$tradingServer = Get-CimInstance Win32_Process -Filter "ProcessId=$($tradingState.server_pid)"
if ($tradingServer) {
    $tradingProcess = Get-Process -Id $tradingState.server_pid -ErrorAction Stop
    $tradingExpectedStart = ([DateTime]$tradingState.server_started_at).ToUniversalTime()
    if ($tradingServer.ExecutablePath -ne $tradingState.executable -or $tradingServer.ParentProcessId -ne $tradingState.supervisor_pid -or $tradingProcess.StartTime.ToUniversalTime() -ne $tradingExpectedStart) { throw 'Server process identity changed; refusing to stop it.' }
    $tradingWorkerPath = Join-Path (Split-Path -Parent $tradingState.executable) 'lib\ollama\llama-server.exe'
    $tradingWorkers = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($tradingState.server_pid)" |
        Where-Object { $_.ExecutablePath -eq $tradingWorkerPath -or ($_.ExecutablePath -eq $tradingState.executable -and $_.CommandLine -match '\brunner\b') })
    $tradingResident = Invoke-RestMethod -Uri 'http://127.0.0.1:11435/api/ps' -TimeoutSec 5
    if ($tradingResident.models.Count -gt 0) { throw 'A model is still resident; do not interrupt a possible request.' }
} else { $tradingWorkers = @() }
Stop-ScheduledTask -TaskName 'TradingResearch-Models-20260928'
foreach ($tradingWorker in $tradingWorkers) { Stop-Process -Id $tradingWorker.ProcessId -ErrorAction SilentlyContinue }
if ($tradingServer) { Stop-Process -Id $tradingState.server_pid -ErrorAction SilentlyContinue }
if (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue) { throw 'A listener remains; inspect ownership before taking another action.' }
$tradingState.state = 'stopped'
$tradingState.updated_at = [DateTime]::UtcNow.ToString('o')
$tradingTemporary = $tradingStatePath + '.tmp'
[IO.File]::WriteAllText($tradingTemporary, ($tradingState | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
[IO.File]::Replace($tradingTemporary, $tradingStatePath, ($tradingStatePath + '.previous'))
Write-Output 'Dedicated trading runtime stopped. The ArcGIS runtime and paper worker were not targeted.'
