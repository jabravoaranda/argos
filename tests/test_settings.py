from __future__ import annotations

import pytest
from pydantic import ValidationError

from argos.config.settings import Settings


def test_settings_load_defaults_without_env_file() -> None:
    settings = Settings(ecowitt_ingest_token="test-token", _env_file=None)

    assert settings.app_env == "development"
    assert settings.database_url == "sqlite:///./var/argos.db"
    assert settings.local_timezone == "Europe/Madrid"
    assert settings.station_slug == "tomillar"
    assert settings.ecowitt_capture_raw is False
    assert settings.ecowitt_cloud_base_url == "https://api.ecowitt.net"
    assert settings.ecowitt_cloud_application_key is None


def test_settings_require_ingest_token(monkeypatch) -> None:
    monkeypatch.delenv("ECOWITT_INGEST_TOKEN", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
