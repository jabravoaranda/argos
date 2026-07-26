from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.main import create_app
from argos.services.ecowitt_status import build_ecowitt_status


def test_build_ecowitt_status_reports_ingestion_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ECOWITT_OFFLINE_AFTER_SECONDS", "180")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())
    raw_body = Path("tests/fixtures/ecowitt/gw2000a_ws90_3_3_2_form.txt").read_text()

    assert client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    ).status_code == 200
    assert client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    ).status_code == 200

    with get_sessionmaker()() as session:
        status = build_ecowitt_status(
            session=session,
            offline_after_seconds=180,
            now_utc=datetime.now(UTC),
        )

    assert status.station_slug == "tomillar"
    assert status.gateway_identifier == "GW2000A"
    assert status.station_type == "GW2000A_V3.3.2"
    assert status.last_report_at is not None
    assert status.online is True
    assert status.reports_last_24h == 1
    assert status.duplicate_events == 1
    assert status.parser_warning_events == 0
    assert status.unknown_fields == 0
    assert status.open_gaps == 0

    get_settings.cache_clear()
    reset_database_caches()
