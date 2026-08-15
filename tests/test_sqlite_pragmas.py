from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from argos.config.settings import get_settings
from argos.database.session import create_db_engine, reset_database_caches


def test_sqlite_pragmas_are_applied(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "argos.db"
    monkeypatch.setenv("SQLITE_BUSY_TIMEOUT_MS", "12345")
    get_settings.cache_clear()
    reset_database_caches()

    engine = create_db_engine(f"sqlite:///{db_path}")

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 12345
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert connection.execute(text("PRAGMA synchronous")).scalar_one() == 1


def test_postgresql_url_does_not_attach_sqlite_connect_listener(monkeypatch) -> None:
    monkeypatch.setattr("argos.database.session.create_engine", lambda *args, **kwargs: create_engine("sqlite:///:memory:"))

    engine = create_db_engine("postgresql+psycopg://argos:argos@localhost:5432/argos")

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 0
