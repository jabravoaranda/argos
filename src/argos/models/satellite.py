from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from argos.database.base import Base


class SatelliteTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class SatelliteSource(SatelliteTimestampMixin, Base):
    __tablename__ = "satellite_sources"
    __table_args__ = (UniqueConstraint("code", name="uq_satellite_sources_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    collection: Mapped[str] = mapped_column(String(100), nullable=False)
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    observations: Mapped[list["SatelliteObservation"]] = relationship(back_populates="source")


class SatelliteZone(SatelliteTimestampMixin, Base):
    __tablename__ = "satellite_zones"
    __table_args__ = (UniqueConstraint("geometry_hash", name="uq_satellite_zones_geometry_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    geometry_geojson: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    geometry_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    crs: Mapped[str] = mapped_column(String(32), nullable=False, default="EPSG:4326", server_default="EPSG:4326")
    area_m2: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    observations: Mapped[list["SatelliteObservation"]] = relationship(back_populates="zone")


class SatelliteObservation(SatelliteTimestampMixin, Base):
    __tablename__ = "satellite_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "zone_id",
            "external_item_id",
            "processing_version",
            name="uq_satellite_observations_source_zone_item_version",
        ),
        Index("ix_satellite_observations_zone_acquisition", "zone_id", "acquisition_time"),
        Index("ix_satellite_observations_quality", "quality_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("satellite_sources.id"), nullable=False, index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("satellite_zones.id"), nullable=False, index=True)
    external_item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    acquisition_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    interval_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interval_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform: Mapped[str | None] = mapped_column(String(100))
    collection: Mapped[str] = mapped_column(String(100), nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(100))
    cloud_cover_metadata: Mapped[float | None] = mapped_column(Float)
    valid_pixel_fraction: Mapped[float | None] = mapped_column(Float)
    invalid_pixel_fraction: Mapped[float | None] = mapped_column(Float)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    source: Mapped[SatelliteSource] = relationship(back_populates="observations")
    zone: Mapped[SatelliteZone] = relationship(back_populates="observations")
    metrics: Mapped[list["SatelliteMetric"]] = relationship(back_populates="observation", cascade="all, delete-orphan")
    assets: Mapped[list["SatelliteAsset"]] = relationship(back_populates="observation", cascade="all, delete-orphan")


class SatelliteMetric(Base):
    __tablename__ = "satellite_metrics"
    __table_args__ = (UniqueConstraint("observation_id", "metric_code", name="uq_satellite_metrics_observation_metric"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("satellite_observations.id"), nullable=False, index=True)
    metric_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mean: Mapped[float | None] = mapped_column(Float)
    median: Mapped[float | None] = mapped_column(Float)
    minimum: Mapped[float | None] = mapped_column(Float)
    maximum: Mapped[float | None] = mapped_column(Float)
    standard_deviation: Mapped[float | None] = mapped_column(Float)
    percentile_10: Mapped[float | None] = mapped_column(Float)
    percentile_25: Mapped[float | None] = mapped_column(Float)
    percentile_75: Mapped[float | None] = mapped_column(Float)
    percentile_90: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    no_data_count: Mapped[int | None] = mapped_column(Integer)
    valid_pixel_count: Mapped[int | None] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="dimensionless", server_default="dimensionless")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    observation: Mapped[SatelliteObservation] = relationship(back_populates="metrics")


class SatelliteAsset(Base):
    __tablename__ = "satellite_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("satellite_observations.id"), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    observation: Mapped[SatelliteObservation] = relationship(back_populates="assets")
