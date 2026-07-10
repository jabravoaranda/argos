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
    ecowitt_ingest_token: str = Field(min_length=1)
    ecowitt_capture_raw: bool = False
    ecowitt_expected_interval_seconds: int = 60
    ecowitt_offline_after_seconds: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
