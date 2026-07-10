from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from argos.models.ecowitt import DailyStatistic, Gateway, WeatherObservation, WeeklyStatistic
from argos.services.weather_aggregations import WeatherPeriodSummary


class WeatherRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_observation(self) -> WeatherObservation | None:
        return self.session.scalar(
            select(WeatherObservation)
            .options(joinedload(WeatherObservation.raw_report))
            .order_by(desc(WeatherObservation.observed_at_utc), desc(WeatherObservation.id))
            .limit(1)
        )

    def observations(self, *, start: datetime | None, end: datetime | None) -> list[WeatherObservation]:
        statement = (
            select(WeatherObservation)
            .options(joinedload(WeatherObservation.raw_report))
            .order_by(WeatherObservation.observed_at_utc, WeatherObservation.id)
        )
        if start is not None:
            statement = statement.where(WeatherObservation.observed_at_utc >= start)
        if end is not None:
            statement = statement.where(WeatherObservation.observed_at_utc <= end)
        return list(self.session.scalars(statement).all())

    def latest_gateway(self) -> Gateway | None:
        return self.session.scalar(select(Gateway).order_by(desc(Gateway.last_seen_at), desc(Gateway.id)).limit(1))

    def daily_statistics(self, *, start: date | None, end: date | None) -> list[DailyStatistic]:
        statement = select(DailyStatistic).order_by(DailyStatistic.period_start, DailyStatistic.id)
        if start is not None:
            statement = statement.where(DailyStatistic.period_start >= start)
        if end is not None:
            statement = statement.where(DailyStatistic.period_start <= end)
        return list(self.session.scalars(statement).all())

    def weekly_statistics(self, *, start: date | None, end: date | None) -> list[WeeklyStatistic]:
        statement = select(WeeklyStatistic).order_by(WeeklyStatistic.period_start, WeeklyStatistic.id)
        if start is not None:
            statement = statement.where(WeeklyStatistic.period_start >= start)
        if end is not None:
            statement = statement.where(WeeklyStatistic.period_start <= end)
        return list(self.session.scalars(statement).all())

    def upsert_daily_statistic(
        self,
        *,
        gateway_id: int | None,
        summary: WeatherPeriodSummary,
    ) -> DailyStatistic:
        statistic = self.session.scalar(
            select(DailyStatistic).where(
                DailyStatistic.gateway_id == gateway_id,
                DailyStatistic.period_start == summary.period_start,
            )
        )
        if statistic is None:
            statistic = DailyStatistic(gateway_id=gateway_id, period_start=summary.period_start)
            self.session.add(statistic)
        _apply_summary(statistic, summary)
        self.session.flush()
        return statistic

    def upsert_weekly_statistic(
        self,
        *,
        gateway_id: int | None,
        summary: WeatherPeriodSummary,
    ) -> WeeklyStatistic:
        statistic = self.session.scalar(
            select(WeeklyStatistic).where(
                WeeklyStatistic.gateway_id == gateway_id,
                WeeklyStatistic.period_start == summary.period_start,
            )
        )
        if statistic is None:
            statistic = WeeklyStatistic(gateway_id=gateway_id, period_start=summary.period_start)
            self.session.add(statistic)
        _apply_summary(statistic, summary)
        self.session.flush()
        return statistic


def _apply_summary(statistic: DailyStatistic | WeeklyStatistic, summary: WeatherPeriodSummary) -> None:
    statistic.period_end = summary.period_end
    statistic.sample_count = summary.sample_count
    statistic.outdoor_temperature_mean_c = summary.outdoor_temperature_mean_c
    statistic.outdoor_temperature_min_c = summary.outdoor_temperature_min_c
    statistic.outdoor_temperature_max_c = summary.outdoor_temperature_max_c
    statistic.outdoor_humidity_mean_pct = summary.outdoor_humidity_mean_pct
    statistic.relative_pressure_mean_hpa = summary.relative_pressure_mean_hpa
    statistic.wind_gust_max_ms = summary.wind_gust_max_ms
    statistic.solar_radiation_max_wm2 = summary.solar_radiation_max_wm2
    statistic.uv_index_max = summary.uv_index_max
    statistic.rain_day_max_mm = summary.rain_day_max_mm
    statistic.rain_event_max_mm = summary.rain_event_max_mm
    statistic.rain_last_24h_max_mm = summary.rain_last_24h_max_mm
