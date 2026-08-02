from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from argos.database.base import Base
from argos import models as _models


def test_initial_schema_tables_are_registered() -> None:
    expected_tables = {
        "stations",
        "gateways",
        "gateway_aliases",
        "ecowitt_raw_reports",
        "ecowitt_cloud_raw_reports",
        "weather_observations",
        "daily_statistics",
        "weekly_statistics",
        "unknown_fields",
        "ingestion_events",
        "data_gaps",
        "argos_node_flowmeter_minutes",
        "argos_node_flowmeter_reset_events",
        "argos_node_flowmeter_sessions",
        "field_events",
    }

    assert expected_tables <= set(Base.metadata.tables)
    assert _models.Station.__tablename__ == "stations"
    assert _models.Gateway.__tablename__ == "gateways"
    assert _models.ArgosNodeFlowmeterMinute.__tablename__ == "argos_node_flowmeter_minutes"
    assert _models.ArgosNodeFlowmeterSession.__tablename__ == "argos_node_flowmeter_sessions"
    assert _models.FieldEvent.__tablename__ == "field_events"


def test_weather_observation_natural_uniqueness_is_registered() -> None:
    constraint_names = {
        constraint.name
        for constraint in Base.metadata.tables["weather_observations"].constraints
    }

    assert "uq_weather_observations_gateway_observed_source" in constraint_names


def test_satellite_asset_natural_uniqueness_is_registered() -> None:
    constraint_names = {
        constraint.name
        for constraint in Base.metadata.tables["satellite_assets"].constraints
    }

    assert "uq_satellite_assets_observation_type" in constraint_names


def test_weather_observation_duplicate_gateway_timestamp_source_is_rejected() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    observed_at = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        gateway = _models.Gateway(uuid="gw", mac_address="gw")
        session.add(gateway)
        session.flush()
        session.add_all(
            [
                _models.WeatherObservation(
                    gateway_id=gateway.id,
                    source="DIRECT",
                    observed_at_utc=observed_at,
                    received_at_utc=observed_at,
                ),
                _models.WeatherObservation(
                    gateway_id=gateway.id,
                    source="DIRECT",
                    observed_at_utc=observed_at,
                    received_at_utc=observed_at,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_satellite_asset_duplicate_observation_type_is_rejected() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    observed_at = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        source = _models.SatelliteSource(code="sentinel-2-l2a", name="Sentinel", provider="Copernicus", collection="c")
        zone = _models.SatelliteZone(slug="north", name="North", geometry_geojson={}, geometry_hash="hash")
        session.add_all([source, zone])
        session.flush()
        observation = _models.SatelliteObservation(
            source_id=source.id,
            zone_id=zone.id,
            external_item_id="item",
            acquisition_time=observed_at,
            collection="c",
            quality_status="valid",
            processing_version="v1",
            geometry_hash="hash",
        )
        session.add(observation)
        session.flush()
        session.add_all(
            [
                _models.SatelliteAsset(
                    observation_id=observation.id,
                    asset_type="preview_rgb_png",
                    storage_path="a.png",
                    mime_type="image/png",
                    checksum_sha256="a",
                    size_bytes=1,
                ),
                _models.SatelliteAsset(
                    observation_id=observation.id,
                    asset_type="preview_rgb_png",
                    storage_path="b.png",
                    mime_type="image/png",
                    checksum_sha256="b",
                    size_bytes=1,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()
