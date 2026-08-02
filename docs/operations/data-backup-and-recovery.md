# ARGOS Data Backup and Recovery

## Irrecoverable Data

Protect these files first:

- `var/argos.db`: active SQLite database with normalized observations, raw SQL payloads, manual events, sync state and derived rows.
- `data/weather`: legacy local weather files until they are reconciled with SQL.
- `data/aemet`: local AEMET CSV seeds until they are confirmed reproducible.
- `data/satellite`: satellite preview assets referenced from SQL by path and checksum.
- `.env`: secrets and local configuration. Do not put it in normal data backups; store it separately in an encrypted secret manager.

A copy on the same disk is not enough. It protects against operator mistakes, but not disk failure, theft, ransomware or machine loss. Sync backups to a second physical disk, NAS, or external service.

## Create a SQLite Backup

Set an external backup directory:

```powershell
$env:ARGOS_BACKUP_DIR = "D:\ARGOS Backups\sqlite"
```

Run:

```powershell
python scripts/backup_sqlite.py
```

The script resolves `DATABASE_URL`, uses SQLite's online backup API, writes a timestamped `.db`, verifies `PRAGMA integrity_check`, computes SHA-256, and creates a JSON manifest next to the backup.

For an explicit database:

```powershell
python scripts/backup_sqlite.py --database-url "sqlite:///./var/argos.db" --backup-dir "D:\ARGOS Backups\sqlite"
```

## Verify a Backup

Inspect the manifest:

```powershell
Get-Content "D:\ARGOS Backups\sqlite\argos-YYYYMMDDTHHMMSSZ.db.manifest.json"
```

The important fields are:

- `integrity_check`: must be `ok`.
- `sha256`: checksum of the copied database.
- `alembic_revision`: must match the expected ARGOS schema revision.
- `row_counts`: quick sanity check for main tables.

## Restore to a Temporary Path

Always restore first to a separate file:

```powershell
python scripts/restore_sqlite.py `
  --backup "D:\ARGOS Backups\sqlite\argos-YYYYMMDDTHHMMSSZ.db" `
  --target "C:\Temp\argos-restore-check.db"
```

The restore command verifies SHA-256 when a manifest exists, runs `PRAGMA integrity_check`, checks the Alembic revision from the manifest, and prints row counts.

It refuses to overwrite an existing target unless `--overwrite` is passed:

```powershell
python scripts/restore_sqlite.py `
  --backup "D:\ARGOS Backups\sqlite\argos-YYYYMMDDTHHMMSSZ.db" `
  --target "C:\Temp\argos-restore-check.db" `
  --overwrite
```

## Replace the Active Database Safely

Stop ARGOS first. Do not replace `var/argos.db` while the API, dashboard workers, or CLI importers are writing.

Example:

```powershell
# 1. Stop ARGOS processes.
Get-Process | Where-Object { $_.ProcessName -match "python|uvicorn|streamlit" }

# 2. Restore to a temporary file and verify output.
python scripts/restore_sqlite.py `
  --backup "D:\ARGOS Backups\sqlite\argos-YYYYMMDDTHHMMSSZ.db" `
  --target "C:\Temp\argos-restored.db" `
  --overwrite

# 3. Keep a last-resort copy of the current active DB.
Copy-Item ".\var\argos.db" ".\var\argos.before-restore.$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')).db"

# 4. Replace the active DB.
Copy-Item "C:\Temp\argos-restored.db" ".\var\argos.db" -Force

# 5. Start ARGOS and verify health.
uv run alembic current
uv run uvicorn argos.main:app --host 0.0.0.0 --port 8080
```

## Additional Directories

Keep database backups outside the operational `data/` tree. A copy on the same disk is not sufficient; sync to a second physical location.

Copy these alongside database backups:

```powershell
robocopy ".\data" "D:\ARGOS Backups\data" /MIR /XD cache staging
```

Minimum data backup scope:

- SQL database.
- `data/raw`.
- `data/legacy`.
- `data/quarantine`.
- `data/processed/satellite` while preview regeneration remains conditional.
- `var/manifests`.
- non-secret reconstruction configuration.

Secrets from `.env` must be backed up separately and encrypted.

If `data/satellite` or `data/processed/satellite` is omitted, SQL metrics remain available, but preview image endpoints may return missing files. If legacy `data/weather` or AEMET CSVs are omitted before reconciliation, local-only historical evidence may be lost.

## Second Location Sync

Examples:

```powershell
robocopy "D:\ARGOS Backups" "E:\ARGOS Backups Mirror" /MIR
```

or to a synced cloud folder:

```powershell
robocopy "D:\ARGOS Backups" "$env:USERPROFILE\OneDrive\ARGOS Backups" /MIR
```

Do not sync `.env` into ordinary cloud folders unless it is encrypted.

## Retention

Recommended minimum:

- 14 daily backups.
- 8 weekly backups.
- 12 monthly backups.

This phase does not install an automatic Windows schedule. Add scheduling only after manual backup and restore have been verified.

Use this report before any future cleanup:

```powershell
argos data retention-report
argos data audit-staging
```

Neither command deletes files in the current phase.

## Windows Scheduling

Daily Windows scheduling is documented in `docs/operations/windows-backup-scheduling.md` and implemented by:

```powershell
.\scripts\run_argos_backup.ps1
.\scripts\register_backup_task.ps1
```

Do not register the scheduled task until the backup destination and mirror location are confirmed.

## Monthly Restore Drill

Once per month:

1. Pick the latest monthly backup.
2. Restore it to `C:\Temp\argos-monthly-restore.db`.
3. Confirm `integrity_check: ok`.
4. Compare `alembic_revision` and row counts with the manifest.
5. Start ARGOS against the temporary DB in a separate shell:

```powershell
$env:DATABASE_URL = "sqlite:///C:/Temp/argos-monthly-restore.db"
uv run alembic current
uv run pytest tests/test_api_health.py tests/test_weather_api.py
```

6. Delete the temporary restore only after recording the result.
