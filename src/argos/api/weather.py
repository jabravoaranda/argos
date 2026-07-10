from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from argos.config.settings import Settings, get_settings
from argos.database.session import get_db_session
from argos.repositories.weather import WeatherRepository
from argos.schemas.weather import (
    GatewayStatusRead,
    StatisticsRecomputeRead,
    WeatherObservationRead,
    WeatherPeriodSummaryRead,
)
from argos.services.weather_statistics import recompute_statistics

router = APIRouter(prefix="/api/v1/weather", tags=["weather"])


@router.get("/latest", response_model=WeatherObservationRead | None)
def latest_weather_observation(session: Session = Depends(get_db_session)) -> WeatherObservationRead | None:
    observation = WeatherRepository(session).latest_observation()
    if observation is None:
        return None
    return WeatherObservationRead.model_validate(observation)


@router.get("/observations", response_model=list[WeatherObservationRead])
def weather_observations(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    session: Session = Depends(get_db_session),
) -> list[WeatherObservationRead]:
    observations = WeatherRepository(session).observations(start=start, end=end)
    return [WeatherObservationRead.model_validate(observation) for observation in observations]


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
    session: Session = Depends(get_db_session),
) -> StatisticsRecomputeRead:
    result = recompute_statistics(session, start=start, end=end)
    session.commit()
    return StatisticsRecomputeRead(daily_count=result.daily_count, weekly_count=result.weekly_count)


@router.get("/gateway/status", response_model=GatewayStatusRead)
def gateway_status(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> GatewayStatusRead:
    gateway = WeatherRepository(session).latest_gateway()
    if gateway is None or gateway.last_seen_at is None:
        return GatewayStatusRead(
            gateway_id=None,
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
