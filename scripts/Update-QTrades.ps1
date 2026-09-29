[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$taskName = 'TradingResearch-Paper-20260927'
. (Join-Path $PSScriptRoot 'PaperStartupIdentity.ps1')

function Git-Read {
    $output = & git --no-pager -C $source @args
    if ($LASTEXITCODE -ne 0) { throw 'Git failed. Resolve the reported error; no reset or force-pull is used.' }
    return ($output -join "`n").Trim()
}
function Copy-Code([string] $From, [string] $To, [switch] $Mirror) {
    # Never mirror a project root, data/, configs/, docs/, .git or a database volume.
    $mode = if ($Mirror) { '/MIR' } else { '/E' }
    foreach ($directory in @('src', 'scripts', 'apps/web')) {
        $origin = Join-Path $From $directory
        $destination = Join-Path $To $directory
        foreach ($path in @($origin, $destination)) {
            if ((Test-Path -LiteralPath $path) -and
                ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "Code directory is redirected; preserving it: $path"
            }
        }
        & robocopy $origin $destination $mode /XJ /R:1 /W:1 /NFL /NDL /NJH /NJS `
            /XD node_modules __pycache__ .git .venv /XF '*.pyc' | Out-Host
        if ($LASTEXITCODE -ge 8) { throw "Code copy failed: $directory" }
    }
    foreach ($name in @('pyproject.toml','requirements-lock.txt','AGENTS.md','README.md')) {
        Copy-Item -LiteralPath (Join-Path $From $name) -Destination (Join-Path $To $name) -Force
    }
}

$disabled = $false
$copyStarted = $false
$mutex = $null
$held = $false
$backup = $null
try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if (@($task.Actions).Count -ne 1) { throw 'Unexpected task actions; no update applied.' }
    $runtime = (Resolve-Path -LiteralPath $task.Actions[0].WorkingDirectory).Path
    if (-not (Test-PaperStartupAction $task $runtime)) { throw 'The task does not identify Q-Trades.' }
    if ($runtime.TrimEnd('\') -ieq $source.TrimEnd('\')) {
        throw 'Run this updater from the separate GitHub checkout, not the running application folder.'
    }
    $python = Join-Path $runtime '.venv/Scripts/python.exe'
    foreach ($required in @($python, (Join-Path $runtime 'data/monitor.sqlite3'),
        (Join-Path $runtime 'data/paper-database.json'))) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw 'Existing application data or Python is missing. No fresh account will be created.'
        }
    }
    $url = Git-Read remote get-url --all origin
    if ($url.TrimEnd('/') -notin @('https://github.com/SAC-CS112-Randall-Christopher/Q-Trades.git',
        'https://github.com/SAC-CS112-Randall-Christopher/Q-Trades')) { throw 'Unexpected Git repository.' }
    if ((Git-Read rev-parse --show-toplevel).Replace('\','/') -ine $source.Replace('\','/')) {
        throw 'Run from the Q-Trades repository root.'
    }
    if (Git-Read status --porcelain --untracked-files=normal) { throw 'Preserve/commit local checkout changes before updating.' }
    Write-Host 'Getting GitHub main...'
    Git-Read fetch --no-tags origin refs/heads/main | Out-Host
    $commit = Git-Read rev-parse FETCH_HEAD
    if ($commit -notmatch '^[0-9a-f]{40}$') { throw 'Main did not resolve to a commit.' }
    Git-Read cat-file -e "${commit}:src/trading/api.py" | Out-Host
    Git-Read merge --ff-only $commit | Out-Host
    if ((Git-Read rev-parse HEAD) -ne $commit) { throw 'Checkout is ahead of main; no development branch will be installed.' }
    Write-Host 'Building the dashboard before stopping the application...'
    & npm --prefix (Join-Path $source 'apps/web') ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Dependency download failed; the running app is unchanged.' }
    & npm --prefix (Join-Path $source 'apps/web') run build
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed; the running app is unchanged.' }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'apps/web/dist/index.html'))) { throw 'Dashboard build is missing.' }
    if (Git-Read status --porcelain --untracked-files=normal) { throw 'Build changed source; preserve and review it.' }
    # Back up source only. Runtime data and experiment evidence never enter this copy.
    $backup = Join-Path $runtime ('data/update-backups/' + (Get-Date -Format 'yyyyMMdd-HHmmss-ffff'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-Code $runtime $backup
    Write-Host "Source backup: $backup"
    # The existing task and supervisor already own process lifetime. Reuse them.
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if (-not (Test-PaperStartupAction $task $runtime)) { throw 'Startup task changed during preparation.' }
    $wasEnabled = $task.Settings.Enabled
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    $disabled = $true
    if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName }
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        $task = Get-ScheduledTask -TaskName $taskName
        $listeners = @(Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue)
        if ($task.State -ne 'Running' -and $listeners.Count -eq 0) { break }
        Start-Sleep -Seconds 2
    }
    if ($task.State -eq 'Running' -or $listeners.Count -ne 0) { throw 'The existing service did not stop. Application files remain unchanged.' }
    $mutex = New-Object Threading.Mutex($false, 'Local\TradingResearchPaper20260927')
    try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { throw 'The existing supervisor has not exited. Application files remain unchanged.' }
    Write-Host 'Updating application code and Python dependencies...'
    $copyStarted = $true
    Copy-Code $source $runtime -Mirror
    & $python -B -m pip install --no-input -r (Join-Path $runtime 'requirements-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed; retry after resolving the error.' }
    & $python -B -m pip install --no-input --no-deps -e $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Application installation failed; retry after resolving the error.' }
    [IO.File]::WriteAllText((Join-Path $runtime 'data/installed-commit.txt'), $commit)
    $mutex.ReleaseMutex(); $held = $false
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    $disabled = $false
    Start-ScheduledTask -TaskName $taskName
    Write-Host 'Waiting for the existing application to report healthy...'
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        $report = & $python -B (Join-Path $source 'scripts/qtrades_health.py') $commit
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Q-Trades updated and running: $commit" -ForegroundColor Green
            Write-Host $report
            exit 0
        }
    }
    throw "Code $commit is installed, but health is not confirmed. Inspect the application logs; do not reset accounts."
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    if ($disabled -and -not $copyStarted -and $wasEnabled) { Enable-ScheduledTask -TaskName $taskName | Out-Null }
    if ($disabled -and $copyStarted) {
        [Console]::Error.WriteLine("Application is left stopped. Source backup: $backup. Fix the reported error and rerun this updater. Databases and research history were not replaced.")
    }
    exit 1
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
