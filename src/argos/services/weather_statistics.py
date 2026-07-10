from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy.orm import Session

from argos.models.ecowitt import WeatherObservation
from argos.repositories.weather import WeatherRepository
from argos.services.weather_aggregations import summarize_daily, summarize_weekly


@dataclass(frozen=True, slots=True)
class StatisticsRecomputeResult:
    daily_count: int
    weekly_count: int


def update_statistics_for_observation(session: Session, observation: WeatherObservation) -> StatisticsRecomputeResult:
    observed_date = observation.observed_at_utc.date()
    week = observed_date.isocalendar()
    week_start = observed_date.fromisocalendar(week.year, week.week, 1)
    week_end = observed_date.fromisocalendar(week.year, week.week, 7)

    daily_count = recompute_daily_statistics(session, start=_start_of_day(observed_date), end=_end_of_day(observed_date))
    weekly_count = recompute_weekly_statistics(session, start=_start_of_day(week_start), end=_end_of_day(week_end))
    return StatisticsRecomputeResult(daily_count=daily_count, weekly_count=weekly_count)


def recompute_statistics(
    session: Session,
    *,
    start: datetime | None,
    end: datetime | None,
) -> StatisticsRecomputeResult:
    daily_count = recompute_daily_statistics(session, start=start, end=end)
    weekly_count = recompute_weekly_statistics(session, start=start, end=end)
    return StatisticsRecomputeResult(daily_count=daily_count, weekly_count=weekly_count)


def recompute_daily_statistics(session: Session, *, start: datetime | None, end: datetime | None) -> int:
    repository = WeatherRepository(session)
    observations = repository.observations(start=start, end=end)
    summaries = summarize_daily(observations)
    for summary in summaries:
        station_keys = {
            (observation.station_uuid, observation.gateway_id)
            for observation in observations
            if observation.observed_at_utc.date() == summary.period_start
        }
        for station_uuid, gateway_id in station_keys:
            gateway_observations = [
                observation
                for observation in observations
                if observation.station_uuid == station_uuid and observation.observed_at_utc.date() == summary.period_start
            ]
            gateway_summary = summarize_daily(gateway_observations)[0]
            repository.upsert_daily_statistic(station_uuid=station_uuid, gateway_id=gateway_id, summary=gateway_summary)
    return len(summaries)


def recompute_weekly_statistics(session: Session, *, start: datetime | None, end: datetime | None) -> int:
    repository = WeatherRepository(session)
    observations = repository.observations(start=start, end=end)
    summaries = summarize_weekly(observations)
    for summary in summaries:
        station_keys = {
            (observation.station_uuid, observation.gateway_id)
            for observation in observations
            if _week_start(observation.observed_at_utc) == summary.period_start
        }
        for station_uuid, gateway_id in station_keys:
            gateway_observations = [
                observation
                for observation in observations
                if observation.station_uuid == station_uuid and _week_start(observation.observed_at_utc) == summary.period_start
            ]
            gateway_summary = summarize_weekly(gateway_observations)[0]
            repository.upsert_weekly_statistic(station_uuid=station_uuid, gateway_id=gateway_id, summary=gateway_summary)
    return len(summaries)


def _week_start(value: datetime):
    value_date = value.date()
    week = value_date.isocalendar()
    return value_date.fromisocalendar(week.year, week.week, 1)


def _start_of_day(value) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _end_of_day(value) -> datetime:
    return datetime.combine(value, time.max, tzinfo=UTC)
