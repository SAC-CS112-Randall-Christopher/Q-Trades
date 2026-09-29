# Import only the reviewed, hash-verified Q-Trades bundle. Requires git and an
# authenticated GitHub CLI. This creates a NEW private repository; it never
# rewrites an existing local checkout or changes an existing repository's privacy.
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository = 'SAC-CS112-Randall-Christopher/Q-Trades'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Run-Native {
    param([string]$Program, [string[]]$Arguments)
    $result = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE). No automatic cleanup or retry was performed." }
    return $result
}
foreach ($tool in @('git', 'gh')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is required. Install it, then authenticate GitHub with 'gh auth login'. Do not paste credentials into chat."
    }
}
$root = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $root '.qtrades-import-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw 'Run the copy of this script inside scripts/ in the extracted Q-Trades-reviewed bundle.'
}
Push-Location $root
try {
    if (Test-Path -LiteralPath '.git') { throw 'Existing .git found. Refusing to alter an existing checkout.' }
    $priorErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & git rev-parse --show-toplevel 2>$null | Out-Null
    $insideCheckout = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $priorErrorPreference
    if ($insideCheckout) { throw 'This folder is inside an existing Git checkout. Extract it into a separate directory.' }
    Run-Native 'gh' @('auth', 'status') | Out-Host
    $login = (Run-Native 'gh' @('api', 'user', '--jq', '.login')).Trim()
    if ($login -ne ($Repository -split '/')[0]) {
        throw "The authenticated GitHub user is not the requested repository owner. Select the correct account before proceeding."
    }
    $gitName = Run-Native 'git' @('config', '--get', 'user.name')
    $gitEmail = Run-Native 'git' @('config', '--get', 'user.email')
    if (-not $gitName -or -not $gitEmail) { throw 'Set your Git commit name and email locally before importing.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $manifest.files) {
        $relative = [string]$entry.path
        if ($relative -match '(^/|^[A-Za-z]:|\\|(^|/)\.\.(/|$)|(^|/)(data|\.git|node_modules|\.venv|__pycache__)(/|$)|\.(woff2?|ttf|otf|db|sqlite3?|log)$)') {
            throw "Disallowed manifest path: $relative"
        }
        $filePath = Join-Path $root $relative
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) { throw "Missing manifest file: $relative" }
        if ((Get-Item -LiteralPath $filePath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Link/reparse point refused: $relative"
        }
        $actual = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $entry.sha256) { throw "File changed since review: $relative. Review the change before publishing." }
    }
    Run-Native 'git' @('init', '-b', 'main') | Out-Host
    foreach ($entry in $manifest.files) { Run-Native 'git' @('add', '--', [string]$entry.path) | Out-Null }
    Run-Native 'git' @('add', '--', '.qtrades-import-manifest.json') | Out-Null
    $staged = @(Run-Native 'git' @('diff', '--cached', '--name-only'))
    if ($staged.Count -ne ($manifest.files.Count + 1)) { throw 'Unexpected staged file count; no push was attempted.' }
    Run-Native 'git' @('commit', '-m', 'Import reviewed Q-Trades snapshot with evidence-backed improvement plan') | Out-Host
    # Create without --push: verify privacy BEFORE sending source code.
    Run-Native 'gh' @('repo', 'create', $Repository, '--private', '--description', 'Paper-only quantitative research, deterministic accounting, and evidence-backed strategy evaluation') | Out-Host
    $private = (Run-Native 'gh' @('api', "repos/$Repository", '--jq', '.private')).Trim()
    if ($private -ne 'true') { throw 'Private visibility could not be verified. No source was pushed.' }
    Run-Native 'git' @('remote', 'add', 'origin', "https://github.com/$Repository.git") | Out-Host
    Run-Native 'git' @('-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential', 'push', '--set-upstream', 'origin', 'main') | Out-Host
    $localSha = (Run-Native 'git' @('rev-parse', 'HEAD')).Trim()
    $remoteSha = (Run-Native 'gh' @('api', "repos/$Repository/branches/main", '--jq', '.commit.sha')).Trim()
    $stillPrivate = (Run-Native 'gh' @('api', "repos/$Repository", '--jq', '.private')).Trim()
    if ($localSha -ne $remoteSha -or $stillPrivate -ne 'true') { throw 'Post-push verification did not match. Inspect GitHub before further writes.' }
    Write-Output "Verified private repository: https://github.com/$Repository"
    Write-Output "Verified main commit: $remoteSha"
    Write-Output 'No trading runtime, cloud service, deployment, paid call, or account funding was started.'
} finally { Pop-Location }
