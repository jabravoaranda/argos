from __future__ import annotations

from fastapi import FastAPI

from argos.api.ecowitt import router as ecowitt_router
from argos.api.health import router as health_router
from argos.api.weather import router as weather_router
from argos.config.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ARGOS",
        description="Agricultural Remote Gateway for Observation and Sensing",
        version="0.1.0",
    )
    app.state.settings = settings
    app.include_router(health_router)
    app.include_router(ecowitt_router)
    app.include_router(weather_router)
    return app


app = create_app()
