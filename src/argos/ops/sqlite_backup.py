from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

MAIN_TABLES = (
    "stations",
    "gateways",
    "ecowitt_raw_reports",
    "ecowitt_cloud_raw_reports",
    "weather_observations",
    "weather_daily_observations",
    "aemet_sync_runs",
    "satellite_observations",
    "satellite_metrics",
    "satellite_assets",
    "argos_node_flowmeter_minutes",
    "argos_node_flowmeter_sessions",
    "argos_node_flowmeter_reset_events",
    "field_events",
    "ingestion_events",
    "data_gaps",
)


class SqliteBackupError(RuntimeError):
    """Raised when a SQLite backup or restore cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class BackupResult:
    backup_path: Path
    manifest_path: Path
    manifest: dict


def sqlite_path_from_database_url(database_url: str, *, cwd: Path | None = None) -> Path:
    if not database_url.startswith("sqlite:"):
        engine = database_url.split(":", 1)[0] or database_url
        raise SqliteBackupError(f"Only SQLite DATABASE_URL values are supported, got: {engine}")
    if database_url in {"sqlite://", "sqlite:///:memory:", "sqlite:///:memory"}:
        raise SqliteBackupError("In-memory SQLite databases cannot be backed up with this command.")
    if database_url.startswith("sqlite:///"):
        raw_path = unquote(database_url.removeprefix("sqlite:///"))
    elif database_url.startswith("sqlite:////"):
        raw_path = "/" + unquote(database_url.removeprefix("sqlite:////"))
    else:
        raise SqliteBackupError("Only file-based sqlite:/// DATABASE_URL values are supported.")
    path = Path(raw_path)
    if not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    return path.resolve()


def create_sqlite_backup(
    *,
    database_url: str,
    backup_dir: Path,
    timestamp: datetime | None = None,
) -> BackupResult:
    source_path = sqlite_path_from_database_url(database_url)
    if not source_path.exists():
        raise SqliteBackupError(f"SQLite database does not exist: {source_path}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    created_at = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
    backup_path = _next_backup_path(backup_dir, created_at)
    manifest_path = backup_path.with_suffix(backup_path.suffix + ".manifest.json")

    try:
        with sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as source:
            with sqlite3.connect(backup_path) as destination:
                source.backup(destination)
        manifest = build_manifest(source_path=source_path, backup_path=backup_path, created_at=created_at)
        if manifest["integrity_check"] != "ok":
            backup_path.unlink(missing_ok=True)
            raise SqliteBackupError(f"Backup integrity check failed: {manifest['integrity_check']}")
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        if backup_path.exists():
            backup_path.unlink(missing_ok=True)
        if manifest_path.exists():
            manifest_path.unlink(missing_ok=True)
        raise

    return BackupResult(backup_path=backup_path, manifest_path=manifest_path, manifest=manifest)


def restore_sqlite_backup(
    *,
    backup_path: Path,
    target_path: Path,
    allow_overwrite: bool = False,
) -> dict:
    backup_path = backup_path.resolve()
    target_path = target_path.resolve()
    if not backup_path.exists():
        raise SqliteBackupError(f"Backup file does not exist: {backup_path}")
    manifest = read_manifest_for_backup(backup_path)
    if manifest is not None:
        expected_sha = manifest.get("sha256")
        actual_sha = sha256_file(backup_path)
        if expected_sha and expected_sha != actual_sha:
            raise SqliteBackupError("Backup SHA-256 does not match manifest.")
    if target_path.exists() and not allow_overwrite:
        raise SqliteBackupError(f"Target already exists; pass --overwrite to replace it: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target_path.with_name(target_path.name + ".restore-tmp")
    if temp_target.exists():
        temp_target.unlink()
    shutil.copy2(backup_path, temp_target)
    try:
        restored_manifest = inspect_sqlite_database(temp_target)
    except sqlite3.DatabaseError as exc:
        temp_target.unlink(missing_ok=True)
        raise SqliteBackupError(f"Backup is not a valid SQLite database: {backup_path}") from exc
    if restored_manifest["integrity_check"] != "ok":
        temp_target.unlink(missing_ok=True)
        raise SqliteBackupError(f"Restored database integrity check failed: {restored_manifest['integrity_check']}")
    if manifest is not None and manifest.get("alembic_revision") != restored_manifest.get("alembic_revision"):
        temp_target.unlink(missing_ok=True)
        raise SqliteBackupError("Restored database Alembic revision does not match manifest.")
    if target_path.exists():
        target_path.unlink()
    temp_target.replace(target_path)
    restored_manifest["target_path"] = str(target_path)
    return restored_manifest


def build_manifest(*, source_path: Path, backup_path: Path, created_at: datetime) -> dict:
    inspected = inspect_sqlite_database(backup_path)
    return {
        "source_path": str(source_path),
        "backup_path": str(backup_path.resolve()),
        "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
        "size_bytes": backup_path.stat().st_size,
        "sha256": sha256_file(backup_path),
        **inspected,
    }


def inspect_sqlite_database(path: Path) -> dict:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        return {
            "integrity_check": integrity[0] if integrity else "missing",
            "alembic_revision": _alembic_revision(connection),
            "row_counts": table_row_counts(connection, MAIN_TABLES),
        }
    finally:
        connection.close()


def table_row_counts(connection: sqlite3.Connection, table_names: tuple[str, ...] = MAIN_TABLES) -> dict[str, int]:
    existing = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    counts: dict[str, int] = {}
    for table_name in table_names:
        if table_name in existing:
            counts[table_name] = int(connection.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0])
    return counts


def read_manifest_for_backup(backup_path: Path) -> dict | None:
    manifest_path = backup_path.with_suffix(backup_path.suffix + ".manifest.json")
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a consistent online backup of the ARGOS SQLite database.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "sqlite:///./var/argos.db"))
    parser.add_argument("--backup-dir", default=os.environ.get("ARGOS_BACKUP_DIR", "./backups/sqlite"))
    args = parser.parse_args(argv)
    try:
        result = create_sqlite_backup(database_url=args.database_url, backup_dir=Path(args.backup_dir))
    except SqliteBackupError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Backup: {result.backup_path}")
    print(f"Manifest: {result.manifest_path}")
    print(f"Integrity: {result.manifest['integrity_check']}")
    print(f"Alembic revision: {result.manifest['alembic_revision'] or '-'}")
    print(f"SHA-256: {result.manifest['sha256']}")
    return 0


def restore_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore and verify an ARGOS SQLite backup to a target path.")
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = restore_sqlite_backup(backup_path=args.backup, target_path=args.target, allow_overwrite=args.overwrite)
    except SqliteBackupError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Restored: {result['target_path']}")
    print(f"Integrity: {result['integrity_check']}")
    print(f"Alembic revision: {result['alembic_revision'] or '-'}")
    print("Row counts:")
    for table_name, count in result["row_counts"].items():
        print(f"  {table_name}: {count}")
    return 0


def _alembic_revision(connection: sqlite3.Connection) -> str | None:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
    ).fetchone()
    if not exists:
        return None
    row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
    return str(row[0]) if row else None


def _next_backup_path(backup_dir: Path, created_at: datetime) -> Path:
    stem = f"argos-{created_at.strftime('%Y%m%dT%H%M%SZ')}"
    candidate = backup_dir / f"{stem}.db"
    counter = 1
    while candidate.exists() or candidate.with_suffix(candidate.suffix + ".manifest.json").exists():
        candidate = backup_dir / f"{stem}-{counter}.db"
        counter += 1
    return candidate
