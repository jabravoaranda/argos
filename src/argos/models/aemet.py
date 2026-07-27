from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from argos.database.base import Base
from argos.models.ecowitt import TimestampMixin


class WeatherStation(TimestampMixin, Base):
    __tablename__ = "weather_stations"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_weather_stations_provider_external"),
        Index("ix_weather_stations_provider_external", "provider", "external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    municipality: Mapped[str | None] = mapped_column(String(255))
    province: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    daily_observations: Mapped[list["WeatherDailyObservation"]] = relationship(back_populates="station")
    sync_runs: Mapped[list["AemetSyncRun"]] = relationship(back_populates="station")


class WeatherDailyObservation(TimestampMixin, Base):
    __tablename__ = "weather_daily_observations"
    __table_args__ = (
        UniqueConstraint("station_id", "observation_date", name="uq_weather_daily_observations_station_date"),
        Index("ix_weather_daily_observations_station_date", "station_id", "observation_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("weather_stations.id"), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    temperature_mean_c: Mapped[float | None] = mapped_column(Float)
    temperature_min_c: Mapped[float | None] = mapped_column(Float)
    temperature_max_c: Mapped[float | None] = mapped_column(Float)
    precipitation_mm: Mapped[float | None] = mapped_column(Float)
    precipitation_trace: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    wind_speed_mean_ms: Mapped[float | None] = mapped_column(Float)
    wind_gust_ms: Mapped[float | None] = mapped_column(Float)
    wind_gust_direction: Mapped[str | None] = mapped_column(String(32))
    sunshine_hours: Mapped[float | None] = mapped_column(Float)
    pressure_max_hpa: Mapped[float | None] = mapped_column(Float)
    pressure_min_hpa: Mapped[float | None] = mapped_column(Float)
    humidity_mean_pct: Mapped[float | None] = mapped_column(Float)
    humidity_min_pct: Mapped[float | None] = mapped_column(Float)
    humidity_max_pct: Mapped[float | None] = mapped_column(Float)
    quality_flag: Mapped[str | None] = mapped_column(String(255))
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    station: Mapped[WeatherStation] = relationship(back_populates="daily_observations")


class AemetSyncRun(TimestampMixin, Base):
    __tablename__ = "aemet_sync_runs"
    __table_args__ = (
        Index("ix_aemet_sync_runs_station_started", "station_id", "started_at"),
        Index("ix_aemet_sync_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("weather_stations.id"), nullable=True)
    station_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_start: Mapped[date] = mapped_column(Date, nullable=False)
    requested_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intervals_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    station: Mapped[WeatherStation | None] = relationship(back_populates="sync_runs")
