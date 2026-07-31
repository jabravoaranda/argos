from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.main import create_app
from argos.models.ecowitt import EcowittCloudRawReport, GatewayAlias, Station, WeatherObservation
from argos.services.ecowitt_backfill import import_backfilled_observation


def test_import_backfilled_observation_creates_cloud_raw_and_backfilled_observation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    with get_sessionmaker()() as session:
        result = import_backfilled_observation(
            session=session,
            gateway_identifier="GW2000A",
            station_type="GW2000A_V3.3.2",
            observed_at_utc=datetime(2026, 7, 10, 12, 45, 26, tzinfo=UTC),
            normalized_values={"outdoor_temperature_c": 35.1, "rain_day_mm": 0.0},
            cloud_payload={"time": "2026-07-10 12:45:26", "temp": {"value": "95.18"}},
        )

        observation = session.get(WeatherObservation, result.observation_id)
        station = session.scalar(select(Station))
        assert result.duplicate is False
        assert station is not None
        assert station.slug == "tomillar"
        assert observation is not None
        assert observation.station_uuid == station.uuid
        assert observation.source == "BACKFILLED"
        assert observation.raw_report_id is None
        assert observation.cloud_raw_report_id == result.cloud_raw_report_id
        assert observation.outdoor_temperature_c == pytest.approx(35.1)
        assert session.get(EcowittCloudRawReport, result.cloud_raw_report_id) is not None
        assert session.get(EcowittCloudRawReport, result.cloud_raw_report_id).station_uuid == station.uuid

    get_settings.cache_clear()
    reset_database_caches()


def test_import_backfilled_observation_preserves_cloud_raw_but_deduplicates_existing_direct_observation(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
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

    with get_sessionmaker()() as session:
        direct_observation = session.scalar(select(WeatherObservation))
        assert direct_observation is not None

        result = import_backfilled_observation(
            session=session,
            gateway_identifier="GW2000A",
            station_type="GW2000A_V3.3.2",
            observed_at_utc=direct_observation.observed_at_utc,
            normalized_values={"outdoor_temperature_c": 12.3, "dew_point_c": 19.0},
            cloud_payload={"time": "2026-07-10 12:45:26", "temp": {"value": "95.18"}},
        )

        session.refresh(direct_observation)
        assert result.duplicate is True
        assert result.duplicate_reason == "existing_observation_timestamp"
        assert result.observation_id == direct_observation.id
        assert direct_observation.outdoor_temperature_c != 12.3
        assert direct_observation.dew_point_c == 19.0
        assert len(session.scalars(select(EcowittCloudRawReport)).all()) == 1
        assert len(session.scalars(select(WeatherObservation)).all()) == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_import_backfilled_observation_resolves_existing_gateway_by_cloud_mac_alias(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
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

    with get_sessionmaker()() as session:
        direct_observation = session.scalar(select(WeatherObservation))
        assert direct_observation is not None

        first = import_backfilled_observation(
            session=session,
            gateway_identifier="GW2000A",
            station_type="GW2000A_V3.3.2",
            gateway_aliases={"ecowitt_cloud_mac": "AA:BB:CC:DD:EE:FF"},
            observed_at_utc=datetime(2026, 7, 10, 12, 50, 26, tzinfo=UTC),
            normalized_values={"outdoor_temperature_c": 35.1},
            cloud_payload={"time": "2026-07-10 12:50:26", "temp": {"value": "95.18"}},
        )
        second = import_backfilled_observation(
            session=session,
            gateway_identifier="AABBCCDDEEFF",
            station_type="GW2000A_V3.3.2",
            gateway_aliases={"ecowitt_cloud_mac": "aa-bb-cc-dd-ee-ff"},
            observed_at_utc=direct_observation.observed_at_utc,
            normalized_values={"outdoor_temperature_c": 35.1},
            cloud_payload={"time": "2026-07-10 12:45:26", "temp": {"value": "95.18"}},
        )

        aliases = session.scalars(select(GatewayAlias)).all()
        observations = session.scalars(select(WeatherObservation)).all()
        assert first.duplicate is False
        assert second.duplicate is True
        assert second.duplicate_reason == "existing_observation_timestamp"
        assert len(aliases) == 1
        assert aliases[0].alias_value == "AABBCCDDEEFF"
        assert len({observation.gateway_id for observation in observations}) == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_import_backfilled_observation_deduplicates_cloud_raw_after_alias_resolution(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    kwargs = {
        "station_type": "GW2000A_V3.3.2",
        "observed_at_utc": datetime(2026, 7, 10, 12, 50, 26, tzinfo=UTC),
        "normalized_values": {"outdoor_temperature_c": 35.1},
        "cloud_payload": {"time": "2026-07-10 12:50:26", "temp": {"value": "95.18"}},
        "gateway_aliases": {"ecowitt_cloud_mac": "AA:BB:CC:DD:EE:FF"},
    }

    with get_sessionmaker()() as session:
        first = import_backfilled_observation(session=session, gateway_identifier="GW2000A", **kwargs)
        second = import_backfilled_observation(session=session, gateway_identifier="AABBCCDDEEFF", **kwargs)

        assert first.duplicate is False
        assert second.duplicate is True
        assert second.duplicate_reason == "cloud_payload_hash"
        assert first.cloud_raw_report_id == second.cloud_raw_report_id
        assert len(session.scalars(select(EcowittCloudRawReport)).all()) == 1
        assert len(session.scalars(select(WeatherObservation)).all()) == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_import_backfilled_observation_is_idempotent_by_cloud_payload_hash(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    kwargs = {
        "gateway_identifier": "GW2000A_V3.3.2",
        "station_type": "GW2000A_V3.3.2",
        "observed_at_utc": datetime(2026, 7, 10, 12, 45, 26, tzinfo=UTC),
        "normalized_values": {"outdoor_temperature_c": 35.1},
        "cloud_payload": {"time": "2026-07-10 12:45:26", "temp": {"value": "95.18"}},
    }

    with get_sessionmaker()() as session:
        first = import_backfilled_observation(session=session, **kwargs)
        second = import_backfilled_observation(session=session, **kwargs)

        assert first.duplicate is False
        assert second.duplicate is True
        assert second.duplicate_reason == "cloud_payload_hash"
        assert first.cloud_raw_report_id == second.cloud_raw_report_id
        assert len(session.scalars(select(EcowittCloudRawReport)).all()) == 1
        assert len(session.scalars(select(WeatherObservation)).all()) == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_import_backfilled_observation_rejects_unknown_normalized_fields(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    with get_sessionmaker()() as session, pytest.raises(ValueError, match="not_a_weather_field"):
        import_backfilled_observation(
            session=session,
            gateway_identifier="GW2000A_V3.3.2",
            observed_at_utc=datetime(2026, 7, 10, 12, 45, 26, tzinfo=UTC),
            normalized_values={"not_a_weather_field": 1.0},
            cloud_payload={"time": "2026-07-10 12:45:26"},
        )

    get_settings.cache_clear()
    reset_database_caches()
