from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from argos.config.settings import Settings
from argos.database.base import Base
from argos.models.ingestion import SourceArtifact
from argos.models.satellite import SatelliteAsset, SatelliteObservation, SatelliteSource, SatelliteZone
from argos.services.data_layout import (
    apply_migration_plan,
    audit_staging,
    build_data_inventory,
    build_migration_plan,
    data_paths,
    retention_report,
    safe_data_path,
)


def test_inventory_classifies_files_and_records_checksums(tmp_path) -> None:
    settings = make_settings(tmp_path)
    data_root = data_paths(settings).data
    (data_root / "aemet").mkdir(parents=True)
    (data_root / "weather" / "raw").mkdir(parents=True)
    (data_root / "satellite" / "aoi").mkdir(parents=True)
    (data_root / "aemet" / "6127X.csv").write_text("fecha,tmed\n2026-01-01,12\n", encoding="utf-8")
    (data_root / "weather" / "raw" / "legacy.json").write_text('{"date":"2026-01-01"}', encoding="utf-8")
    (data_root / "satellite" / "aoi" / "preview.png").write_bytes(b"png")

    records = build_data_inventory(settings=settings)
    by_path = {record.relative_path: record for record in records}

    assert by_path["aemet/6127X.csv"].proposed_classification == "raw"
    assert by_path["weather/raw/legacy.json"].proposed_classification == "legacy"
    assert by_path["satellite/aoi/preview.png"].proposed_classification == "processed"
    assert by_path["satellite/aoi/preview.png"].sha256


def test_safe_data_path_rejects_traversal(tmp_path) -> None:
    root = tmp_path / "data"
    root.mkdir()

    with pytest.raises(ValueError, match="escapes data root"):
        safe_data_path("../outside.txt", root=root)


def test_migration_plan_dry_run_does_not_move_files(tmp_path) -> None:
    settings = make_settings(tmp_path)
    data_root = data_paths(settings).data
    source = data_root / "aemet" / "6127X.csv"
    source.parent.mkdir(parents=True)
    source.write_text("fecha,tmed\n2026-01-01,12\n", encoding="utf-8")

    with in_memory_session() as session:
        plan = build_migration_plan(session=session, settings=settings)

    assert source.exists()
    assert plan[0].source_path == "aemet/6127X.csv"
    assert plan[0].destination_path == "raw/aemet/6127X.csv"


def test_apply_migration_plan_moves_and_is_idempotent(tmp_path) -> None:
    settings = make_settings(tmp_path)
    data_root = data_paths(settings).data
    source = data_root / "aemet" / "6127X.csv"
    source.parent.mkdir(parents=True)
    source.write_text("fecha,tmed\n2026-01-01,12\n", encoding="utf-8")

    with in_memory_session() as session:
        first_plan = build_migration_plan(session=session, settings=settings)
        apply_migration_plan(session=session, plan=first_plan, settings=settings)
        second_plan = build_migration_plan(session=session, settings=settings)
        artifact = session.scalar(select(SourceArtifact))

    assert not source.exists()
    assert (data_root / "raw" / "aemet" / "6127X.csv").exists()
    assert second_plan == []
    assert artifact is not None
    assert artifact.run_id is None
    assert artifact.metadata_json["historical_ingestion_run"] == "not_reconstructed"


def test_apply_migration_plan_does_not_overwrite_conflicts(tmp_path) -> None:
    settings = make_settings(tmp_path)
    data_root = data_paths(settings).data
    source = data_root / "aemet" / "6127X.csv"
    destination = data_root / "raw" / "aemet" / "6127X.csv"
    source.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    source.write_text("original", encoding="utf-8")
    destination.write_text("different", encoding="utf-8")

    with in_memory_session() as session:
        plan = build_migration_plan(session=session, settings=settings)
        apply_migration_plan(session=session, plan=plan, settings=settings)

    assert source.exists()
    assert destination.read_text(encoding="utf-8") == "different"
    assert plan[0].conflict == "destination_exists_with_different_checksum"


def test_satellite_asset_path_updates_to_relative_processed_path(tmp_path) -> None:
    settings = make_settings(tmp_path)
    data_root = data_paths(settings).data
    source = data_root / "satellite" / "aoi" / "preview.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png")

    with in_memory_session() as session:
        observation = create_satellite_observation(session)
        session.add(
            SatelliteAsset(
                observation_id=observation.id,
                asset_type="preview_rgb_png",
                storage_path="satellite/aoi/preview.png",
                mime_type="image/png",
                checksum_sha256=sha256(source.read_bytes()).hexdigest(),
                size_bytes=3,
            )
        )
        session.commit()
        plan = build_migration_plan(session=session, settings=settings)
        apply_migration_plan(session=session, plan=plan, settings=settings)
        asset = session.scalar(select(SatelliteAsset))

    assert asset is not None
    assert asset.storage_path == "processed/satellite/aoi/preview.png"


def test_retention_report_protects_raw_legacy_and_quarantine(tmp_path) -> None:
    settings = make_settings(tmp_path)
    data_root = data_paths(settings).data
    (data_root / "raw").mkdir(parents=True)
    (data_root / "legacy").mkdir()
    (data_root / "quarantine").mkdir()
    (data_root / "raw" / "source.csv").write_text("x", encoding="utf-8")
    (data_root / "legacy" / "old.json").write_text("{}", encoding="utf-8")
    (data_root / "quarantine" / "bad.bin").write_bytes(b"x")

    records = build_data_inventory(settings=settings)
    report = retention_report(records=records, now=datetime.now(UTC) + timedelta(days=365))

    assert {item.category for item in report} == {"raw", "legacy", "quarantine"}
    assert all(not item.eligible for item in report)


def test_audit_staging_reports_unregistered_empty_file(tmp_path) -> None:
    settings = make_settings(tmp_path)
    staging_file = data_paths(settings).staging / "partial.tmp"
    staging_file.parent.mkdir(parents=True)
    staging_file.write_bytes(b"")

    with in_memory_session() as session:
        issues = audit_staging(session=session, settings=settings, older_than=timedelta(seconds=0))

    assert {issue.issue for issue in issues} >= {"unregistered_file", "partial_or_empty_file"}


def test_settings_derive_layout_directories(tmp_path) -> None:
    settings = make_settings(tmp_path)
    paths = data_paths(settings)

    assert paths.raw == paths.data / "raw"
    assert paths.processed == paths.data / "processed"


def create_satellite_observation(session: Session) -> SatelliteObservation:
    source = SatelliteSource(code="sentinel-2-l2a", name="Sentinel", provider="Copernicus", collection="c")
    zone = SatelliteZone(slug="aoi", name="AOI", geometry_geojson={}, geometry_hash="hash")
    session.add_all([source, zone])
    session.flush()
    observation = SatelliteObservation(
        source_id=source.id,
        zone_id=zone.id,
        external_item_id="item",
        acquisition_time=datetime(2026, 1, 1, tzinfo=UTC),
        collection="c",
        quality_status="valid",
        processing_version="v1",
        geometry_hash="hash",
    )
    session.add(observation)
    session.flush()
    return observation


def make_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        argos_admin_token="test-admin-token",
        ecowitt_ingest_token="test-token",
        argos_data_dir=str(tmp_path / "data"),
    )


def in_memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
