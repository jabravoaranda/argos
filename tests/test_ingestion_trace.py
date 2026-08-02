from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from argos.database.base import Base
from argos.models.ingestion import IngestionRun, SourceArtifact, SyncCursor
from argos.services.ingestion_trace import (
    COMPLETED,
    FAILED,
    INTERRUPTED,
    abandoned_runs,
    audit_source_artifacts,
    create_ingestion_item,
    create_source_artifact,
    finalize_ingestion_run,
    ingestion_run,
    mark_run_interrupted,
    start_ingestion_run,
    update_sync_cursor,
)


def test_ingestion_run_context_redacts_parameters_and_finalizes() -> None:
    with in_memory_session() as session:
        with ingestion_run(
            session,
            source_code="ecowitt_cloud",
            mode="backfill",
            trigger="manual",
            parameters_json={"api_key": "secret", "gateway": "GW2000A"},
        ) as run:
            run.inserted_count = 1

        stored = session.scalar(select(IngestionRun))

    assert stored is not None
    assert stored.status == COMPLETED
    assert stored.parameters_json == {"api_key": "<redacted>", "gateway": "GW2000A"}


def test_ingestion_run_context_marks_failures() -> None:
    with in_memory_session() as session:
        with pytest.raises(RuntimeError):
            with ingestion_run(session, source_code="aemet_api", mode="sync", trigger="test"):
                raise RuntimeError("boom")

        stored = session.scalar(select(IngestionRun))

    assert stored is not None
    assert stored.status == FAILED
    assert "RuntimeError: boom" == stored.error_summary


def test_ingestion_items_are_unique_per_run() -> None:
    with in_memory_session() as session:
        run = start_ingestion_run(session, source_code="aemet_api", mode="sync", trigger="test")
        create_ingestion_item(session, run=run, item_key="6127X:2026-01-01", item_type="aemet_interval")

        with pytest.raises(IntegrityError):
            create_ingestion_item(session, run=run, item_key="6127X:2026-01-01", item_type="aemet_interval")


def test_sync_cursor_only_advances_after_successful_run() -> None:
    with in_memory_session() as session:
        run = start_ingestion_run(session, source_code="aemet_api", mode="sync", trigger="test")

        with pytest.raises(ValueError, match="successful run"):
            update_sync_cursor(
                session,
                source_code="aemet_api",
                scope="station",
                scope_key="6127X",
                cursor_type="date",
                cursor_value_json={"last_successful_date": "2026-01-01"},
                last_successful_run=run,
            )

        finalize_ingestion_run(run)
        run_id = run.id
        cursor = update_sync_cursor(
            session,
            source_code="aemet_api",
            scope="station",
            scope_key="6127X",
            cursor_type="date",
            cursor_value_json={"last_successful_date": "2026-01-01"},
            last_successful_run=run,
        )
        session.commit()

        stored = session.scalar(select(SyncCursor))

    assert stored is not None
    assert stored.id == cursor.id
    assert stored.last_successful_run_id == run_id


def test_artifact_audit_detects_checksum_mismatch(tmp_path) -> None:
    artifact_path = tmp_path / "preview.png"
    artifact_path.write_bytes(b"original")
    with in_memory_session() as session:
        run = start_ingestion_run(session, source_code="copernicus_sentinel2", mode="backfill", trigger="test")
        artifact = create_source_artifact(
            session,
            source_code="copernicus_sentinel2",
            storage_path=artifact_path,
            artifact_type="preview_rgb_png",
            role="derived_preview",
            run=run,
            mime_type="image/png",
        )
        session.commit()

        artifact_path.write_bytes(b"changed")
        issues = audit_source_artifacts(session)
        stored = session.get(SourceArtifact, artifact.id)

    assert stored is not None
    assert issues[0].issue == "size_mismatch"
    assert issues[1].issue == "sha256_mismatch"


def test_abandoned_runs_can_be_marked_interrupted() -> None:
    with in_memory_session() as session:
        run = start_ingestion_run(session, source_code="argos_node_flowmeter", mode="minute_capture", trigger="test")
        run.heartbeat_at_utc = datetime.now(UTC) - timedelta(hours=2)
        session.commit()

        stale = abandoned_runs(session, older_than=timedelta(hours=1))
        mark_run_interrupted(stale[0], reason="test reconciliation")
        session.commit()
        stored = session.get(IngestionRun, run.id)

    assert len(stale) == 1
    assert stored is not None
    assert stored.status == INTERRUPTED


def in_memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
