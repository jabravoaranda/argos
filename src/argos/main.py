from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from threading import Event, Thread

from fastapi import FastAPI

from argos.api.analytics import router as analytics_router
from argos.api.ecowitt import router as ecowitt_router
from argos.api.field_events import router as field_events_router
from argos.api.health import router as health_router
from argos.api.satellite import router as satellite_router
from argos.api.weather import router as weather_router
from argos.config.settings import get_settings
from argos.dashboard.argos_node_client import ArgosNodeClient
from argos.database.session import get_sessionmaker
from argos.services.argos_node_flowmeter import run_flowmeter_minute_capture
from argos.services.scheduled_sync import run_daily_data_sync_worker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Iterator[None]:
    settings = app.state.settings
    workers: list[tuple[Thread, Event, float]] = []
    if settings.argos_node_url:
        stop_event = Event()
        worker = Thread(
            target=_run_flowmeter_worker,
            kwargs={"node_url": settings.argos_node_url, "stop_event": stop_event},
            name="argos-node-flowmeter-capture",
            daemon=True,
        )
        worker.start()
        workers.append((worker, stop_event, max(1.0, settings.argos_node_poll_interval_seconds + 1.0)))
        app.state.argos_node_flowmeter_worker = worker
        app.state.argos_node_flowmeter_stop_event = stop_event
        logger.info("started argos-node flowmeter capture worker")
    if getattr(settings, "argos_daily_sync_enabled", False):
        stop_event = Event()
        worker = Thread(
            target=_run_daily_data_sync_worker,
            kwargs={"stop_event": stop_event},
            name="argos-daily-data-sync",
            daemon=True,
        )
        worker.start()
        sync_interval_hours = float(getattr(settings, "argos_daily_sync_interval_hours", 24.0))
        workers.append((worker, stop_event, max(1.0, sync_interval_hours * 3600.0 + 1.0)))
        app.state.argos_daily_sync_worker = worker
        app.state.argos_daily_sync_stop_event = stop_event
        logger.info("started daily data sync worker")
    try:
        yield
    finally:
        for _worker, stop_event, _timeout in workers:
            stop_event.set()
        for worker, _stop_event, timeout in workers:
            worker.join(timeout=timeout)
            logger.info("stopped worker %s", worker.name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ARGOS",
        description="Agricultural Remote Gateway for Observation and Sensing",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(health_router)
    app.include_router(ecowitt_router)
    app.include_router(weather_router)
    app.include_router(satellite_router)
    app.include_router(field_events_router)
    app.include_router(analytics_router)
    return app


def _run_flowmeter_worker(*, node_url: str, stop_event: Event) -> None:
    settings = get_settings()
    try:
        run_flowmeter_minute_capture(
            session_factory=get_sessionmaker(),
            client=ArgosNodeClient(base_url=node_url, timeout_seconds=settings.argos_node_timeout_seconds),
            poll_interval_seconds=settings.argos_node_poll_interval_seconds,
            stop_event=stop_event,
            hydrological_year_reset_month=settings.argos_flowmeter_hydrological_year_reset_month,
            hydrological_year_reset_day=settings.argos_flowmeter_hydrological_year_reset_day,
        )
    except Exception:
        logger.exception("argos-node flowmeter capture worker stopped unexpectedly")


def _run_daily_data_sync_worker(*, stop_event: Event) -> None:
    settings = get_settings()
    try:
        run_daily_data_sync_worker(
            session_factory=get_sessionmaker(),
            stop_event=stop_event,
            interval_hours=settings.argos_daily_sync_interval_hours,
            settings=settings,
        )
    except Exception:
        logger.exception("daily data sync worker stopped unexpectedly")


app = create_app()
