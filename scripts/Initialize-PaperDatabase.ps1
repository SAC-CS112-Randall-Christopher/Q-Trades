[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dataPath = Join-Path $projectRoot 'data'
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
$connectionPath = Join-Path $dataPath 'paper-database.json'
$environmentPath = Join-Path $dataPath 'postgres.env'
if (-not (Test-Path -LiteralPath $connectionPath)) {
    if (Test-Path -LiteralPath $environmentPath) {
        throw 'Database environment exists without connection settings. Recover settings before continuing.'
    }
    $passwordBytes = New-Object byte[] 32
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($passwordBytes) } finally { $random.Dispose() }
    $localPassword = [BitConverter]::ToString($passwordBytes).Replace('-', '').ToLowerInvariant()
    "POSTGRES_USER=paper`nPOSTGRES_DB=paper`nPOSTGRES_PASSWORD=$localPassword" |
        Set-Content -LiteralPath $environmentPath -Encoding ascii
    @{ dsn = "host=127.0.0.1 port=55432 dbname=paper user=paper password=$localPassword connect_timeout=5" } |
        ConvertTo-Json | Set-Content -LiteralPath $connectionPath -Encoding ascii
    # These are local database credentials, never exchange credentials. Restrict the files.
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    foreach ($privatePath in @($environmentPath, $connectionPath)) {
        & icacls.exe $privatePath /inheritance:r /grant:r "${identity}:(F)" 'SYSTEM:(F)' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not restrict database credential file permissions.' }
    }
}
if (-not (Test-Path -LiteralPath $environmentPath)) { throw 'Missing database environment file.' }
Push-Location $projectRoot
try {
    & docker compose up -d --wait paper-db
    if ($LASTEXITCODE -ne 0) { throw 'Paper database did not become healthy.' }
} finally { Pop-Location }
Write-Output 'Dedicated paper database ready on loopback port 55432.'
