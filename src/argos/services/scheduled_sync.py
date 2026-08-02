from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from argos.config.settings import Settings, get_settings
from argos.integrations.aemet.client import AemetClient, AemetConfigError, AemetError
from argos.integrations.ecowitt_cloud import EcowittCloudClient, EcowittCloudConfigError, EcowittCloudError
from argos.repositories.weather import WeatherRepository
from argos.services.aemet_import import AemetImportRangeError, AemetImportService
from argos.services.ecowitt_backfill import BackfillRangeError, backfill_ecowitt_cloud_range
from argos.services.satellite_ingestion import SatelliteIngestionService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncTaskResult:
    name: str
    status: str
    message: str
    details: dict[str, int | float | str | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DailySyncResult:
    started_at_utc: datetime
    finished_at_utc: datetime
    tasks: list[SyncTaskResult]


def run_daily_data_sync_once(
    *,
    session: Session,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> DailySyncResult:
    settings = settings or get_settings()
    started_at = _as_utc(now or datetime.now(UTC))
    tasks = [
        sync_ecowitt_cloud_recent(session=session, settings=settings, now=started_at),
        sync_aemet_recent(session=session, settings=settings),
        sync_satellite_recent(session=session, settings=settings),
    ]
    return DailySyncResult(started_at_utc=started_at, finished_at_utc=datetime.now(UTC), tasks=tasks)


def run_daily_data_sync_worker(
    *,
    session_factory: sessionmaker[Session],
    stop_event: Event,
    interval_hours: float,
    settings: Settings | None = None,
    now: Callable[[], datetime] | None = None,
) -> None:
    settings = settings or get_settings()
    clock = now or (lambda: datetime.now(UTC))
    interval_seconds = max(60.0, interval_hours * 3600.0)
    while not stop_event.is_set():
        with session_factory() as session:
            result = run_daily_data_sync_once(session=session, settings=settings, now=clock())
        for task in result.tasks:
            logger.info("daily data sync task", extra={"task": task.name, "status": task.status, **task.details})
        stop_event.wait(interval_seconds)


def sync_ecowitt_cloud_recent(*, session: Session, settings: Settings, now: datetime) -> SyncTaskResult:
    if not (
        settings.ecowitt_cloud_application_key
        and settings.ecowitt_cloud_api_key
        and settings.ecowitt_cloud_mac
    ):
        return SyncTaskResult("ecowitt", "skipped", "Ecowitt Cloud credentials are not configured.")

    latest_gateway = WeatherRepository(session).latest_gateway()
    gateway_identifier = latest_gateway.mac_address if latest_gateway is not None else settings.ecowitt_cloud_mac
    station_type = latest_gateway.station_type if latest_gateway is not None else None
    end = _as_utc(now)
    start = end - timedelta(hours=settings.ecowitt_cloud_sync_lookback_hours)
    try:
        result = backfill_ecowitt_cloud_range(
            session=session,
            client=EcowittCloudClient.from_settings(settings),
            gateway_identifier=gateway_identifier,
            station_slug=settings.station_slug,
            station_type=station_type,
            gateway_aliases={"ecowitt_cloud_mac": settings.ecowitt_cloud_mac},
            start=start,
            end=end,
            max_range_hours=max(settings.ecowitt_cloud_max_backfill_hours, settings.ecowitt_cloud_sync_lookback_hours),
        )
    except (EcowittCloudConfigError, EcowittCloudError, BackfillRangeError, ValueError) as exc:
        return SyncTaskResult("ecowitt", "failed", str(exc))
    return SyncTaskResult(
        "ecowitt",
        "success",
        "Ecowitt Cloud recent history imported.",
        {
            "imported": result.imported_count,
            "duplicates": result.duplicate_count,
            "warnings": result.warning_count,
        },
    )


def sync_aemet_recent(*, session: Session, settings: Settings) -> SyncTaskResult:
    if not settings.aemet_api_key:
        return SyncTaskResult("aemet", "skipped", "AEMET API key is not configured.")
    try:
        result = AemetImportService(
            session=session,
            client=AemetClient.from_settings(settings),
            settings=settings,
        ).sync(station_id=settings.aemet_station_id, lookback_days=settings.aemet_sync_lookback_days)
    except (AemetConfigError, AemetImportRangeError, AemetError) as exc:
        return SyncTaskResult("aemet", "failed", str(exc))
    return SyncTaskResult(
        "aemet",
        result.status,
        "AEMET recent daily observations imported.",
        {
            "received": result.records_received,
            "inserted": result.inserted,
            "updated": result.updated,
            "skipped": result.skipped,
            "errors": len(result.errors),
        },
    )


def sync_satellite_recent(*, session: Session, settings: Settings) -> SyncTaskResult:
    status = SatelliteIngestionService(session=session, settings=settings).status()
    if not status.configured:
        return SyncTaskResult("satellite", "skipped", status.message)
    result = SatelliteIngestionService(session=session, settings=settings).update()
    return SyncTaskResult(
        "satellite",
        result.status,
        "Satellite observations updated.",
        {
            "found": result.found_count,
            "processed": result.processed_count,
            "skipped": result.skipped_count,
            "failed": result.failed_count,
            "processing_units": result.processing_units,
        },
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
