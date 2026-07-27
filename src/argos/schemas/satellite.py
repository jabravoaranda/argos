from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SatelliteSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    provider: str
    collection: str
    spatial_resolution_m: float | None
    enabled: bool


class SatelliteZoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    geometry_geojson: dict[str, Any]
    geometry_hash: str
    crs: str
    area_m2: float | None
    enabled: bool


class SatelliteMetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    observation_id: int
    metric_code: str
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    standard_deviation: float | None
    percentile_10: float | None
    percentile_25: float | None
    percentile_75: float | None
    percentile_90: float | None
    sample_count: int | None
    no_data_count: int | None
    valid_pixel_count: int | None
    unit: str


class SatelliteAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    observation_id: int
    asset_type: str
    storage_path: str
    mime_type: str
    checksum_sha256: str
    size_bytes: int


class SatelliteObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    zone_id: int
    external_item_id: str
    acquisition_time: datetime
    interval_start: datetime | None
    interval_end: datetime | None
    processing_time: datetime | None
    platform: str | None
    collection: str
    product_type: str | None
    cloud_cover_metadata: float | None
    valid_pixel_fraction: float | None
    invalid_pixel_fraction: float | None
    quality_status: str
    processing_version: str
    geometry_hash: str
    metrics: list[SatelliteMetricRead] = []
    assets: list[SatelliteAssetRead] = []


class SatelliteStatusRead(BaseModel):
    status: str
    enabled: bool
    configured: bool
    credentials_available: bool
    geometry_defined: bool
    message: str
    latest_acquisition_time: datetime | None
    latest_update_time: datetime | None
    zone_count: int
    observation_count: int


class SatelliteTimeseriesPoint(BaseModel):
    acquisition_time: datetime
    mean: float | None
    median: float | None
    p25: float | None
    p75: float | None
    valid_pixel_fraction: float | None
    quality_status: str


class SatelliteTimeseriesRead(BaseModel):
    zone: SatelliteZoneRead | None
    metric: str
    processing_version: str
    points: list[SatelliteTimeseriesPoint]


class SatelliteIngestionRead(BaseModel):
    status: str
    found_count: int
    processed_count: int
    skipped_count: int
    failed_count: int
    dry_run: bool
    warnings: list[str]
    processing_units: float | None


class SatelliteExportRow(BaseModel):
    acquisition_time: datetime
    zone_name: str
    metric_code: str
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    standard_deviation: float | None
    percentile_10: float | None
    percentile_25: float | None
    percentile_75: float | None
    percentile_90: float | None
    valid_pixel_fraction: float | None
    cloud_cover_metadata: float | None
    quality_status: str
    processing_version: str
