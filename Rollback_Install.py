# Version: 1.0.0
[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\VTBC\current',
    [string]$BackupDir1 = 'C:\VTBC\backup1',
    [string]$BackupDir2 = 'C:\VTBC\backup2',
    [string]$AppExePath = 'C:\VTBC\current\VTBC.exe',
    [switch]$RestartApp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\Common-Install.ps1"

function Stop-AppIfRunning {
    param([string]$ExePath)

    $procName = [System.IO.Path]::GetFileNameWithoutExtension($ExePath)
    $procs = Get-Process -Name $procName -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force
        Start-Sleep -Seconds 2
    }
}

Write-Host "Starting rollback process..."

Ensure-Directory -Path $InstallDir
Ensure-Directory -Path $BackupDir1
Ensure-Directory -Path $BackupDir2

$timestamp = Get-Timestamp

# 1) Save current install into backup #2
$currentToB2Zip = Join-Path $BackupDir2 "install-$timestamp.zip"
$currentToB2Config = Join-Path $BackupDir2 'config.json'

Compress-DirectoryToZip -SourceDir $InstallDir -ZipPath $currentToB2Zip
Copy-IfExists -Source (Join-Path $InstallDir 'config.json') -Destination $currentToB2Config | Out-Null

# 2) Restore from backup #1
$restoreZip = Get-ChildItem -LiteralPath $BackupDir1 -Filter '*.zip' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $restoreZip) {
    throw "No rollback zip found in backup directory #1 ($BackupDir1)."
}

$backup1Config = Join-Path $BackupDir1 'config.json'
if (-not (Test-Path -LiteralPath $backup1Config)) {
    Write-Warning "backup #1 config.json not found; restore will continue without config restore."
}

Stop-AppIfRunning -ExePath $AppExePath
Expand-ZipToDirectory -ZipPath $restoreZip.FullName -Destination $InstallDir

# 3) Load config from backup #1
if (Test-Path -LiteralPath $backup1Config) {
    Copy-Item -LiteralPath $backup1Config -Destination (Join-Path $InstallDir 'config.json') -Force
}

# 4) Move backup #2 artifacts into backup #1
Move-Item -LiteralPath $currentToB2Zip -Destination (Join-Path $BackupDir1 (Split-Path $currentToB2Zip -Leaf)) -Force
if (Test-Path -LiteralPath $currentToB2Config) {
    Move-Item -LiteralPath $currentToB2Config -Destination (Join-Path $BackupDir1 'config.json') -Force
}

if ($RestartApp -and (Test-Path -LiteralPath $AppExePath)) {
    Start-Process -FilePath $AppExePath
}

Write-Host "Rollback complete."