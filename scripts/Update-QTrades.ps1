[CmdletBinding()]
param(
    [string] $LogDirectory = 'C:\Projects\Q-Trades\logs',
    [string] $ExpectedCommit = '',
    [ValidateSet('', 'default', 'pglz', 'lz4')]
    [string] $PaperProjectionCompression = '',
    [ValidateSet('', 'default', 'pglz', 'lz4')]
    [string] $ExpectedPaperProjectionCompression = '',
    [ValidateSet(0, 400)]
    [int] $TemporaryStorageGB = 0,
    [ValidateSet(0, 100)]
    [int] $ExpectedTemporaryStorageGB = 0
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$taskName = 'TradingResearch-Paper-20260927'

# Use PowerShell's transcript, not a separate logging service. Native output is
# written to the host immediately so it reaches both the console and the log.
function Write-Stage([string] $Message) {
    $script:stage = $Message
    Write-Host ("[{0:o}] {1}" -f (Get-Date), $Message)
}
function Invoke-LoggedNative([string] $FilePath, [string[]] $Arguments) {
    $executable = Get-Command $FilePath -ErrorAction Stop
    # Windows PowerShell may turn native stderr into ErrorRecords. A warning is
    # not a failed command: retain it, then use the actual native exit code.
    $ErrorActionPreference = 'Continue'
    & $executable @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    if ($null -eq $code) { throw 'The command did not provide an exit code.' }
    Write-Host "Command exit code: $code"
    return $code
}

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
        Write-Host "Copy $mode : $origin -> $destination"
        # Keep file classes/names (including extra files removed by /MIR) in the log.
        $copyExit = Invoke-LoggedNative 'robocopy' @($origin, $destination, $mode,
            '/XJ', '/R:1', '/W:1', '/FP', '/NP', '/NJH', '/NJS',
            '/XD', 'node_modules', '__pycache__', '.git', '.venv', '/XF', '*.pyc')
        if ($copyExit -ge 8) { throw "Code copy failed: $directory" }
    }
    foreach ($name in @('pyproject.toml','requirements-lock.txt','AGENTS.md','README.md')) {
        Copy-Item -LiteralPath (Join-Path $From $name) -Destination (Join-Path $To $name) -Force
        Write-Host "Copied: $(Join-Path $To $name)"
    }
}

$startedAt = Get-Date
$logPath = $null
$transcribing = $false
$outcome = 'INCOMPLETE'
$stage = 'Open update log'
$previousCommit = 'unknown'
$commit = 'not selected'
$wasEnabled = $false
$disabled = $false
$copyStarted = $false
$mutex = $null
$held = $false
$backup = $null
$updateMutex = $null
$updateHeld = $false
try {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    $logPath = Join-Path $LogDirectory ('update-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') +
        '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8) + '.log')
    Start-Transcript -LiteralPath $logPath -NoClobber -ErrorAction Stop | Out-Null
    $transcribing = $true
    Write-Host "Update log: $logPath"
    Write-Host "Source checkout: $source"
    Write-Host 'Local diagnostic log. Review before sharing; dependency output may contain private details.'
    if ($PSBoundParameters.ContainsKey('ExpectedCommit')) {
        if ($ExpectedCommit -notmatch '\A[0-9a-f]{40}\z') {
            throw 'ExpectedCommit must be the full 40-hex approved target commit.'
        }
        Write-Host "Approved target commit: $ExpectedCommit"
    }
    if (([bool] $PaperProjectionCompression) -ne ([bool] $ExpectedPaperProjectionCompression)) {
        throw 'Compression changes require both the reviewed target and expected previous setting.'
    }
    if (([bool] $TemporaryStorageGB) -ne ([bool] $ExpectedTemporaryStorageGB)) {
        throw 'Storage expansion requires both the reviewed target and expected previous quota.'
    }
    Write-Stage 'Validate the existing installation'
    . (Join-Path $PSScriptRoot 'PaperStartupIdentity.ps1')
    . (Join-Path $PSScriptRoot 'PaperUpdateShutdown.ps1')
    $updateMutex = New-Object Threading.Mutex($false, 'Local\QTradesManualUpdate')
    try { $updateHeld = $updateMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $updateHeld = $true }
    if (-not $updateHeld) { throw 'Another Q-Trades update is running.' }
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if (@($task.Actions).Count -ne 1) { throw 'Unexpected task actions; no update applied.' }
    $runtime = (Resolve-Path -LiteralPath $task.Actions[0].WorkingDirectory).Path
    if (-not (Test-PaperStartupAction $task $runtime)) { throw 'The task does not identify Q-Trades.' }
    if ($runtime.TrimEnd('\') -ieq $source.TrimEnd('\')) {
        throw 'Run this updater from the separate GitHub checkout, not the running application folder.'
    }
    Write-Host "Installed application: $runtime"
    $installedMarker = Join-Path $runtime 'data/installed-commit.txt'
    if (Test-Path -LiteralPath $installedMarker -PathType Leaf) {
        $savedCommit = ([IO.File]::ReadAllText($installedMarker)).Trim()
        if ($savedCommit -match '^[0-9a-f]{40}$') { $previousCommit = $savedCommit }
    }
    Write-Host "Previous installed commit: $previousCommit"
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
    Write-Stage 'Fetch GitHub main'
    Git-Read fetch --no-tags origin refs/heads/main | Out-Host
    $commit = Git-Read rev-parse FETCH_HEAD
    if ($commit -notmatch '^[0-9a-f]{40}$') { throw 'Main did not resolve to a commit.' }
    Write-Host "Target main commit: $commit"
    if ($ExpectedCommit -and $commit -ne $ExpectedCommit) {
        throw 'Fetched main differs from the approved target commit. No checkout or application update applied.'
    }
    Git-Read cat-file -e "${commit}:src/trading/api.py" | Out-Host
    Git-Read merge --ff-only $commit | Out-Host
    if ((Git-Read rev-parse HEAD) -ne $commit) { throw 'Checkout is ahead of main; no development branch will be installed.' }
    Write-Host 'Tracked code changes since the installed marker (not proof of completed copies):'
    if ($previousCommit -ne 'unknown') {
        try {
            $changes = Git-Read diff --name-status --no-renames $previousCommit $commit -- `
                src scripts apps/web pyproject.toml requirements-lock.txt AGENTS.md README.md
            if ($changes) { Write-Host $changes } else { Write-Host 'No tracked code differences.' }
        } catch { Write-Host 'Previous commit is not available locally; consult the file-copy output below.' }
    } else { Write-Host 'Previous version unknown; consult the file-copy output below.' }
    Write-Stage 'Install dashboard dependencies (application still running)'
    $commandExit = Invoke-LoggedNative 'npm' @('--prefix', (Join-Path $source 'apps/web'),
        'ci', '--ignore-scripts', '--no-audit', '--no-fund')
    if ($commandExit -ne 0) { throw 'Dependency download failed; the running app is unchanged.' }
    Write-Stage 'Build dashboard (application still running)'
    $commandExit = Invoke-LoggedNative 'npm' @('--prefix', (Join-Path $source 'apps/web'), 'run', 'build')
    if ($commandExit -ne 0) { throw 'Dashboard build failed; the running app is unchanged.' }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'apps/web/dist/index.html'))) { throw 'Dashboard build is missing.' }
    if (Git-Read status --porcelain --untracked-files=normal) { throw 'Build changed source; preserve and review it.' }
    if ((Git-Read rev-parse HEAD) -ne $commit) { throw 'Source commit changed during the build; no application update applied.' }
    if ($PaperProjectionCompression) {
        Write-Stage 'Preview the explicitly requested projection compression'
        $projectionArguments = @('-X', 'utf8', '-B',
            (Join-Path $source 'scripts/configure_paper_projection.py'),
            '--settings', (Join-Path $runtime 'data/paper-database.json'),
            '--compression', $PaperProjectionCompression,
            '--expected', $ExpectedPaperProjectionCompression)
        $commandExit = Invoke-LoggedNative $python $projectionArguments
        if ($commandExit -ne 0) { throw 'Compression preview failed; the running app is unchanged.' }
    }
    if ($TemporaryStorageGB) {
        Write-Stage 'Preview the explicitly requested temporary storage expansion'
        $storageArguments = @('-X', 'utf8', '-B',
            (Join-Path $source 'scripts/configure_research_storage.py'),
            '--settings', (Join-Path $runtime 'data/paper-database.json'),
            '--directory', (Join-Path $runtime 'data'),
            '--temporary-gb', $TemporaryStorageGB.ToString(),
            '--expected-temporary-gb', $ExpectedTemporaryStorageGB.ToString())
        $commandExit = Invoke-LoggedNative $python $storageArguments
        if ($commandExit -ne 0) { throw 'Storage preview failed; the running app is unchanged.' }
    }
    Write-Stage 'Back up installed source code'
    # Back up source only. Runtime data and experiment evidence never enter this copy.
    $backup = Join-Path $runtime ('data/update-backups/' + (Get-Date -Format 'yyyyMMdd-HHmmss-ffff'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-Code $runtime $backup
    Write-Host "Source backup: $backup"
    Write-Stage 'Stop the existing application'
    # The existing task and supervisor already own process lifetime. Reuse them.
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if (-not (Test-PaperStartupAction $task $runtime)) { throw 'Startup task changed during preparation.' }
    $wasEnabled = $task.Settings.Enabled
    $paperProcesses = @(Get-PaperUpdateProcessSnapshot $runtime)
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    $disabled = $true
    if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName }
    Stop-VerifiedPaperUpdateProcesses $paperProcesses
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
    Write-Stage 'Copy application code'
    $copyStarted = $true
    Copy-Code $source $runtime -Mirror
    Write-Stage 'Install Python dependencies'
    $commandExit = Invoke-LoggedNative $python @('-B', '-m', 'pip', 'install', '--no-input',
        '-r', (Join-Path $runtime 'requirements-lock.txt'))
    if ($commandExit -ne 0) { throw 'Python dependency installation failed; retry after resolving the error.' }
    Write-Stage 'Install application package'
    $commandExit = Invoke-LoggedNative $python @('-B', '-m', 'pip', 'install', '--no-input',
        '--no-deps', '-e', $runtime)
    if ($commandExit -ne 0) { throw 'Application installation failed; retry after resolving the error.' }
    if ($PaperProjectionCompression) {
        Write-Stage 'Apply the explicitly requested projection compression'
        $commandExit = Invoke-LoggedNative $python ($projectionArguments + @('--apply'))
        if ($commandExit -ne 0) { throw 'Compression was not confirmed; the application remains stopped.' }
    }
    if ($TemporaryStorageGB) {
        Write-Stage 'Apply the explicitly requested temporary storage expansion'
        $commandExit = Invoke-LoggedNative $python ($storageArguments + @('--apply'))
        if ($commandExit -ne 0) { throw 'Storage expansion was not confirmed; the application remains stopped.' }
    }
    [IO.File]::WriteAllText((Join-Path $runtime 'data/installed-commit.txt'), $commit)
    Write-Host 'Installed-version marker written; restart health is not confirmed yet.'
    Write-Stage 'Restart the existing application'
    $mutex.ReleaseMutex(); $held = $false
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    $disabled = $false
    Start-ScheduledTask -TaskName $taskName
    Write-Stage 'Verify running version and paper health'
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        $report = & $python -B (Join-Path $source 'scripts/qtrades_health.py') $commit
        $healthExit = $LASTEXITCODE
        Write-Host "Health attempt $($attempt + 1): exit=$healthExit $report"
        if ($healthExit -eq 0) {
            $outcome = 'SUCCESS'
            Write-Host "Q-Trades updated and running: $commit" -ForegroundColor Green
            Write-Host $report
            exit 0
        }
    }
    throw "Code $commit is installed, but health is not confirmed. Inspect the application logs; do not reset accounts."
} catch {
    $outcome = 'FAILED'
    Write-Host "FAILED AT: $stage"
    Write-Host $_.Exception.Message -ForegroundColor Red
    [Console]::Error.WriteLine($_.Exception.Message)
    if ($disabled -and -not $copyStarted -and $wasEnabled) { Enable-ScheduledTask -TaskName $taskName | Out-Null }
    if ($disabled -and $copyStarted) {
        Write-Host 'Application left stopped; no successful restart is claimed.'
        [Console]::Error.WriteLine("Application is left stopped. Source backup: $backup. Fix the reported error and rerun this updater. Databases and research history were not replaced.")
    }
    exit 1
} finally {
    # A killed process/power loss may leave an unfinished transcript, never a fake success.
    if ($transcribing) {
        Write-Host "RESULT: $outcome"
        Write-Host "Last stage: $stage"
        Write-Host "Previous installed commit: $previousCommit"
        Write-Host "Target main commit: $commit"
        Write-Host "Source backup: $backup"
        Write-Host ("Finished: {0:o}; duration: {1:N1} seconds" -f (Get-Date), ((Get-Date) - $startedAt).TotalSeconds)
        Stop-Transcript -ErrorAction Continue | Out-Null
        Write-Host "Saved update log: $logPath"
    } else { [Console]::Error.WriteLine('Update log could not be created; no update was started.') }
    if ($updateHeld) { $updateMutex.ReleaseMutex() }
    if ($null -ne $updateMutex) { $updateMutex.Dispose() }
    if ($held) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
