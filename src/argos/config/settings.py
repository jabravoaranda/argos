from __future__ import annotations

from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
