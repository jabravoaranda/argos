from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.main import create_app
from argos.models.satellite import SatelliteMetric, SatelliteObservation, SatelliteSource, SatelliteZone


def test_satellite_status_disabled_does_not_block_app_start(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ARGOS_SATELLITE_ENABLED", "false")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())
    response = client.get("/api/v1/satellite/status")

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    get_settings.cache_clear()
    reset_database_caches()


def test_satellite_export_csv_and_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())
    with get_sessionmaker()() as session:
        source = SatelliteSource(
            code="copernicus_sentinel_2_l2a",
            name="Sentinel-2 Level-2A",
            provider="Copernicus Data Space Ecosystem",
            collection="sentinel-2-l2a",
            spatial_resolution_m=10,
        )
        zone = SatelliteZone(
            name="Finca completa",
            geometry_geojson={"type": "Polygon", "coordinates": []},
            geometry_hash="hash",
            area_m2=1000,
        )
        session.add_all([source, zone])
        session.flush()
        observation = SatelliteObservation(
            source_id=source.id,
            zone_id=zone.id,
            external_item_id="item-1",
            acquisition_time=datetime(2026, 1, 1, tzinfo=UTC),
            collection="sentinel-2-l2a",
            cloud_cover_metadata=12.0,
            valid_pixel_fraction=0.75,
            invalid_pixel_fraction=0.25,
            quality_status="valid",
            processing_version="s2-indices-v1",
            geometry_hash="hash",
        )
        session.add(observation)
        session.flush()
        session.add(
            SatelliteMetric(
                observation_id=observation.id,
                metric_code="ndvi",
                mean=0.4,
                median=0.41,
                minimum=0.1,
                maximum=0.8,
                standard_deviation=0.05,
                percentile_10=0.2,
                percentile_25=0.3,
                percentile_75=0.5,
                percentile_90=0.6,
            )
        )
        session.commit()

    client = TestClient(create_app())

    json_response = client.get("/api/v1/satellite/export.json", params={"metric": "ndvi"})
    csv_response = client.get("/api/v1/satellite/export.csv", params={"metric": "ndvi"})

    assert json_response.status_code == 200
    assert json_response.json()[0]["zone_name"] == "Finca completa"
    assert csv_response.status_code == 200
    assert csv_response.text.splitlines()[0].startswith("acquisition_time,zone_name,metric_code")
    assert "2026-01-01T00:00:00" in csv_response.text

    get_settings.cache_clear()
    reset_database_caches()
