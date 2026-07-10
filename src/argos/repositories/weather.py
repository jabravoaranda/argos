from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from argos.models.ecowitt import (
    DailyStatistic,
    DataGap,
    EcowittRawReport,
    Gateway,
    IngestionEvent,
    UnknownField,
    WeatherObservation,
    WeeklyStatistic,
)
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

    def previous_observation(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        observed_at_utc: datetime,
    ) -> WeatherObservation | None:
        return self.session.scalar(
            select(WeatherObservation)
            .where(
                WeatherObservation.station_uuid == station_uuid,
                WeatherObservation.observed_at_utc < observed_at_utc,
            )
            .order_by(desc(WeatherObservation.observed_at_utc), desc(WeatherObservation.id))
            .limit(1)
        )

    def latest_gateway(self) -> Gateway | None:
        return self.session.scalar(select(Gateway).order_by(desc(Gateway.last_seen_at), desc(Gateway.id)).limit(1))

    def recent_raw_reports(self, *, limit: int) -> list[EcowittRawReport]:
        return list(
            self.session.scalars(
                select(EcowittRawReport).order_by(desc(EcowittRawReport.received_at_utc), desc(EcowittRawReport.id)).limit(limit)
            ).all()
        )

    def ingestion_events(self, *, limit: int) -> list[IngestionEvent]:
        return list(
            self.session.scalars(
                select(IngestionEvent).order_by(desc(IngestionEvent.created_at), desc(IngestionEvent.id)).limit(limit)
            ).all()
        )

    def unknown_fields(self) -> list[UnknownField]:
        return list(self.session.scalars(select(UnknownField).order_by(UnknownField.field_name)).all())

    def data_gaps(self, *, unresolved_only: bool) -> list[DataGap]:
        statement = select(DataGap).order_by(desc(DataGap.gap_start), desc(DataGap.id))
        if unresolved_only:
            statement = statement.where(DataGap.resolved.is_(False))
        return list(self.session.scalars(statement).all())

    def create_data_gap(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        gap_start: datetime,
        gap_end: datetime,
        expected_reports: int,
        received_reports: int,
    ) -> DataGap:
        existing = self.session.scalar(
            select(DataGap).where(
                DataGap.station_uuid == station_uuid,
                DataGap.gap_start == gap_start,
                DataGap.gap_end == gap_end,
            )
        )
        if existing is not None:
            return existing

        gap = DataGap(
            station_uuid=station_uuid,
            gateway_id=gateway_id,
            gap_start=gap_start,
            gap_end=gap_end,
            expected_reports=expected_reports,
            received_reports=received_reports,
            resolved=False,
        )
        self.session.add(gap)
        self.session.flush()
        return gap

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
        station_uuid: str | None,
        gateway_id: int | None,
        summary: WeatherPeriodSummary,
    ) -> DailyStatistic:
        statistic = self.session.scalar(
            select(DailyStatistic).where(
                DailyStatistic.station_uuid == station_uuid,
                DailyStatistic.period_start == summary.period_start,
            )
        )
        if statistic is None:
            statistic = DailyStatistic(station_uuid=station_uuid, gateway_id=gateway_id, period_start=summary.period_start)
            self.session.add(statistic)
        _apply_summary(statistic, summary)
        self.session.flush()
        return statistic

    def upsert_weekly_statistic(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        summary: WeatherPeriodSummary,
    ) -> WeeklyStatistic:
        statistic = self.session.scalar(
            select(WeeklyStatistic).where(
                WeeklyStatistic.station_uuid == station_uuid,
                WeeklyStatistic.period_start == summary.period_start,
            )
        )
        if statistic is None:
            statistic = WeeklyStatistic(station_uuid=station_uuid, gateway_id=gateway_id, period_start=summary.period_start)
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
