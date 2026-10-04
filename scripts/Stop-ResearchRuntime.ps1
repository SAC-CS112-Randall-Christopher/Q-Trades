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
. (Join-Path $PSScriptRoot 'ResearchRuntimeOwnership.ps1')
$tradingMaintenance = Enter-ResearchMaintenance (Join-Path $tradingRoot 'data')
$tradingHandles = New-Object 'System.Collections.Generic.List[object]'
try {
$tradingServer = Get-CimInstance Win32_Process -Filter "ProcessId=$($tradingState.server_pid)"
if ($tradingServer) {
    $tradingExpectedStart = ([DateTime]$tradingState.server_started_at).ToUniversalTime()
    $tradingProcess = Get-ResearchProcessHandle $tradingServer $tradingExpectedStart $tradingState.supervisor_pid @($tradingState.executable)
    if ($tradingProcess) { $tradingHandles.Add($tradingProcess) }
    $tradingWorkerPath = Join-Path (Split-Path -Parent $tradingState.executable) 'lib\ollama\llama-server.exe'
    $tradingWorkers = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($tradingState.server_pid)")
    foreach ($tradingWorker in $tradingWorkers) {
        if ($tradingWorker.ExecutablePath -ne $tradingWorkerPath -and
            -not ($tradingWorker.ExecutablePath -eq $tradingState.executable -and $tradingWorker.CommandLine -match '\brunner\b')) {
            throw 'Research child ownership differs; preserve it for diagnosis.'
        }
        $tradingChildStart = ([DateTime]$tradingWorker.CreationDate).ToUniversalTime()
        if ($tradingChildStart -lt $tradingExpectedStart) { throw 'Research child predates its owned server.' }
        $tradingChild = Get-ResearchProcessHandle $tradingWorker $tradingChildStart $tradingState.server_pid @($tradingWorkerPath, $tradingState.executable)
        if ($tradingChild) { $tradingHandles.Add($tradingChild) }
    }
    $tradingResident = Invoke-RestMethod -Uri 'http://127.0.0.1:11435/api/ps' -TimeoutSec 5
    if ($tradingResident.models.Count -gt 0) { throw 'A model is still resident; do not interrupt a possible request.' }
} else { $tradingWorkers = @() }
$tradingListeners = @(Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue)
foreach ($tradingListener in $tradingListeners) {
    if (-not $tradingServer -or $tradingListener.OwningProcess -ne $tradingState.server_pid -or
        $tradingListener.LocalAddress -ne '127.0.0.1') {
        throw 'An uncertain listener remains; preserve its process and task for diagnosis.'
    }
}
Stop-ScheduledTask -TaskName 'TradingResearch-Models-20260928'
for ($tradingIndex = $tradingHandles.Count - 1; $tradingIndex -ge 0; $tradingIndex--) {
    Stop-ResearchProcessHandle $tradingHandles[$tradingIndex]
}
if (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue) { throw 'A listener remains; inspect ownership before taking another action.' }
$tradingState.state = 'stopped'
$tradingState.updated_at = [DateTime]::UtcNow.ToString('o')
$tradingTemporary = $tradingStatePath + '.tmp'
[IO.File]::WriteAllText($tradingTemporary, ($tradingState | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
[IO.File]::Replace($tradingTemporary, $tradingStatePath, ($tradingStatePath + '.previous'))
Write-Output 'Dedicated trading runtime stopped. The ArcGIS runtime and paper worker were not targeted.'
} finally {
    foreach ($tradingHandle in $tradingHandles) { $tradingHandle.Dispose() }
    foreach ($tradingHandle in $tradingMaintenance) { $tradingHandle.Dispose() }
}
