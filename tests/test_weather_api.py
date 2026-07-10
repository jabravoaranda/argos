from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.main import create_app
from argos.models.ecowitt import DailyStatistic, WeeklyStatistic


def test_weather_latest_observations_and_gateway_status(monkeypatch, tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'argos.db'}"
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ECOWITT_OFFLINE_AFTER_SECONDS", "180")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())
    raw_body = Path("tests/fixtures/ecowitt/gw2000a_ws90_3_3_2_form.txt").read_text()
    upload_response = client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert upload_response.status_code == 200

    latest_response = client.get("/api/v1/weather/latest")
    assert latest_response.status_code == 200
    latest = latest_response.json()
    assert latest["outdoor_temperature_c"] == 35.1
    assert latest["rain_last_24h_mm"] == 0.0
    assert latest["ws90_capacitor_voltage"] == 5.3

    observations_response = client.get(
        "/api/v1/weather/observations",
        params={"from": "2026-07-10T12:00:00Z", "to": "2026-07-10T13:00:00Z"},
    )
    assert observations_response.status_code == 200
    observations = observations_response.json()
    assert len(observations) == 1
    assert observations[0]["id"] == latest["id"]

    status_response = client.get("/api/v1/weather/gateway/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["gateway_id"] is not None
    assert status["station_type"] == "GW2000A_V3.3.2"
    assert status["online"] is True
    assert status["offline_after_seconds"] == 180

    get_settings.cache_clear()
    reset_database_caches()


def test_weather_daily_and_weekly_summaries(monkeypatch, tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'argos.db'}"
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())
    raw_body = Path("tests/fixtures/ecowitt/gw2000a_ws90_3_3_2_form.txt").read_text()
    second_body = raw_body.replace("dateutc=2026-07-10+12:45:26", "dateutc=2026-07-10+12:46:26").replace(
        "tempf=95.18",
        "tempf=96.98",
    )

    assert client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    ).status_code == 200
    assert client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=second_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    ).status_code == 200

    daily_response = client.get(
        "/api/v1/weather/summary/daily",
        params={"from": "2026-07-10T00:00:00Z", "to": "2026-07-10T23:59:59Z"},
    )
    assert daily_response.status_code == 200
    daily = daily_response.json()
    assert len(daily) == 1
    assert daily[0]["period_start"] == "2026-07-10"
    assert daily[0]["period_end"] == "2026-07-10"
    assert daily[0]["gateway_id"] is not None
    assert daily[0]["sample_count"] == 2
    assert daily[0]["outdoor_temperature_min_c"] == pytest.approx(35.1)
    assert daily[0]["outdoor_temperature_max_c"] == pytest.approx(36.1)
    assert daily[0]["outdoor_temperature_mean_c"] == pytest.approx(35.6)
    assert daily[0]["wind_gust_max_ms"] == pytest.approx(1.3992352)
    assert daily[0]["rain_day_max_mm"] == pytest.approx(0.0)

    weekly_response = client.get(
        "/api/v1/weather/summary/weekly",
        params={"from": "2026-07-01T00:00:00Z", "to": "2026-07-31T23:59:59Z"},
    )
    assert weekly_response.status_code == 200
    weekly = weekly_response.json()
    assert len(weekly) == 1
    assert weekly[0]["period_start"] == "2026-07-06"
    assert weekly[0]["period_end"] == "2026-07-10"
    assert weekly[0]["sample_count"] == 2

    with get_sessionmaker()() as session:
        assert len(session.scalars(select(DailyStatistic)).all()) == 1
        assert len(session.scalars(select(WeeklyStatistic)).all()) == 1

    recompute_response = client.post(
        "/api/v1/weather/statistics/recompute",
        params={"from": "2026-07-01T00:00:00Z", "to": "2026-07-31T23:59:59Z"},
        headers={"X-ARGOS-ADMIN-TOKEN": "test-token"},
    )
    assert recompute_response.status_code == 200
    assert recompute_response.json() == {"daily_count": 1, "weekly_count": 1}

    with get_sessionmaker()() as session:
        assert len(session.scalars(select(DailyStatistic)).all()) == 1
        assert len(session.scalars(select(WeeklyStatistic)).all()) == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_weather_admin_endpoints_and_gap_detection(monkeypatch, tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'argos.db'}"
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ECOWITT_EXPECTED_INTERVAL_SECONDS", "60")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())
    raw_body = Path("tests/fixtures/ecowitt/gw2000a_ws90_3_3_2_form.txt").read_text()
    delayed_body = raw_body.replace("dateutc=2026-07-10+12:45:26", "dateutc=2026-07-10+12:50:26")

    assert client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=raw_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    ).status_code == 200
    assert client.post(
        "/api/v1/ecowitt/upload/test-token",
        content=delayed_body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    ).status_code == 200

    assert client.get("/api/v1/weather/admin/data-gaps").status_code == 403

    admin_headers = {"X-ARGOS-ADMIN-TOKEN": "test-token"}
    gaps = client.get("/api/v1/weather/admin/data-gaps", headers=admin_headers).json()
    assert len(gaps) == 1
    assert gaps[0]["expected_reports"] == 4
    assert gaps[0]["resolved"] is False

    raw_reports = client.get("/api/v1/weather/admin/raw-reports", params={"limit": 1}, headers=admin_headers).json()
    assert len(raw_reports) == 1
    assert raw_reports[0]["parser_version"] == "gw2000a-ws90-3.3.2.3"

    events = client.get("/api/v1/weather/admin/events", params={"limit": 10}, headers=admin_headers).json()
    assert any(event["event_type"] == "REPORT_RECEIVED" for event in events)

    unknown_fields = client.get("/api/v1/weather/admin/unknown-fields", headers=admin_headers).json()
    assert unknown_fields == []

    get_settings.cache_clear()
    reset_database_caches()


def test_weather_latest_returns_null_when_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())

    assert client.get("/api/v1/weather/latest").json() is None
    assert client.get("/api/v1/weather/observations").json() == []
    assert client.get("/api/v1/weather/gateway/status").json()["online"] is False

    get_settings.cache_clear()
    reset_database_caches()
