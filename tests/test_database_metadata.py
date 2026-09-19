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
        "data_sources",
        "ingestion_runs",
        "ingestion_items",
        "sync_cursors",
        "source_artifacts",
        "data_gaps",
        "argos_irrigation_sector_minute_attributions",
        "argos_node_flowmeter_minutes",
        "argos_node_flowmeter_reset_events",
        "argos_node_flowmeter_sessions",
        "field_events",
        "field_event_photos",
        "field_event_plant_units",
        "plant_irrigation_lines",
        "plant_matrix_cells",
        "plant_parcels",
        "plant_units",
    }

    assert expected_tables <= set(Base.metadata.tables)
    assert _models.Station.__tablename__ == "stations"
    assert _models.Gateway.__tablename__ == "gateways"
    assert _models.ArgosNodeFlowmeterMinute.__tablename__ == "argos_node_flowmeter_minutes"
    assert _models.ArgosIrrigationSectorMinuteAttribution.__tablename__ == "argos_irrigation_sector_minute_attributions"
    assert _models.ArgosNodeFlowmeterSession.__tablename__ == "argos_node_flowmeter_sessions"
    assert _models.FieldEvent.__tablename__ == "field_events"
    assert _models.FieldEventPhoto.__tablename__ == "field_event_photos"
    assert _models.PlantUnit.__tablename__ == "plant_units"
    assert _models.PlantMatrixCell.__tablename__ == "plant_matrix_cells"
    assert _models.DataSource.__tablename__ == "data_sources"
    assert _models.IngestionRun.__tablename__ == "ingestion_runs"


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


def test_ingestion_traceability_constraints_are_registered() -> None:
    data_source_constraints = {
        constraint.name for constraint in Base.metadata.tables["data_sources"].constraints
    }
    item_constraints = {
        constraint.name for constraint in Base.metadata.tables["ingestion_items"].constraints
    }
    cursor_constraints = {
        constraint.name for constraint in Base.metadata.tables["sync_cursors"].constraints
    }

    assert "uq_data_sources_code" in data_source_constraints
    assert "uq_ingestion_items_run_item_key" in item_constraints
    assert "uq_sync_cursors_source_scope_key" in cursor_constraints


def test_plant_inventory_constraints_are_registered() -> None:
    plant_constraints = {constraint.name for constraint in Base.metadata.tables["plant_units"].constraints}
    cell_constraints = {constraint.name for constraint in Base.metadata.tables["plant_matrix_cells"].constraints}
    event_link_constraints = {constraint.name for constraint in Base.metadata.tables["field_event_plant_units"].constraints}

    assert "uq_plant_units_public_code" in plant_constraints
    assert "uq_plant_units_parcel_matrix_position" in plant_constraints
    assert "ck_plant_units_matrix_row" in plant_constraints
    assert "uq_plant_matrix_cells_parcel_position" in cell_constraints
    assert "uq_field_event_plant_units_event_plant" in event_link_constraints


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
