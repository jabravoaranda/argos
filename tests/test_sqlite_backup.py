from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from argos.ops.sqlite_backup import (
    SqliteBackupError,
    create_sqlite_backup,
    restore_sqlite_backup,
    sha256_file,
    sqlite_path_from_database_url,
)


def create_sample_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num TEXT NOT NULL);
            INSERT INTO alembic_version VALUES ('test_revision');
            CREATE TABLE weather_observations (id INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO weather_observations (value) VALUES ('one'), ('two');
            CREATE TABLE satellite_assets (id INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO satellite_assets (value) VALUES ('asset');
            """
        )


def test_sqlite_path_from_database_url_resolves_relative_paths(tmp_path: Path) -> None:
    assert sqlite_path_from_database_url("sqlite:///argos.db", cwd=tmp_path) == (tmp_path / "argos.db").resolve()


def test_sqlite_path_from_database_url_rejects_non_sqlite() -> None:
    with pytest.raises(SqliteBackupError, match="Only SQLite"):
        sqlite_path_from_database_url("postgresql+psycopg://argos:argos@localhost/argos")


def test_create_backup_and_restore_with_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    target = tmp_path / "restored.db"
    create_sample_db(source)

    result = create_sqlite_backup(
        database_url=f"sqlite:///{source}",
        backup_dir=backup_dir,
        timestamp=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
    )

    assert result.backup_path.exists()
    assert result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["integrity_check"] == "ok"
    assert manifest["alembic_revision"] == "test_revision"
    assert manifest["row_counts"]["weather_observations"] == 2
    assert manifest["row_counts"]["satellite_assets"] == 1
    assert manifest["sha256"] == sha256_file(result.backup_path)

    restored = restore_sqlite_backup(backup_path=result.backup_path, target_path=target)

    assert target.exists()
    assert restored["integrity_check"] == "ok"
    assert restored["alembic_revision"] == "test_revision"
    assert restored["row_counts"] == manifest["row_counts"]


def test_restore_rejects_corrupt_backup(tmp_path: Path) -> None:
    backup = tmp_path / "broken.db"
    target = tmp_path / "target.db"
    backup.write_bytes(b"not a sqlite database")

    with pytest.raises(SqliteBackupError, match="not a valid SQLite"):
        restore_sqlite_backup(backup_path=backup, target_path=target)

    assert not target.exists()


def test_restore_does_not_overwrite_without_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    create_sample_db(source)
    create_sample_db(target)
    result = create_sqlite_backup(database_url=f"sqlite:///{source}", backup_dir=tmp_path / "backups")

    with pytest.raises(SqliteBackupError, match="Target already exists"):
        restore_sqlite_backup(backup_path=result.backup_path, target_path=target)
