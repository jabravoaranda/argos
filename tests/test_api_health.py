from __future__ import annotations

from fastapi.testclient import TestClient

from argos.config.settings import get_settings
from argos.database.session import reset_database_caches
from argos.main import create_app


def test_health_endpoints(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()

    client = TestClient(create_app())

    assert client.get("/live").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ok"}
    assert client.get("/health").json() == {"status": "ok", "environment": "development"}

    get_settings.cache_clear()
    reset_database_caches()
