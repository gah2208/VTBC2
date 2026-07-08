# Version: 1.0.0
[CmdletBinding()]
param(
    [string]$Owner = 'gah2208',
    [string]$Repo = 'VTBC',
    [string]$InstallDir = 'C:\VTBC\current',
    [string]$BackupDir1 = 'C:\VTBC\backup1',
    [string]$TempDir = 'C:\VTBC\tmp',
    [string]$ReleaseAssetPattern = '*.zip',
    [switch]$RestartApp,
    [string]$AppExePath = 'C:\VTBC\current\VTBC.exe'
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

Write-Host "Starting update process..."

Ensure-Directory -Path $InstallDir
Ensure-Directory -Path $BackupDir1
Ensure-Directory -Path $TempDir

$timestamp = Get-Timestamp
$backupZip = Join-Path $BackupDir1 "install-$timestamp.zip"
$backupConfig = Join-Path $BackupDir1 'config.json'

# 1) Save current install zip + config into backup #1
Write-Host "Backing up current install..."
Compress-DirectoryToZip -SourceDir $InstallDir -ZipPath $backupZip
Copy-IfExists -Source (Join-Path $InstallDir 'config.json') -Destination $backupConfig | Out-Null

# 2) Get latest release metadata
$latestReleaseUrl = "https://api.github.com/repos/$Owner/$Repo/releases/latest"
Write-Host "Fetching latest release from $latestReleaseUrl"
$release = Invoke-RestMethod -Uri $latestReleaseUrl -Headers @{ 'User-Agent' = 'VTBC-Updater' }

if (-not $release.assets) {
    throw "No release assets found on latest release."
}

$zipAsset = $release.assets | Where-Object { $_.name -like $ReleaseAssetPattern } | Select-Object -First 1
if (-not $zipAsset) {
    throw "No asset matched pattern '$ReleaseAssetPattern'."
}

$downloadZip = Join-Path $TempDir $zipAsset.name
Write-Host "Downloading $($zipAsset.browser_download_url) -> $downloadZip"
Invoke-WebRequest -Uri $zipAsset.browser_download_url -OutFile $downloadZip -Headers @{ 'User-Agent' = 'VTBC-Updater' }

# 3) Stop app and install new zip
Stop-AppIfRunning -ExePath $AppExePath
Write-Host "Installing new version..."
Expand-ZipToDirectory -ZipPath $downloadZip -Destination $InstallDir

# 4) Load prior config into new install
$installedConfig = Join-Path $InstallDir 'config.json'
if (Test-Path -LiteralPath $backupConfig) {
    Copy-Item -LiteralPath $backupConfig -Destination $installedConfig -Force
    Write-Host "Restored config.json to new install."
} else {
    Write-Warning "No backup config.json found to restore."
}

# Optional restart
if ($RestartApp -and (Test-Path -LiteralPath $AppExePath)) {
    Start-Process -FilePath $AppExePath
}

Write-Host "Update complete. Installed release: $($release.tag_name)"