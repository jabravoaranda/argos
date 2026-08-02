from __future__ import annotations

from datetime import UTC, date, datetime
import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from argos.config.settings import Settings, get_settings
from argos.database.session import get_db_session
from argos.integrations.aemet.client import AemetClient, AemetConfigError, AemetError
from argos.repositories.weather import WeatherRepository
from argos.repositories.aemet import AemetRepository
from argos.schemas.weather import (
    AemetObservationBoundsRead,
    AemetImportSummaryRead,
    AemetSyncRunRead,
    DataGapRead,
    GatewayHardwareRead,
    GatewayStatusRead,
    IngestionEventRead,
    RawReportRead,
    StationRead,
    StatisticsRecomputeRead,
    UnknownFieldRead,
    WeatherObservationRead,
    WeatherDailyObservationRead,
    WeatherStationRead,
    WeatherPeriodSummaryRead,
)
from argos.models.aemet import WeatherDailyObservation
from argos.services.aemet_import import AemetImportRangeError, AemetImportService
from argos.services.weather_statistics import recompute_statistics
from argos.utils.redaction import redact_sensitive_values

router = APIRouter(prefix="/api/v1/weather", tags=["weather"])


def require_admin_token(
    x_argos_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_argos_admin_token is None or not hmac.compare_digest(x_argos_admin_token, settings.argos_admin_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin token.")


@router.get("/latest", response_model=WeatherObservationRead | None)
def latest_weather_observation(session: Session = Depends(get_db_session)) -> WeatherObservationRead | None:
    observation = WeatherRepository(session).latest_observation()
    if observation is None:
        return None
    return WeatherObservationRead.model_validate(observation)


@router.get("/station", response_model=StationRead | None)
def station(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> StationRead | None:
    station_record = WeatherRepository(session).station_by_slug(settings.station_slug)
    if station_record is None:
        return None
    return StationRead.model_validate(station_record)


@router.get("/station/hardware", response_model=list[GatewayHardwareRead])
def station_hardware(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[GatewayHardwareRead]:
    repository = WeatherRepository(session)
    station_record = repository.station_by_slug(settings.station_slug)
    if station_record is None:
        return []
    hardware = repository.station_hardware(station_uuid=station_record.uuid)
    return [GatewayHardwareRead.model_validate(gateway) for gateway in hardware]


@router.get("/observations", response_model=list[WeatherObservationRead])
def weather_observations(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    session: Session = Depends(get_db_session),
) -> list[WeatherObservationRead]:
    observations = WeatherRepository(session).observations(start=start, end=end)
    return [WeatherObservationRead.model_validate(observation) for observation in observations]


@router.get("/stations", response_model=list[WeatherStationRead])
def weather_stations(
    provider: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[WeatherStationRead]:
    stations = AemetRepository(session).stations(provider=provider, limit=limit)
    return [WeatherStationRead.model_validate(station) for station in stations]


@router.get("/aemet/observations", response_model=list[WeatherDailyObservationRead])
def aemet_daily_observations(
    station: str = Query(default="6127X"),
    start: date | None = Query(default=None, alias="from"),
    end: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=366, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> list[WeatherDailyObservationRead]:
    _validate_date_window(start=start, end=end, max_days=50000)
    repository = AemetRepository(session)
    station_record = repository.station_by_provider_external(provider="aemet", external_id=station)
    if station_record is None:
        return []
    observations = repository.daily_observations(
        station_id=station_record.id,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    return [WeatherDailyObservationRead.model_validate(observation) for observation in observations]


@router.get("/aemet/sync/latest", response_model=AemetSyncRunRead | None)
def latest_aemet_sync(
    station: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> AemetSyncRunRead | None:
    run = AemetRepository(session).latest_sync_run(station_external_id=station)
    if run is None:
        return None
    return AemetSyncRunRead.model_validate(run)


@router.get("/aemet/bounds", response_model=AemetObservationBoundsRead)
def aemet_observation_bounds(
    station: str = Query(default="6127X"),
    session: Session = Depends(get_db_session),
) -> AemetObservationBoundsRead:
    repository = AemetRepository(session)
    station_record = repository.station_by_provider_external(provider="aemet", external_id=station)
    if station_record is None:
        return AemetObservationBoundsRead(station=station, first_date=None, last_date=None, count=0)
    first_date, last_date = repository.observation_date_bounds(station_id=station_record.id)
    count = session.scalar(
        select(func.count()).select_from(WeatherDailyObservation).where(WeatherDailyObservation.station_id == station_record.id)
    )
    return AemetObservationBoundsRead(station=station, first_date=first_date, last_date=last_date, count=int(count or 0))


@router.post("/aemet/backfill", response_model=AemetImportSummaryRead)
def backfill_aemet(
    station: str | None = Query(default=None),
    start: date | None = Query(default=None, alias="from"),
    end: date | None = Query(default=None, alias="to"),
    block_days: int | None = Query(default=None, ge=1, le=366),
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AemetImportSummaryRead:
    import_start = start or settings.aemet_backfill_start_date
    import_end = end or datetime.now(UTC).date()
    _validate_date_window(start=import_start, end=import_end, max_days=50000)
    try:
        result = AemetImportService(
            session=session,
            client=AemetClient.from_settings(settings),
            settings=settings,
        ).backfill(
            station_id=station or settings.aemet_station_id,
            start=import_start,
            end=import_end,
            block_days=block_days,
        )
    except AemetConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (AemetImportRangeError, AemetError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _aemet_summary_read(result)


@router.post("/aemet/sync", response_model=AemetImportSummaryRead)
def sync_aemet(
    station: str | None = Query(default=None),
    lookback_days: int | None = Query(default=None, ge=1, le=366),
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AemetImportSummaryRead:
    try:
        result = AemetImportService(
            session=session,
            client=AemetClient.from_settings(settings),
            settings=settings,
        ).sync(
            station_id=station or settings.aemet_station_id,
            lookback_days=lookback_days or settings.aemet_sync_lookback_days,
        )
    except AemetConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (AemetImportRangeError, AemetError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _aemet_summary_read(result)


@router.post("/aemet/import-csv", response_model=AemetImportSummaryRead)
def import_aemet_csv(
    path: str = Query(...),
    station: str | None = Query(default=None),
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AemetImportSummaryRead:
    try:
        result = AemetImportService(
            session=session,
            client=AemetClient(base_url=settings.aemet_base_url, api_key="csv-import"),
            settings=settings,
        ).import_csv(path=Path(path), station_id=station or settings.aemet_station_id)
    except AemetImportRangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _aemet_summary_read(result)


@router.get("/summary/daily", response_model=list[WeatherPeriodSummaryRead])
def daily_weather_summary(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    session: Session = Depends(get_db_session),
) -> list[WeatherPeriodSummaryRead]:
    statistics = WeatherRepository(session).daily_statistics(start=_date_or_none(start), end=_date_or_none(end))
    return [WeatherPeriodSummaryRead.model_validate(statistic) for statistic in statistics]


@router.get("/summary/weekly", response_model=list[WeatherPeriodSummaryRead])
def weekly_weather_summary(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    session: Session = Depends(get_db_session),
) -> list[WeatherPeriodSummaryRead]:
    statistics = WeatherRepository(session).weekly_statistics(start=_date_or_none(start), end=_date_or_none(end))
    return [WeatherPeriodSummaryRead.model_validate(statistic) for statistic in statistics]


@router.post("/statistics/recompute", response_model=StatisticsRecomputeRead)
def recompute_weather_statistics(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> StatisticsRecomputeRead:
    result = recompute_statistics(session, start=start, end=end)
    session.commit()
    return StatisticsRecomputeRead(daily_count=result.daily_count, weekly_count=result.weekly_count)


@router.get("/admin/raw-reports", response_model=list[RawReportRead])
def recent_raw_reports(
    limit: int = Query(default=20, ge=1, le=200),
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> list[RawReportRead]:
    reports = WeatherRepository(session).recent_raw_reports(limit=limit)
    return [
        RawReportRead.model_validate(report).model_copy(
            update={"payload_json": redact_sensitive_values(report.payload_json)}
        )
        for report in reports
    ]


@router.get("/admin/events", response_model=list[IngestionEventRead])
def ingestion_events(
    limit: int = Query(default=50, ge=1, le=500),
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> list[IngestionEventRead]:
    events = WeatherRepository(session).ingestion_events(limit=limit)
    return [IngestionEventRead.model_validate(event) for event in events]


@router.get("/admin/unknown-fields", response_model=list[UnknownFieldRead])
def unknown_fields(
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> list[UnknownFieldRead]:
    fields = WeatherRepository(session).unknown_fields()
    return [UnknownFieldRead.model_validate(field) for field in fields]


@router.get("/admin/data-gaps", response_model=list[DataGapRead])
def data_gaps(
    unresolved_only: bool = True,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> list[DataGapRead]:
    gaps = WeatherRepository(session).data_gaps(unresolved_only=unresolved_only)
    return [DataGapRead.model_validate(gap) for gap in gaps]


@router.get("/gateway/status", response_model=GatewayStatusRead)
def gateway_status(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> GatewayStatusRead:
    gateway = WeatherRepository(session).latest_gateway()
    if gateway is None or gateway.last_seen_at is None:
        return GatewayStatusRead(
            gateway_id=None,
            station_uuid=None,
            station_slug=None,
            station_type=None,
            last_seen_at=None,
            seconds_since_last_seen=None,
            online=False,
            offline_after_seconds=settings.ecowitt_offline_after_seconds,
        )

    last_seen_at = _ensure_utc(gateway.last_seen_at)
    seconds_since_last_seen = (datetime.now(UTC) - last_seen_at).total_seconds()
    return GatewayStatusRead(
        gateway_id=gateway.id,
        station_uuid=gateway.station_uuid,
        station_slug=gateway.station.slug if gateway.station else None,
        station_type=gateway.station_type,
        last_seen_at=last_seen_at,
        seconds_since_last_seen=seconds_since_last_seen,
        online=seconds_since_last_seen <= settings.ecowitt_offline_after_seconds,
        offline_after_seconds=settings.ecowitt_offline_after_seconds,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _date_or_none(value: datetime | None):
    if value is None:
        return None
    return value.date()


def _validate_date_window(*, start: date | None, end: date | None, max_days: int) -> None:
    if start is not None and end is not None:
        if end < start:
            raise HTTPException(status_code=400, detail="End date must be on or after start date.")
        if (end - start).days > max_days:
            raise HTTPException(status_code=400, detail=f"Date range cannot exceed {max_days} days.")


def _aemet_summary_read(result) -> AemetImportSummaryRead:
    return AemetImportSummaryRead(
        station_external_id=result.station_external_id,
        start=result.start,
        end=result.end,
        status=result.status,
        intervals=[interval.as_dict() for interval in result.intervals],
        records_received=result.records_received,
        inserted=result.inserted,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.errors,
    )
