# ARGOS Windows Backup Scheduling

Estado: Vigente
Tipo: Manual operativo
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Operador ARGOS
Revision: 1

Date: 2026-08-02

ARGOS provides PowerShell scripts to run and register a daily SQLite backup. The scheduled task is not registered automatically by tests or migrations.

## Manual Backup Run

```powershell
$env:ARGOS_BACKUP_DIR = "D:\ARGOS Backups\sqlite"
$env:ARGOS_BACKUP_MIRROR_DIR = "E:\ARGOS Backups Mirror\sqlite"
.\scripts\run_argos_backup.ps1
```

The script:

- calls `scripts/backup_sqlite.py`, which uses SQLite's online backup API;
- verifies `PRAGMA integrity_check`;
- writes a SHA-256 manifest next to the `.db`;
- writes a log per execution;
- exits non-zero on failure;
- copies the `.db` and manifest to `ARGOS_BACKUP_MIRROR_DIR` when configured;
- applies retention only after a successful backup;
- keeps at least the latest valid backup.

Retention defaults:

- 14 daily backups;
- 8 weekly backups;
- 12 monthly backups.

## Register Scheduled Task

Run from an elevated PowerShell when ready:

```powershell
.\scripts\register_backup_task.ps1 `
  -TaskName "ARGOS Daily SQLite Backup" `
  -BackupDir "D:\ARGOS Backups\sqlite" `
  -MirrorDir "E:\ARGOS Backups Mirror\sqlite" `
  -Time "03:15"
```

The task runs daily through Windows Task Scheduler. It does not include secrets. Keep `.env` backups separate and encrypted.

## External Verification

A backup on the same disk does not protect against physical disk failure. Use a second disk, NAS, synced folder or other authorized external destination. Copy the database and `.manifest.json` together, and sync only after the backup script has finished writing.
