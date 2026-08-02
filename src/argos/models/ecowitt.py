from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from argos.database.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Station(TimestampMixin, Base):
    __tablename__ = "stations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_stations_slug"),
        UniqueConstraint("code", name="uq_stations_code"),
    )

    uuid: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    gateways: Mapped[list["Gateway"]] = relationship(back_populates="station")


class Gateway(TimestampMixin, Base):
    __tablename__ = "gateways"
    __table_args__ = (
        UniqueConstraint("mac_address", name="uq_gateways_mac_address"),
        Index("ix_gateways_last_seen_at", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_uuid: Mapped[str | None] = mapped_column(ForeignKey("stations.uuid"), index=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    mac_address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    station_type: Mapped[str | None] = mapped_column(String(100))
    firmware_version: Mapped[str | None] = mapped_column(String(100))
    hardware_version: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    station: Mapped[Station | None] = relationship(back_populates="gateways")
    raw_reports: Mapped[list["EcowittRawReport"]] = relationship(back_populates="gateway")
    aliases: Mapped[list["GatewayAlias"]] = relationship(back_populates="gateway")


class GatewayAlias(TimestampMixin, Base):
    __tablename__ = "gateway_aliases"
    __table_args__ = (
        UniqueConstraint("alias_type", "alias_value", name="uq_gateway_aliases_type_value"),
        Index("ix_gateway_aliases_gateway_id", "gateway_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gateway_id: Mapped[int] = mapped_column(ForeignKey("gateways.id"), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(64), nullable=False)
    alias_value: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    gateway: Mapped[Gateway] = relationship(back_populates="aliases")


class EcowittRawReport(TimestampMixin, Base):
    __tablename__ = "ecowitt_raw_reports"
    __table_args__ = (
        UniqueConstraint("payload_hash", name="uq_ecowitt_raw_reports_payload_hash"),
        Index("ix_ecowitt_raw_reports_gateway_received", "gateway_id", "received_at_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_uuid: Mapped[str | None] = mapped_column(ForeignKey("stations.uuid"), index=True)
    gateway_id: Mapped[int] = mapped_column(ForeignKey("gateways.id"), nullable=False, index=True)
    received_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    device_timestamp_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(128))
    content_type: Mapped[str | None] = mapped_column(String(255))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_body_text: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    headers_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    query_string: Mapped[str | None] = mapped_column(Text)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str | None] = mapped_column(String(32))
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)

    gateway: Mapped[Gateway | None] = relationship(back_populates="raw_reports")
    observation: Mapped["WeatherObservation | None"] = relationship(back_populates="raw_report")


class EcowittCloudRawReport(TimestampMixin, Base):
    __tablename__ = "ecowitt_cloud_raw_reports"
    __table_args__ = (
        UniqueConstraint("payload_hash", name="uq_ecowitt_cloud_raw_reports_payload_hash"),
        Index("ix_ecowitt_cloud_raw_reports_gateway_observed", "gateway_id", "observed_at_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_uuid: Mapped[str | None] = mapped_column(ForeignKey("stations.uuid"), index=True)
    gateway_id: Mapped[int | None] = mapped_column(ForeignKey("gateways.id"), index=True)
    requested_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_version: Mapped[str | None] = mapped_column(String(32))
    parser_version: Mapped[str | None] = mapped_column(String(32))
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)

    observation: Mapped["WeatherObservation | None"] = relationship(back_populates="cloud_raw_report")


class WeatherObservation(TimestampMixin, Base):
    __tablename__ = "weather_observations"
    __table_args__ = (
        UniqueConstraint(
            "gateway_id",
            "observed_at_utc",
            "source",
            name="uq_weather_observations_gateway_observed_source",
        ),
        Index("ix_weather_observations_gateway_observed", "gateway_id", "observed_at_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_uuid: Mapped[str | None] = mapped_column(ForeignKey("stations.uuid"), index=True)
    gateway_id: Mapped[int | None] = mapped_column(ForeignKey("gateways.id"), index=True)
    raw_report_id: Mapped[int | None] = mapped_column(ForeignKey("ecowitt_raw_reports.id"), unique=True)
    cloud_raw_report_id: Mapped[int | None] = mapped_column(ForeignKey("ecowitt_cloud_raw_reports.id"), unique=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="DIRECT", server_default="DIRECT")
    observed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    received_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    indoor_temperature_c: Mapped[float | None] = mapped_column(Float)
    indoor_humidity_pct: Mapped[float | None] = mapped_column(Float)
    outdoor_temperature_c: Mapped[float | None] = mapped_column(Float)
    outdoor_humidity_pct: Mapped[float | None] = mapped_column(Float)
    dew_point_c: Mapped[float | None] = mapped_column(Float)
    feels_like_c: Mapped[float | None] = mapped_column(Float)
    vpd_kpa: Mapped[float | None] = mapped_column(Float)
    absolute_pressure_hpa: Mapped[float | None] = mapped_column(Float)
    relative_pressure_hpa: Mapped[float | None] = mapped_column(Float)
    wind_direction_deg: Mapped[float | None] = mapped_column(Float)
    wind_direction_avg10m_deg: Mapped[float | None] = mapped_column(Float)
    wind_speed_ms: Mapped[float | None] = mapped_column(Float)
    wind_gust_ms: Mapped[float | None] = mapped_column(Float)
    daily_max_gust_ms: Mapped[float | None] = mapped_column(Float)
    solar_radiation_wm2: Mapped[float | None] = mapped_column(Float)
    uv_index: Mapped[float | None] = mapped_column(Float)
    rain_rate_mm_h: Mapped[float | None] = mapped_column(Float)
    rain_event_mm: Mapped[float | None] = mapped_column(Float)
    rain_hour_mm: Mapped[float | None] = mapped_column(Float)
    rain_last_24h_mm: Mapped[float | None] = mapped_column(Float)
    rain_day_mm: Mapped[float | None] = mapped_column(Float)
    rain_week_mm: Mapped[float | None] = mapped_column(Float)
    rain_month_mm: Mapped[float | None] = mapped_column(Float)
    rain_year_mm: Mapped[float | None] = mapped_column(Float)
    piezo_rain_mm: Mapped[float | None] = mapped_column(Float)
    battery_voltage: Mapped[float | None] = mapped_column(Float)
    ws90_capacitor_voltage: Mapped[float | None] = mapped_column(Float)
    signal_dbm: Mapped[float | None] = mapped_column(Float)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)

    raw_report: Mapped["EcowittRawReport | None"] = relationship(back_populates="observation")
    cloud_raw_report: Mapped["EcowittCloudRawReport | None"] = relationship(back_populates="observation")


class DailyStatistic(TimestampMixin, Base):
    __tablename__ = "daily_statistics"
    __table_args__ = (
        UniqueConstraint("gateway_id", "period_start", name="uq_daily_statistics_gateway_period"),
        Index("ix_daily_statistics_gateway_period", "gateway_id", "period_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_uuid: Mapped[str | None] = mapped_column(ForeignKey("stations.uuid"), index=True)
    gateway_id: Mapped[int | None] = mapped_column(ForeignKey("gateways.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outdoor_temperature_mean_c: Mapped[float | None] = mapped_column(Float)
    outdoor_temperature_min_c: Mapped[float | None] = mapped_column(Float)
    outdoor_temperature_max_c: Mapped[float | None] = mapped_column(Float)
    outdoor_humidity_mean_pct: Mapped[float | None] = mapped_column(Float)
    relative_pressure_mean_hpa: Mapped[float | None] = mapped_column(Float)
    wind_gust_max_ms: Mapped[float | None] = mapped_column(Float)
    solar_radiation_max_wm2: Mapped[float | None] = mapped_column(Float)
    uv_index_max: Mapped[float | None] = mapped_column(Float)
    rain_day_max_mm: Mapped[float | None] = mapped_column(Float)
    rain_event_max_mm: Mapped[float | None] = mapped_column(Float)
    rain_last_24h_max_mm: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class WeeklyStatistic(TimestampMixin, Base):
    __tablename__ = "weekly_statistics"
    __table_args__ = (
        UniqueConstraint("gateway_id", "period_start", name="uq_weekly_statistics_gateway_period"),
        Index("ix_weekly_statistics_gateway_period", "gateway_id", "period_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_uuid: Mapped[str | None] = mapped_column(ForeignKey("stations.uuid"), index=True)
    gateway_id: Mapped[int | None] = mapped_column(ForeignKey("gateways.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outdoor_temperature_mean_c: Mapped[float | None] = mapped_column(Float)
    outdoor_temperature_min_c: Mapped[float | None] = mapped_column(Float)
    outdoor_temperature_max_c: Mapped[float | None] = mapped_column(Float)
    outdoor_humidity_mean_pct: Mapped[float | None] = mapped_column(Float)
    relative_pressure_mean_hpa: Mapped[float | None] = mapped_column(Float)
    wind_gust_max_ms: Mapped[float | None] = mapped_column(Float)
    solar_radiation_max_wm2: Mapped[float | None] = mapped_column(Float)
    uv_index_max: Mapped[float | None] = mapped_column(Float)
    rain_day_max_mm: Mapped[float | None] = mapped_column(Float)
    rain_event_max_mm: Mapped[float | None] = mapped_column(Float)
    rain_last_24h_max_mm: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class UnknownField(TimestampMixin, Base):
    __tablename__ = "unknown_fields"
    __table_args__ = (UniqueConstraint("field_name", name="uq_unknown_fields_field_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sample_value: Mapped[str | None] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    normalized_mapping: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)


class IngestionEvent(TimestampMixin, Base):
    __tablename__ = "ingestion_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_uuid: Mapped[str | None] = mapped_column(ForeignKey("stations.uuid"), index=True)
    gateway_id: Mapped[int | None] = mapped_column(ForeignKey("gateways.id"), index=True)
    raw_report_id: Mapped[int | None] = mapped_column(ForeignKey("ecowitt_raw_reports.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)


class DataGap(TimestampMixin, Base):
    __tablename__ = "data_gaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_uuid: Mapped[str | None] = mapped_column(ForeignKey("stations.uuid"), index=True)
    gateway_id: Mapped[int | None] = mapped_column(ForeignKey("gateways.id"), index=True)
    gap_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gap_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_reports: Mapped[int | None] = mapped_column(Integer)
    received_reports: Mapped[int | None] = mapped_column(Integer)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    resolution_method: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
