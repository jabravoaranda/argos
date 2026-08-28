from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.integrations.ecowitt_cloud import EcowittCloudClient, EcowittCloudCredentials
from argos.main import create_app
from argos.models.ecowitt import EcowittCloudRawReport, WeatherObservation
from argos.models.ingestion import IngestionRun, SyncCursor
from argos.services.ecowitt_backfill import BackfillRangeError, backfill_ecowitt_cloud_range


class FakeCloudClient(EcowittCloudClient):
    def __init__(self) -> None:
        super().__init__(
            base_url="https://api.ecowitt.net",
            api_version="v3",
            credentials=EcowittCloudCredentials(application_key="app", api_key="api", mac="AABBCCDDEEFF"),
        )
        object.__setattr__(self, "calls", [])

    def get_history(
        self,
        *,
        start: datetime,
        end: datetime,
        callbacks: tuple[str, ...],
    ) -> dict:
        self.calls.append((start, end, callbacks))
        return {
            "code": 0,
            "data": {
                "outdoor": {
                    "temperature": {"list": [{"time": "2026-07-10 12:45:00", "value": "95.18", "unit": "F"}]},
                    "humidity": {"list": [{"time": "2026-07-10 12:45:00", "value": "24", "unit": "%"}]},
                },
                "rainfall_piezo": {
                    "daily": {"list": [{"time": "2026-07-10 12:45:00", "value": "0.10", "unit": "in"}]}
                },
            },
        }


def test_backfill_ecowitt_cloud_range_fetches_parses_and_imports(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    start = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    end = datetime(2026, 7, 10, 13, 0, tzinfo=UTC)
    client = FakeCloudClient()

    with get_sessionmaker()() as session:
        result = backfill_ecowitt_cloud_range(
            session=session,
            client=client,
            gateway_identifier="GW2000A",
            station_type="GW2000A_V3.3.2",
            start=start,
            end=end,
            callbacks=("outdoor", "rainfall_piezo"),
        )

        observation = session.scalar(select(WeatherObservation))
        raw_report = session.scalar(select(EcowittCloudRawReport))
        ingestion_run = session.scalar(select(IngestionRun))
        cursor = session.scalar(select(SyncCursor))
        assert client.calls == [(start, end, ("outdoor", "rainfall_piezo"))]
        assert result.imported_count == 1
        assert result.duplicate_count == 0
        assert result.warning_count == 0
        assert observation is not None
        assert observation.source == "BACKFILLED"
        assert observation.outdoor_temperature_c == 35.1
        assert observation.rain_day_mm == 2.54
        assert raw_report is not None
        assert ingestion_run is not None
        assert raw_report.ingestion_run_id == ingestion_run.id
        assert observation.ingestion_run_id == ingestion_run.id
        assert ingestion_run.status == "completed"
        assert cursor is not None
        assert cursor.cursor_value_json == {"last_successful_end_utc": end.isoformat()}
        assert raw_report.requested_start_utc == start.replace(tzinfo=None)
        assert raw_report.requested_end_utc == end.replace(tzinfo=None)

    get_settings.cache_clear()
    reset_database_caches()


def test_backfill_ecowitt_cloud_range_reports_adapter_warnings(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    class WarningCloudClient(FakeCloudClient):
        def get_history(self, *, start: datetime, end: datetime, callbacks: tuple[str, ...]) -> dict:
            return {"code": 0, "data": {"soil": {"soilmoisture1": {"list": [{"time": "2026-07-10", "value": "33"}]}}}}

    with get_sessionmaker()() as session:
        result = backfill_ecowitt_cloud_range(
            session=session,
            client=WarningCloudClient(),
            gateway_identifier="GW2000A",
            start=datetime(2026, 7, 10, tzinfo=UTC),
            end=datetime(2026, 7, 11, tzinfo=UTC),
        )

        assert result.imported_count == 0
        assert result.warning_count == 1
        assert "soilmoisture1" in result.warnings[0]

    get_settings.cache_clear()
    reset_database_caches()


def test_ecowitt_cloud_admin_backfill_endpoint_imports_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ARGOS_ADMIN_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    fake_client = FakeCloudClient()
    monkeypatch.setattr("argos.api.weather.EcowittCloudClient.from_settings", lambda settings: fake_client)

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/weather/ecowitt-cloud/backfill",
        params={
            "gateway_identifier": "GW2000A",
            "from": "2026-07-10T12:00:00Z",
            "to": "2026-07-10T13:00:00Z",
        },
        headers={"X-ARGOS-ADMIN-TOKEN": "test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported_count"] == 1
    assert payload["duplicate_count"] == 0
    assert payload["warning_count"] == 0

    get_settings.cache_clear()
    reset_database_caches()


def test_backfill_ecowitt_cloud_range_rejects_invalid_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = FakeCloudClient()
    start = datetime(2026, 7, 10, 13, 0, tzinfo=UTC)
    end = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)

    with get_sessionmaker()() as session, pytest.raises(BackfillRangeError, match="end must be after start"):
        backfill_ecowitt_cloud_range(
            session=session,
            client=client,
            gateway_identifier="GW2000A",
            start=start,
            end=end,
        )

    assert client.calls == []
    get_settings.cache_clear()
    reset_database_caches()


def test_backfill_ecowitt_cloud_range_rejects_oversized_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = FakeCloudClient()
    start = datetime(2026, 7, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 7, 12, 0, 0, tzinfo=UTC)

    with get_sessionmaker()() as session, pytest.raises(BackfillRangeError, match="24 hours"):
        backfill_ecowitt_cloud_range(
            session=session,
            client=client,
            gateway_identifier="GW2000A",
            start=start,
            end=end,
            max_range_hours=24,
        )

    assert client.calls == []
    get_settings.cache_clear()
    reset_database_caches()
