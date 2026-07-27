from __future__ import annotations

from datetime import datetime
from datetime import date

from pydantic import BaseModel, ConfigDict


class StationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    slug: str
    code: str
    name: str | None
    enabled: bool
    metadata_json: dict | None


class GatewayHardwareRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_uuid: str | None
    uuid: str
    name: str | None
    mac_address: str
    station_type: str | None
    firmware_version: str | None
    hardware_version: str | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    enabled: bool
    metadata_json: dict | None


class WeatherObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_uuid: str | None
    gateway_id: int | None
    raw_report_id: int | None
    cloud_raw_report_id: int | None
    source: str
    observed_at_utc: datetime
    received_at_utc: datetime
    indoor_temperature_c: float | None
    indoor_humidity_pct: float | None
    outdoor_temperature_c: float | None
    outdoor_humidity_pct: float | None
    vpd_kpa: float | None
    absolute_pressure_hpa: float | None
    relative_pressure_hpa: float | None
    wind_direction_deg: float | None
    wind_direction_avg10m_deg: float | None
    wind_speed_ms: float | None
    wind_gust_ms: float | None
    daily_max_gust_ms: float | None
    solar_radiation_wm2: float | None
    uv_index: float | None
    rain_rate_mm_h: float | None
    rain_event_mm: float | None
    rain_hour_mm: float | None
    rain_last_24h_mm: float | None
    rain_day_mm: float | None
    rain_week_mm: float | None
    rain_month_mm: float | None
    rain_year_mm: float | None
    piezo_rain_mm: float | None
    battery_voltage: float | None
    ws90_capacitor_voltage: float | None


class GatewayStatusRead(BaseModel):
    station_uuid: str | None
    station_slug: str | None
    gateway_id: int | None
    station_type: str | None
    last_seen_at: datetime | None
    seconds_since_last_seen: float | None
    online: bool
    offline_after_seconds: int


class WeatherPeriodSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gateway_id: int | None
    station_uuid: str | None
    period_start: date
    period_end: date
    sample_count: int
    outdoor_temperature_mean_c: float | None
    outdoor_temperature_min_c: float | None
    outdoor_temperature_max_c: float | None
    outdoor_humidity_mean_pct: float | None
    relative_pressure_mean_hpa: float | None
    wind_gust_max_ms: float | None
    solar_radiation_max_wm2: float | None
    uv_index_max: float | None
    rain_day_max_mm: float | None
    rain_event_max_mm: float | None
    rain_last_24h_max_mm: float | None


class StatisticsRecomputeRead(BaseModel):
    daily_count: int
    weekly_count: int


class RawReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_uuid: str | None
    gateway_id: int | None
    received_at_utc: datetime
    device_timestamp_utc: datetime | None
    source_ip: str | None
    content_type: str | None
    payload_json: dict
    parser_version: str | None


class IngestionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_uuid: str | None
    gateway_id: int | None
    raw_report_id: int | None
    event_type: str
    severity: str
    message: str
    created_at: datetime


class UnknownFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_name: str
    sample_value: str | None
    occurrence_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    normalized_mapping: str | None


class DataGapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_uuid: str | None
    gateway_id: int | None
    gap_start: datetime
    gap_end: datetime
    expected_reports: int | None
    received_reports: int | None
    resolved: bool
    resolution_method: str | None
    resolved_at: datetime | None


class WeatherStationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    external_id: str
    name: str
    municipality: str | None
    province: str | None
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    enabled: bool
    metadata_json: dict | None


class WeatherDailyObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_id: int
    observation_date: date
    temperature_mean_c: float | None
    temperature_min_c: float | None
    temperature_max_c: float | None
    precipitation_mm: float | None
    precipitation_trace: bool
    wind_speed_mean_ms: float | None
    wind_gust_ms: float | None
    wind_gust_direction: str | None
    sunshine_hours: float | None
    pressure_max_hpa: float | None
    pressure_min_hpa: float | None
    humidity_mean_pct: float | None
    humidity_min_pct: float | None
    humidity_max_pct: float | None
    quality_flag: str | None
    raw_payload_json: dict
    created_at: datetime
    updated_at: datetime | None


class AemetSyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    station_id: int | None
    station_external_id: str
    mode: str
    requested_start: date
    requested_end: date
    status: str
    started_at: datetime
    finished_at: datetime | None
    intervals_json: list[dict]
    records_received: int
    inserted: int
    updated: int
    skipped: int
    errors_json: list[dict]


class AemetObservationBoundsRead(BaseModel):
    station: str
    first_date: date | None
    last_date: date | None
    count: int


class AemetImportIntervalRead(BaseModel):
    start: date
    end: date
    records_received: int
    status: str
    error: str | None


class AemetImportSummaryRead(BaseModel):
    station_external_id: str
    start: date
    end: date
    status: str
    intervals: list[AemetImportIntervalRead]
    records_received: int
    inserted: int
    updated: int
    skipped: int
    errors: list[dict]
