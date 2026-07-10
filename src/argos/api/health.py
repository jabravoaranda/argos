from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from argos.config.settings import get_settings
from argos.database.session import get_sessionmaker


router = APIRouter(tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, str]:
    with get_sessionmaker()() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.app_env}
