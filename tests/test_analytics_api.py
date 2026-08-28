from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import math

from fastapi.testclient import TestClient
import pandas as pd

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.main import create_app
from argos.models.aemet import WeatherDailyObservation, WeatherStation
from argos.models.argos_node import ArgosIrrigationSectorMinuteAttribution, ArgosNodeFlowmeterMinute
from argos.models.ecowitt import WeatherObservation
from argos.models.field_event import FieldEvent
from argos.models.satellite import SatelliteMetric, SatelliteObservation, SatelliteSource, SatelliteZone
from argos.services.analytics import histogram_bins


def test_analytics_variables_and_unknown_variable(monkeypatch, tmp_path) -> None:
    client = analytics_client(monkeypatch, tmp_path)

    variables = client.get("/api/v1/analytics/variables")
    invalid = client.post("/api/v1/analytics/series", json={"variable_ids": ["missing.variable"]})

    assert variables.status_code == 200
    assert "ecowitt.outdoor_temperature" in {item["variable_id"] for item in variables.json()}
    assert "controller.sector_i_water_volume" in {item["variable_id"] for item in variables.json()}
    assert invalid.status_code == 422


def test_analytics_series_aggregation_correlation_matrix_distribution_and_trend(monkeypatch, tmp_path) -> None:
    client = analytics_client(monkeypatch, tmp_path)
    seed_analytics_data()

    series = client.post(
        "/api/v1/analytics/series",
        json={
            "variable_ids": ["ecowitt.outdoor_temperature", "aemet.temperature_mean"],
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-03T23:59:59Z",
            "frequency": "daily",
            "aggregation": "mean",
        },
    )
    assert series.status_code == 200
    assert len(series.json()["series"]) == 2
    assert series.json()["series"][0]["points"][0]["value"] == 11.0

    sector_series = client.post(
        "/api/v1/analytics/series",
        json={
            "variable_ids": ["controller.sector_i_water_volume"],
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-03T23:59:59Z",
            "frequency": "daily",
            "aggregation": "sum",
        },
    )
    assert sector_series.status_code == 200
    assert [point["value"] for point in sector_series.json()["series"][0]["points"]] == [0.5, 1.5, 2.5]

    hourly = client.post(
        "/api/v1/analytics/series",
        json={
            "variable_ids": ["ecowitt.outdoor_temperature"],
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-01T02:00:00Z",
            "frequency": "hourly",
            "aggregation": "mean",
        },
    )
    monthly = client.post(
        "/api/v1/analytics/series",
        json={
            "variable_ids": ["aemet.precipitation"],
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-31T23:59:59Z",
            "frequency": "monthly",
            "aggregation": "sum",
        },
    )
    assert hourly.status_code == 200
    assert monthly.status_code == 200
    assert monthly.json()["series"][0]["points"][0]["value"] == 6.0

    correlation = client.post(
        "/api/v1/analytics/correlation",
        json={
            "variable_x": "ecowitt.outdoor_temperature",
            "variable_y": "aemet.temperature_mean",
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-03T23:59:59Z",
            "frequency": "daily",
            "aggregation_x": "mean",
            "aggregation_y": "mean",
            "method": "pearson",
            "lag": "0",
        },
    )
    spearman = client.post(
        "/api/v1/analytics/correlation",
        json={
            "variable_x": "ecowitt.outdoor_temperature",
            "variable_y": "aemet.temperature_mean",
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-03T23:59:59Z",
            "frequency": "daily",
            "aggregation_x": "mean",
            "aggregation_y": "mean",
            "method": "spearman",
            "lag": "+1d",
        },
    )
    assert correlation.status_code == 200
    assert correlation.json()["pairs_count"] == 3
    assert correlation.json()["correlation"] > 0.99
    assert spearman.status_code == 200

    matrix = client.post(
        "/api/v1/analytics/correlation-matrix",
        json={
            "variable_ids": ["ecowitt.outdoor_temperature", "aemet.temperature_mean", "controller.flow_rate"],
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-03T23:59:59Z",
            "frequency": "daily",
            "aggregation": "mean",
            "method": "pearson",
        },
    )
    assert matrix.status_code == 200
    assert len(matrix.json()["matrix"]) == 3

    distribution = client.post(
        "/api/v1/analytics/distribution",
        json={
            "variable_id": "ecowitt.outdoor_temperature",
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-03T23:59:59Z",
            "frequency": "daily",
            "aggregation": "mean",
            "bins": 10,
        },
    )
    assert distribution.status_code == 200
    assert distribution.json()["summary"]["count"] == 3
    assert len(distribution.json()["histogram"]) == 10

    trend = client.post(
        "/api/v1/analytics/trend",
        json={
            "variable_id": "ecowitt.outdoor_temperature",
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-03T23:59:59Z",
            "frequency": "daily",
            "aggregation": "mean",
            "reference": "moving_average",
            "moving_window": 2,
            "include_field_events": True,
        },
    )
    assert trend.status_code == 200
    assert trend.json()["observations_count"] == 3
    assert trend.json()["points"][1]["anomaly"] is not None
    assert trend.json()["field_events"][0]["title"] == "Riego"


def test_analytics_satellite_series_filters_aoi(monkeypatch, tmp_path) -> None:
    client = analytics_client(monkeypatch, tmp_path)
    seed_satellite_data()

    response = client.post(
        "/api/v1/analytics/series",
        json={
            "variable_ids": ["satellite.ndvi"],
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-02T23:59:59Z",
            "frequency": "daily",
            "aggregation": "mean",
            "zone_slug": "olivos_pequenos",
            "quality_status": "valid",
        },
    )

    assert response.status_code == 200
    points = response.json()["series"][0]["points"]
    assert [point["zone_slug"] for point in points] == ["olivos_pequenos"]
    assert [point["value"] for point in points] == [0.4]


def test_density_histogram_sanitizes_degenerate_values() -> None:
    histogram = histogram_bins(pd.Series([0.42, 0.42, 0.42], dtype="float64"), "auto", density=True)

    assert histogram
    assert all(math.isfinite(bin_.count) for bin_ in histogram)


def analytics_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ARGOS_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())
    return TestClient(create_app())


def seed_analytics_data() -> None:
    with get_sessionmaker()() as session:
        station = WeatherStation(provider="aemet", external_id="6127X", name="AEMET", latitude=None, longitude=None, altitude_m=None, metadata_json={})
        session.add(station)
        session.flush()
        start = datetime(2026, 7, 1, tzinfo=UTC)
        for day_index in range(3):
            day = start + timedelta(days=day_index)
            session.add(WeatherObservation(observed_at_utc=day, received_at_utc=day, source="DIRECT", outdoor_temperature_c=10 + day_index))
            session.add(WeatherObservation(observed_at_utc=day + timedelta(hours=1), received_at_utc=day, source="DIRECT", outdoor_temperature_c=12 + day_index))
            session.add(
                WeatherDailyObservation(
                    station_id=station.id,
                    observation_date=date(2026, 7, 1 + day_index),
                    temperature_mean_c=11 + day_index,
                    precipitation_mm=day_index + 1,
                    raw_payload_json={},
                )
            )
            minute = ArgosNodeFlowmeterMinute(
                node_url="http://node",
                window_start_utc=day,
                window_end_utc=day + timedelta(minutes=1),
                pulse_count_start=0,
                pulse_count_end=27,
                pulse_delta=27,
                volume_l=1.0,
                avg_flow_l_min=1 + day_index,
                max_flow_l_min=2 + day_index,
                samples_count=1,
                relay1_state_end=day_index % 2 == 0,
                relay1_open_fraction=1.0 if day_index % 2 == 0 else 0.0,
            )
            session.add(minute)
            session.flush()
            session.add(
                ArgosIrrigationSectorMinuteAttribution(
                    flowmeter_minute_id=minute.id,
                    node_url=minute.node_url,
                    window_start_utc=minute.window_start_utc,
                    sector_id="I",
                    volume_l=day_index + 0.5,
                )
            )
        session.add(FieldEvent(occurred_at=start, event_type="irrigation", title="Riego", source="manual", zone_slug="olivos_pequenos"))
        session.commit()


def seed_satellite_data() -> None:
    with get_sessionmaker()() as session:
        source = SatelliteSource(code="copernicus_sentinel_2_l2a", name="Sentinel", provider="Copernicus", collection="sentinel-2-l2a")
        small = SatelliteZone(slug="olivos_pequenos", name="Olivos pequeños", geometry_geojson={}, geometry_hash="a")
        large = SatelliteZone(slug="olivos_grandes", name="Olivos grandes", geometry_geojson={}, geometry_hash="b")
        session.add_all([source, small, large])
        session.flush()
        for zone, value in ((small, 0.4), (large, 0.8)):
            observation = SatelliteObservation(
                source_id=source.id,
                zone_id=zone.id,
                external_item_id=f"item-{zone.slug}",
                acquisition_time=datetime(2026, 7, 1, tzinfo=UTC),
                collection="sentinel-2-l2a",
                valid_pixel_fraction=0.9,
                invalid_pixel_fraction=0.1,
                quality_status="valid",
                processing_version="test",
                geometry_hash=zone.geometry_hash,
            )
            session.add(observation)
            session.flush()
            session.add(SatelliteMetric(observation_id=observation.id, metric_code="ndvi", mean=value, unit="dimensionless"))
        session.commit()
