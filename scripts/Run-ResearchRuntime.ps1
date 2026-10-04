[CmdletBinding()]
param([ValidateSet('CpuTwoProcessors', 'CpuElastic')][string] $RuntimeProfile = 'CpuTwoProcessors')
$ErrorActionPreference = 'Stop'
$tradingRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$tradingData = Join-Path $tradingRoot 'data'
$tradingStatePath = Join-Path $tradingData 'research-runtime.json'
$tradingExecutable = (Get-Command ollama.exe -ErrorAction Stop).Source
$tradingWorkerExecutable = Join-Path (Split-Path -Parent $tradingExecutable) 'lib\ollama\llama-server.exe'
$tradingModels = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.ollama\models'
$tradingOrigin = 'http://127.0.0.1:11435'
$tradingMutex = New-Object Threading.Mutex($false, 'Local\TradingResearchModels20260928')
$tradingLocked = $false
$tradingServer = $null
$tradingExit = 0
$tradingState = [ordered]@{}
. (Join-Path $PSScriptRoot 'ResearchRuntimeOwnership.ps1')
$tradingElastic = $RuntimeProfile -eq 'CpuElastic'
$tradingThreads = if ($tradingElastic) { 6 } else { 2 }
$tradingPriority = if ($tradingElastic) { 'Idle' } else { 'BelowNormal' }
$tradingProfileName = if ($tradingElastic) { 'trading-cpu-elastic-six-threads-v1' } else { 'trading-cpu-two-processors-v1' }

function Save-RuntimeState {
    $tradingState.updated_at = [DateTime]::UtcNow.ToString('o')
    $tradingTemporary = $tradingStatePath + '.tmp'
    [IO.File]::WriteAllText($tradingTemporary, ($tradingState | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $tradingStatePath) {
        # Windows PowerShell 5.1 binds a null backup path as an invalid empty path.
        [IO.File]::Replace($tradingTemporary, $tradingStatePath, ($tradingStatePath + '.previous'))
    } else {
        [IO.File]::Move($tradingTemporary, $tradingStatePath)
    }
}

try {
    try { $tradingLocked = $tradingMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $tradingLocked = $true }
    if (-not $tradingLocked) { exit 0 }
    if (-not (Test-Path -LiteralPath $tradingModels -PathType Container)) { throw 'Installed model directory is missing; downloads are not performed.' }
    if (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 11435 is occupied; preserving its existing process.' }
    New-Item -ItemType Directory -Path $tradingData -Force | Out-Null
    # Process-local settings: no user/machine environment or ArcGIS runtime changes.
    $tradingEnvironment = [ordered]@{
        OLLAMA_HOST = '127.0.0.1:11435'; OLLAMA_MODELS = $tradingModels
        OLLAMA_NO_CLOUD = '1'; OLLAMA_NOPRUNE = '1'; OLLAMA_NUM_PARALLEL = '1'
        OLLAMA_MAX_LOADED_MODELS = '1'; OLLAMA_MAX_QUEUE = '2'; OLLAMA_KEEP_ALIVE = '60s'
        OLLAMA_CONTEXT_LENGTH = '8192'; CUDA_VISIBLE_DEVICES = '-1'; ROCR_VISIBLE_DEVICES = '-1'
        OLLAMA_VULKAN = '0'; GGML_VK_VISIBLE_DEVICES = '-1'; OMP_NUM_THREADS = [string]$tradingThreads
        OLLAMA_DEBUG = '0'
    }
    foreach ($tradingKey in $tradingEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($tradingKey, $tradingEnvironment[$tradingKey], 'Process')
    }
    $tradingStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $tradingServer = Start-Process -FilePath $tradingExecutable -ArgumentList @('serve') `
        -WorkingDirectory $tradingRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $tradingData "research-runtime-$tradingStamp.out.log") `
        -RedirectStandardError (Join-Path $tradingData "research-runtime-$tradingStamp.err.log")
    $null = $tradingServer.Handle
    $tradingServer.PriorityClass = $tradingPriority
    # Elastic research may use any processor, at lower priority than interactive/paper work.
    $tradingProcessorCount = [Environment]::ProcessorCount
    if ($tradingProcessorCount -lt 4 -or $tradingProcessorCount -gt 63) { throw 'CPU affinity needs an explicit profile on this machine.' }
    if ($tradingElastic -and $tradingProcessorCount -lt 6) { throw 'Six-thread profile requires at least six logical processors.' }
    $tradingAffinity = if ($tradingElastic) { (1L -shl $tradingProcessorCount) - 1L } else { (1L -shl ($tradingProcessorCount - 1)) -bor (1L -shl ($tradingProcessorCount - 3)) }
    $tradingServer.ProcessorAffinity = [IntPtr]$tradingAffinity
    # Hashing must not depend on Utility module auto-loading in windowless hosts.
    $tradingHasher = [Security.Cryptography.SHA256]::Create()
    try { $tradingScriptHash = ([BitConverter]::ToString($tradingHasher.ComputeHash([IO.File]::ReadAllBytes($PSCommandPath)))).Replace('-', '').ToLowerInvariant() }
    finally { $tradingHasher.Dispose() }
    $tradingState = [ordered]@{
        profile = $tradingProfileName; state = 'starting'; origin = $tradingOrigin
        supervisor_pid = $PID; server_pid = $tradingServer.Id; executable = $tradingExecutable
        server_started_at = $tradingServer.StartTime.ToUniversalTime().ToString('o')
        started_at = [DateTime]::UtcNow.ToString('o'); priority = $tradingPriority
        processor_affinity = $tradingAffinity; logical_processors = if ($tradingElastic) { $tradingProcessorCount } else { 2 }
        inference_threads = $tradingThreads; gpu_policy = 'Reserved for ArcGIS; research CPU only'
        environment = $tradingEnvironment; script_sha256 = $tradingScriptHash
    }
    Save-RuntimeState
    $tradingReady = $false
    for ($tradingAttempt = 0; $tradingAttempt -lt 20; $tradingAttempt++) {
        if ($tradingServer.HasExited) { throw 'Dedicated model server exited during startup.' }
        try {
            $tradingVersion = Invoke-RestMethod -Uri ($tradingOrigin + '/api/version') -TimeoutSec 3
            $tradingReady = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $tradingReady) { throw 'Dedicated model server did not become ready.' }
    $tradingListeners = @(Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction Stop)
    if ($tradingListeners.Count -ne 1 -or $tradingListeners[0].LocalAddress -ne '127.0.0.1' -or $tradingListeners[0].OwningProcess -ne $tradingServer.Id) { throw 'Runtime listener ownership or loopback binding differs.' }
    $tradingState.state = 'running'
    $tradingState.version = $tradingVersion.version
    Save-RuntimeState
    $tradingBudgetedWorker = 0
    $tradingLastHeartbeat = [DateTime]::UtcNow
    while (-not $tradingServer.HasExited) {
        # Ollama may give its worker higher priority explicitly, overriding inheritance.
        $tradingWorkers = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($tradingServer.Id)" |
            Where-Object { $_.ExecutablePath -eq $tradingWorkerExecutable -or ($_.ExecutablePath -eq $tradingExecutable -and $_.CommandLine -match '\brunner\b') }
        foreach ($tradingWorker in $tradingWorkers) {
            $tradingWorkerProcess = $null
            try {
                $tradingWorkerStart = ([DateTime]$tradingWorker.CreationDate).ToUniversalTime()
                if ($tradingWorkerStart -lt $tradingServer.StartTime.ToUniversalTime()) { throw 'Child predates server.' }
                $tradingWorkerProcess = Get-ResearchProcessHandle $tradingWorker $tradingWorkerStart $tradingServer.Id @($tradingWorkerExecutable, $tradingExecutable)
                if ($null -ne $tradingWorkerProcess) {
                    $tradingWorkerProcess.PriorityClass = $tradingPriority
                    $tradingWorkerProcess.ProcessorAffinity = [IntPtr]$tradingAffinity
                    if ($tradingBudgetedWorker -ne $tradingWorkerProcess.Id -or $tradingState.worker_started_at -ne $tradingWorkerStart.ToString('o')) {
                        $tradingBudgetedWorker = $tradingWorkerProcess.Id
                        $tradingState.last_budgeted_worker_pid = $tradingBudgetedWorker
                        $tradingState.worker_started_at = $tradingWorkerStart.ToString('o')
                        $tradingState.worker_executable = $tradingWorker.ExecutablePath
                        Save-RuntimeState
                    }
                }
            } catch { if (-not $tradingWorkerProcess -or -not $tradingWorkerProcess.HasExited) { throw } }
            finally { if ($tradingWorkerProcess) { $tradingWorkerProcess.Dispose() } }
        }
        if (([DateTime]::UtcNow - $tradingLastHeartbeat).TotalSeconds -ge 10) {
            Save-RuntimeState
            $tradingLastHeartbeat = [DateTime]::UtcNow
        }
        Start-Sleep -Seconds 2
        $tradingServer.Refresh()
    }
    throw "Dedicated model server exited with code $($tradingServer.ExitCode)."
} catch {
    $tradingExit = 1
    if ($tradingState.Count) {
        $tradingState.state = 'failed'
        $tradingState.error = $_.Exception.Message
        try { Save-RuntimeState }
        catch { Write-Error ('Runtime status save failed: ' + $_.Exception.Message) -ErrorAction Continue }
    }
    Write-Error $_ -ErrorAction Continue
} finally {
    try {
    if ($tradingServer -and -not $tradingServer.HasExited) {
        $tradingChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($tradingServer.Id)"
        foreach ($tradingChild in $tradingChildren) {
            if ($tradingChild.ExecutablePath -ne $tradingWorkerExecutable -and
                -not ($tradingChild.ExecutablePath -eq $tradingExecutable -and $tradingChild.CommandLine -match '\brunner\b')) {
                Write-Error 'Unknown research child preserved for diagnosis.' -ErrorAction Continue
                continue
            }
            $tradingChildHandle = $null
            try {
                $tradingChildStart = ([DateTime]$tradingChild.CreationDate).ToUniversalTime()
                if ($tradingChildStart -lt $tradingServer.StartTime.ToUniversalTime()) { throw 'Child predates server.' }
                $tradingChildHandle = Get-ResearchProcessHandle $tradingChild $tradingChildStart $tradingServer.Id @($tradingWorkerExecutable, $tradingExecutable)
                Stop-ResearchProcessHandle $tradingChildHandle
            } catch { Write-Error ('Research child preserved: ' + $_.Exception.Message) -ErrorAction Continue }
            finally { if ($tradingChildHandle) { $tradingChildHandle.Dispose() } }
        }
        Stop-ResearchProcessHandle $tradingServer
    }
    } finally {
    if ($tradingServer) { $tradingServer.Dispose() }
    if ($tradingLocked) { $tradingMutex.ReleaseMutex() }
    $tradingMutex.Dispose()
    }
}
exit $tradingExit
