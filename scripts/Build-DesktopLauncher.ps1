[CmdletBinding()]
param([switch] $InstallDesktop, [string] $RuntimeRoot)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$compiler = Join-Path ([Environment]::GetFolderPath('Windows')) 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$buildPath = Join-Path $projectRoot 'data\desktop-launcher-build'
$sourcePath = Join-Path $PSScriptRoot 'TradingDashboardLauncher.cs'
$generatedPath = Join-Path $buildPath 'TradingDashboardLauncher.cs'
if ($RuntimeRoot) {
    $RuntimeRoot = (Resolve-Path -LiteralPath $RuntimeRoot).Path
    if ($RuntimeRoot.Contains('"')) { throw 'Invalid runtime path.' }
    if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot 'data') -PathType Container)) {
        throw 'Existing runtime data is missing.'
    }
}
$exePath = Join-Path $buildPath 'Trading Research.exe'

if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw 'The installed Windows .NET Framework C# compiler was not found. Nothing was downloaded.'
}
New-Item -ItemType Directory -Path $buildPath -Force | Out-Null
$source = [IO.File]::ReadAllText($sourcePath).Replace('{{PROJECT_ROOT}}', $projectRoot.Replace('"', '""'))
$runtimeToken = if ($RuntimeRoot) { $RuntimeRoot.Replace('"', '""') } else { '' }
$source = $source.Replace('{{RUNTIME_ROOT}}', $runtimeToken)
[IO.File]::WriteAllText($generatedPath, $source, [Text.Encoding]::UTF8)
& $compiler '/nologo' '/target:winexe' '/platform:anycpu' '/optimize+' '/warnaserror+' `
    '/reference:System.Windows.Forms.dll' '/reference:System.Drawing.dll' `
    "/out:$exePath" $generatedPath
if ($LASTEXITCODE -ne 0) { throw "Launcher compilation failed with exit code $LASTEXITCODE." }

$installedPath = $null
if ($InstallDesktop) {
    $desktopPath = [Environment]::GetFolderPath('Desktop')
    if (-not $desktopPath -or -not (Test-Path -LiteralPath $desktopPath -PathType Container)) {
        throw 'The current Windows user desktop folder is unavailable.'
    }
    $installedPath = Join-Path $desktopPath 'Trading Research.exe'
    if (Test-Path -LiteralPath $installedPath) {
        throw "A desktop file already exists at $installedPath. It was preserved; the new build is at $exePath."
    }
    Copy-Item -LiteralPath $exePath -Destination $installedPath
    if ((Get-FileHash -LiteralPath $exePath).Hash -ne (Get-FileHash -LiteralPath $installedPath).Hash) {
        throw 'Desktop copy verification failed.'
    }
}
[pscustomobject]@{
    Executable = $exePath
    DesktopExecutable = $installedPath
    Bytes = (Get-Item -LiteralPath $exePath).Length
    SHA256 = (Get-FileHash -LiteralPath $exePath).Hash
    Project = $projectRoot
} | ConvertTo-Json
