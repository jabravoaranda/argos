from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path
import sqlite3

from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from argos.config.settings import get_settings


def create_db_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    url = database_url or settings.database_url
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False}
    else:
        connect_args = {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite:///"):
        _configure_sqlite_connections(engine, busy_timeout_ms=settings.sqlite_busy_timeout_ms)
    return engine


def _configure_sqlite_connections(engine: Engine, *, busy_timeout_ms: int) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        if not isinstance(dbapi_connection, sqlite3.Connection):
            return
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


@lru_cache
def get_engine(database_url: str | None = None) -> Engine:
    return create_db_engine(database_url)


@lru_cache
def get_sessionmaker(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, autocommit=False, future=True)


def reset_database_caches() -> None:
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


def get_db_session() -> Generator[Session, None, None]:
    with get_sessionmaker()() as session:
        yield session
