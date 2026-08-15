param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$BackupDir = $env:ARGOS_BACKUP_DIR,
  [string]$MirrorDir = $env:ARGOS_BACKUP_MIRROR_DIR,
  [int]$DailyRetention = 14,
  [int]$WeeklyRetention = 8,
  [int]$MonthlyRetention = 12
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($BackupDir)) {
  $BackupDir = Join-Path $RepoRoot "var\scheduled-backups"
}

$BackupDir = (New-Item -ItemType Directory -Path $BackupDir -Force).FullName
$LogDir = New-Item -ItemType Directory -Path (Join-Path $BackupDir "logs") -Force
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$LogPath = Join-Path $LogDir.FullName "argos-backup-$Stamp.log"

function Write-BackupLog {
  param([string]$Message)
  $Line = "$(Get-Date -Format o) $Message"
  Add-Content -Path $LogPath -Value $Line
  Write-Host $Line
}

function Invoke-Retention {
  param(
    [string]$BackupDir,
    [int]$DailyRetention,
    [int]$WeeklyRetention,
    [int]$MonthlyRetention
  )

  $Backups = Get-ChildItem -Path $BackupDir -Filter "argos-*.db" | Sort-Object LastWriteTimeUtc -Descending
  if ($Backups.Count -le 1) {
    return
  }

  $Keep = New-Object "System.Collections.Generic.HashSet[string]"
  foreach ($Item in ($Backups | Select-Object -First $DailyRetention)) {
    [void]$Keep.Add($Item.FullName)
  }

  foreach ($Group in ($Backups | Group-Object { $_.LastWriteTimeUtc.ToString("yyyy-ww") })) {
    $Item = $Group.Group | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    [void]$Keep.Add($Item.FullName)
  }

  foreach ($Group in ($Backups | Group-Object { $_.LastWriteTimeUtc.ToString("yyyy-MM") })) {
    $Item = $Group.Group | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    [void]$Keep.Add($Item.FullName)
  }

  $WeeklyKeep = ($Backups | Group-Object { $_.LastWriteTimeUtc.ToString("yyyy-ww") } |
    ForEach-Object { $_.Group | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1 } |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First $WeeklyRetention)
  foreach ($Item in $WeeklyKeep) {
    [void]$Keep.Add($Item.FullName)
  }

  $MonthlyKeep = ($Backups | Group-Object { $_.LastWriteTimeUtc.ToString("yyyy-MM") } |
    ForEach-Object { $_.Group | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1 } |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First $MonthlyRetention)
  foreach ($Item in $MonthlyKeep) {
    [void]$Keep.Add($Item.FullName)
  }

  foreach ($Backup in $Backups) {
    if ($Keep.Contains($Backup.FullName)) {
      continue
    }
    $Manifest = $Backup.FullName + ".manifest.json"
    Remove-Item -LiteralPath $Backup.FullName -Force
    if (Test-Path -LiteralPath $Manifest) {
      Remove-Item -LiteralPath $Manifest -Force
    }
    Write-BackupLog "Removed old backup $($Backup.FullName)."
  }
}

try {
  Write-BackupLog "Starting ARGOS SQLite backup."
  Push-Location $RepoRoot
  uv run python scripts\backup_sqlite.py --backup-dir $BackupDir 2>&1 | Tee-Object -FilePath $LogPath -Append
  Pop-Location

  $LatestBackup = Get-ChildItem -Path $BackupDir -Filter "argos-*.db" |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
  if ($null -eq $LatestBackup) {
    throw "No backup file was created."
  }
  $Manifest = Get-Item -LiteralPath ($LatestBackup.FullName + ".manifest.json")
  if ($null -eq $Manifest) {
    throw "Backup manifest missing: $($LatestBackup.FullName).manifest.json"
  }

  Write-BackupLog "Created $($LatestBackup.FullName)."

  if (-not [string]::IsNullOrWhiteSpace($MirrorDir)) {
    $MirrorDir = (New-Item -ItemType Directory -Path $MirrorDir -Force).FullName
    Copy-Item -LiteralPath $LatestBackup.FullName -Destination $MirrorDir -Force
    Copy-Item -LiteralPath $Manifest.FullName -Destination $MirrorDir -Force
    Write-BackupLog "Copied backup and manifest to mirror $MirrorDir."
  }

  Invoke-Retention -BackupDir $BackupDir -DailyRetention $DailyRetention -WeeklyRetention $WeeklyRetention -MonthlyRetention $MonthlyRetention
  Write-BackupLog "Backup completed successfully."
  exit 0
}
catch {
  Write-BackupLog "Backup failed: $($_.Exception.Message)"
  exit 1
}
