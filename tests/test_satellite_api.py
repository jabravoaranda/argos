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


def test_satellite_read_filters_return_empty_for_unknown_aoi(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    client = TestClient(create_app())

    latest_response = client.get("/api/v1/satellite/latest", params={"aoi_slug": "olivos_pequenos"})
    observations_response = client.get("/api/v1/satellite/observations", params={"aoi_slug": "olivos_pequenos"})
    bounds_response = client.get("/api/v1/satellite/bounds", params={"aoi_slug": "olivos_pequenos"})

    assert latest_response.status_code == 200
    assert latest_response.json() is None
    assert observations_response.status_code == 200
    assert observations_response.json() == []
    assert bounds_response.status_code == 200
    assert bounds_response.json() == {"first_date": None, "last_date": None}

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
            slug="olivos_pequenos",
            name="Olivos pequeños",
            geometry_geojson={"type": "Polygon", "coordinates": []},
            geometry_hash="hash",
            area_m2=1000,
        )
        second_zone = SatelliteZone(
            slug="olivos_grandes",
            name="Olivos grandes",
            geometry_geojson={"type": "Polygon", "coordinates": []},
            geometry_hash="hash-2",
            area_m2=2000,
        )
        session.add_all([source, zone, second_zone])
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
        second_observation = SatelliteObservation(
            source_id=source.id,
            zone_id=second_zone.id,
            external_item_id="item-2",
            acquisition_time=datetime(2026, 2, 1, tzinfo=UTC),
            collection="sentinel-2-l2a",
            cloud_cover_metadata=5.0,
            valid_pixel_fraction=0.8,
            invalid_pixel_fraction=0.2,
            quality_status="valid",
            processing_version="s2-indices-v1",
            geometry_hash="hash-2",
        )
        session.add(second_observation)
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
        session.add(
            SatelliteMetric(
                observation_id=second_observation.id,
                metric_code="ndvi",
                mean=0.5,
                median=0.51,
                minimum=0.2,
                maximum=0.9,
                standard_deviation=0.04,
                percentile_10=0.3,
                percentile_25=0.4,
                percentile_75=0.6,
                percentile_90=0.7,
            )
        )
        session.commit()

    client = TestClient(create_app())

    json_response = client.get("/api/v1/satellite/export.json", params={"metric": "ndvi"})
    csv_response = client.get("/api/v1/satellite/export.csv", params={"metric": "ndvi"})
    filtered_response = client.get(
        "/api/v1/satellite/export.json",
        params={"metric": "ndvi", "aoi_slug": "olivos_grandes"},
    )
    bounds_response = client.get("/api/v1/satellite/bounds")

    assert json_response.status_code == 200
    assert json_response.json()[0]["zone_name"] == "Olivos pequeños"
    assert json_response.json()[0]["aoi_slug"] == "olivos_pequenos"
    assert csv_response.status_code == 200
    assert csv_response.text.splitlines()[0].startswith("acquisition_time,aoi_slug,zone_name,metric_code")
    assert "2026-01-01T00:00:00" in csv_response.text
    assert filtered_response.status_code == 200
    assert [row["aoi_slug"] for row in filtered_response.json()] == ["olivos_grandes"]
    assert bounds_response.status_code == 200
    assert bounds_response.json() == {"first_date": "2026-01-01", "last_date": "2026-02-01"}

    get_settings.cache_clear()
    reset_database_caches()
