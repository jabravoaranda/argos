from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.main import create_app
from argos.models.ecowitt import EcowittRawReport, IngestionEvent, UnknownField, WeatherObservation


def test_ecowitt_upload_captures_and_normalizes_real_form_payload(monkeypatch, tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'argos.db'}"
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())
    raw_body = Path("tests/fixtures/ecowitt/gw2000a_ws90_3_3_2_form.txt").read_text()

    response = client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["duplicate"] is False
    assert body["observation_id"] is not None
    assert body["payload_key_count"] == 34
    assert body["unknown_field_count"] == 0
    assert body["warnings"] == []

    with get_sessionmaker()() as session:
        raw_reports = session.scalars(select(EcowittRawReport)).all()
        observations = session.scalars(select(WeatherObservation)).all()
        unknown_fields = session.scalars(select(UnknownField).order_by(UnknownField.field_name)).all()
        events = session.scalars(select(IngestionEvent)).all()

    assert len(raw_reports) == 1
    assert raw_reports[0].raw_body_text == raw_body
    assert raw_reports[0].payload_json["stationtype"] == "GW2000A_V3.3.2"
    assert raw_reports[0].payload_json["dateutc"] == "2026-07-10 12:45:26"
    assert raw_reports[0].parser_version == "gw2000a-ws90-3.3.2.3"
    assert len(observations) == 1
    assert observations[0].outdoor_temperature_c == pytest.approx(35.1)
    assert observations[0].wind_direction_avg10m_deg == pytest.approx(135)
    assert observations[0].rain_last_24h_mm == pytest.approx(0.0)
    assert observations[0].rain_week_mm == pytest.approx(0.6096)
    assert observations[0].piezo_rain_mm == pytest.approx(0.0)
    assert observations[0].battery_voltage == pytest.approx(3.02)
    assert observations[0].ws90_capacitor_voltage == pytest.approx(5.3)
    assert [field.field_name for field in unknown_fields] == []
    assert [event.event_type for event in events] == [
        "REPORT_RECEIVED",
    ]

    get_settings.cache_clear()
    reset_database_caches()


def test_ecowitt_upload_detects_duplicate_raw_capture(monkeypatch, tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'argos.db'}"
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())
    raw_body = "stationtype=GW2000A_V3.3.2&dateutc=2026-07-10+10%3A15%3A00"

    first = client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    second = client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    with get_sessionmaker()() as session:
        raw_reports = session.scalars(select(EcowittRawReport)).all()
        observations = session.scalars(select(WeatherObservation)).all()
        duplicate_events = session.scalars(
            select(IngestionEvent).where(IngestionEvent.event_type == "DUPLICATE")
        ).all()

    assert len(raw_reports) == 1
    assert len(observations) == 1
    assert len(duplicate_events) == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_ecowitt_upload_deduplicates_same_observation_with_different_transport_metadata(monkeypatch, tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'argos.db'}"
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())
    raw_body = Path("tests/fixtures/ecowitt/gw2000a_ws90_3_3_2_form.txt").read_text()

    first = client.post(
        "/api/v1/ecowitt/upload/test-token?transport_attempt=1",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    second = client.post(
        "/api/v1/ecowitt/upload/test-token?transport_attempt=2",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    with get_sessionmaker()() as session:
        raw_count = len(session.scalars(select(EcowittRawReport)).all())
        observation_count = len(session.scalars(select(WeatherObservation)).all())

    assert raw_count == 1
    assert observation_count == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_ecowitt_upload_rejects_invalid_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()

    client = TestClient(create_app())

    response = client.post("/api/v1/ecowitt/upload/wrong-token", content="stationtype=GW2000A")

    assert response.status_code == 403

    get_settings.cache_clear()
    reset_database_caches()
