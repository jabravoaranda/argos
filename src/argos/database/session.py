from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from argos.config.settings import get_settings


def create_db_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False}
    else:
        connect_args = {}
    return create_engine(url, future=True, connect_args=connect_args)


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
