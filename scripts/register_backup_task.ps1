param(
  [string]$TaskName = "ARGOS Daily SQLite Backup",
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$BackupDir = $env:ARGOS_BACKUP_DIR,
  [string]$MirrorDir = $env:ARGOS_BACKUP_MIRROR_DIR,
  [string]$Time = "03:15"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($BackupDir)) {
  $BackupDir = Join-Path $RepoRoot "var\scheduled-backups"
}

$Script = Join-Path $RepoRoot "scripts\run_argos_backup.ps1"
$Args = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$Script`"",
  "-RepoRoot", "`"$RepoRoot`"",
  "-BackupDir", "`"$BackupDir`""
)

if (-not [string]::IsNullOrWhiteSpace($MirrorDir)) {
  $Args += @("-MirrorDir", "`"$MirrorDir`"")
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($Args -join " ")
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Daily ARGOS SQLite backup with manifest and integrity verification." -Force

Write-Host "Registered scheduled task '$TaskName' at $Time."
Write-Host "Backup directory: $BackupDir"
if (-not [string]::IsNullOrWhiteSpace($MirrorDir)) {
  Write-Host "Mirror directory: $MirrorDir"
}
