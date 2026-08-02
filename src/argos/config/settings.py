from __future__ import annotations

from functools import lru_cache
from datetime import date

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./var/argos.db"
    local_timezone: str = "Europe/Madrid"
    log_level: str = "INFO"
    station_slug: str = "tomillar"
    argos_admin_token: str = Field(min_length=1)
    ecowitt_ingest_token: str = Field(min_length=1)
    ecowitt_capture_raw: bool = False
    ecowitt_expected_interval_seconds: int = 60
    ecowitt_offline_after_seconds: int = 180
    ecowitt_cloud_base_url: str = "https://api.ecowitt.net"
    ecowitt_cloud_api_version: str = "v3"
    ecowitt_cloud_application_key: str | None = None
    ecowitt_cloud_api_key: str | None = None
    ecowitt_cloud_mac: str | None = None
    ecowitt_cloud_timeout_seconds: int = 10
    ecowitt_cloud_max_backfill_hours: int = 24
    argos_satellite_enabled: bool = False
    argos_satellite_aois_json: str | None = None
    copernicus_client_id: str | None = None
    copernicus_client_secret: str | None = None
    copernicus_token_url: str = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )
    copernicus_stac_url: str = "https://stac.dataspace.copernicus.eu/v1"
    copernicus_catalog_url: str = "https://sh.dataspace.copernicus.eu/catalog/v1"
    copernicus_statistics_url: str = "https://sh.dataspace.copernicus.eu/statistics/v1"
    copernicus_process_url: str = "https://sh.dataspace.copernicus.eu/process/v1"
    argos_satellite_history_days: int = 730
    argos_satellite_max_cloud_cover: float = 60.0
    argos_satellite_min_valid_pixel_fraction: float = 0.20
    argos_satellite_valid_pixel_fraction: float = 0.50
    argos_satellite_update_interval_hours: int = 24
    argos_satellite_preview_enabled: bool = True
    argos_satellite_asset_dir: str = "data/satellite"
    argos_satellite_http_timeout_seconds: int = 30
    aemet_api_key: str | None = None
    aemet_station_id: str = "6127X"
    aemet_base_url: str = "https://opendata.aemet.es/opendata/api"
    aemet_timeout_seconds: int = 20
    aemet_max_retries: int = 3
    aemet_backoff_seconds: float = 0.5
    aemet_block_days: int = 31
    aemet_sync_lookback_days: int = 7
    aemet_backfill_start_date: date = date(1900, 1, 1)
    aemet_seed_csv_path: str | None = None
    argos_node_url: str | None = None
    argos_node_timeout_seconds: int = 5
    argos_node_poll_interval_seconds: float = 5.0
    argos_flowmeter_hydrological_year_reset_month: int = 10
    argos_flowmeter_hydrological_year_reset_day: int = 1
    argos_daily_sync_enabled: bool = True
    argos_daily_sync_interval_hours: float = 24.0
    ecowitt_cloud_sync_lookback_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
