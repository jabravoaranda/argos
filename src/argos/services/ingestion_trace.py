from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from argos.config.settings import get_settings
from argos.models.ingestion import DataSource, IngestionItem, IngestionRun, SourceArtifact, SyncCursor

RUNNING = "running"
PENDING = "pending"
COMPLETED = "completed"
COMPLETED_WITH_WARNINGS = "completed_with_warnings"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"
TERMINAL_STATUSES = {COMPLETED, COMPLETED_WITH_WARNINGS, FAILED, CANCELLED, INTERRUPTED}
VALID_STATUSES = {PENDING, RUNNING, *TERMINAL_STATUSES}

SECRET_KEY_PATTERN = re.compile(r"(secret|token|password|passkey|api[_-]?key|authorization|cookie)", re.IGNORECASE)


DATA_SOURCE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"code": "ecowitt_lan", "name": "Ecowitt LAN", "source_type": "weather_station", "provider": "Ecowitt"},
    {"code": "ecowitt_cloud", "name": "Ecowitt Cloud", "source_type": "weather_station", "provider": "Ecowitt"},
    {"code": "aemet_api", "name": "AEMET OpenData API", "source_type": "weather_reference", "provider": "AEMET"},
    {"code": "aemet_csv", "name": "AEMET CSV import", "source_type": "weather_reference", "provider": "AEMET"},
    {"code": "copernicus_sentinel2", "name": "Copernicus Sentinel-2", "source_type": "satellite", "provider": "Copernicus CDSE"},
    {"code": "argos_node_flowmeter", "name": "argos-node flowmeter", "source_type": "controller", "provider": "argos-node"},
    {"code": "manual_field_event", "name": "Manual field event", "source_type": "manual", "provider": None},
)


@dataclass(frozen=True, slots=True)
class ArtifactAuditIssue:
    artifact_id: int
    storage_path: str
    issue: str


class IngestionTraceError(ValueError):
    """Raised when ingestion traceability metadata is invalid."""


def get_or_create_data_source(session: Session, code: str) -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.code == code))
    if source is not None:
        return source
    definition = next((item for item in DATA_SOURCE_DEFINITIONS if item["code"] == code), None)
    if definition is None:
        raise IngestionTraceError(f"Unknown data source code: {code}")
    source = DataSource(
        code=definition["code"],
        name=definition["name"],
        source_type=definition["source_type"],
        provider=definition["provider"],
        enabled=True,
        configuration_json={},
    )
    session.add(source)
    session.flush()
    return source


@contextmanager
def ingestion_run(
    session: Session,
    *,
    source_code: str,
    mode: str,
    trigger: str,
    requested_start_utc: datetime | None = None,
    requested_end_utc: datetime | None = None,
    processing_version: str | None = None,
    parameters_json: Mapping[str, Any] | None = None,
    code_version: str | None = None,
) -> Iterator[IngestionRun]:
    run = start_ingestion_run(
        session,
        source_code=source_code,
        mode=mode,
        trigger=trigger,
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        processing_version=processing_version,
        parameters_json=dict(parameters_json or {}),
        code_version=code_version,
    )
    try:
        yield run
    except Exception as exc:
        mark_run_failed(run, exc)
        session.commit()
        raise
    else:
        finalize_ingestion_run(run)
        session.commit()


def start_ingestion_run(
    session: Session,
    *,
    source_code: str,
    mode: str,
    trigger: str,
    requested_start_utc: datetime | None = None,
    requested_end_utc: datetime | None = None,
    processing_version: str | None = None,
    parameters_json: dict[str, Any] | None = None,
    code_version: str | None = None,
) -> IngestionRun:
    source = get_or_create_data_source(session, source_code)
    now = datetime.now(UTC)
    run = IngestionRun(
        source_id=source.id,
        run_uuid=str(uuid.uuid4()),
        mode=mode,
        status=RUNNING,
        requested_start_utc=_as_utc_or_none(requested_start_utc),
        requested_end_utc=_as_utc_or_none(requested_end_utc),
        started_at_utc=now,
        heartbeat_at_utc=now,
        trigger=trigger,
        code_version=code_version,
        processing_version=processing_version,
        parameters_json=redact_secret_values(parameters_json or {}),
    )
    session.add(run)
    session.flush()
    return run


def finalize_ingestion_run(run: IngestionRun) -> None:
    now = datetime.now(UTC)
    run.finished_at_utc = now
    run.heartbeat_at_utc = now
    run.status = COMPLETED_WITH_WARNINGS if run.warning_count or run.failed_count else COMPLETED


def mark_run_failed(run: IngestionRun, exc: BaseException) -> None:
    now = datetime.now(UTC)
    run.status = FAILED
    run.finished_at_utc = now
    run.heartbeat_at_utc = now
    run.failed_count += 1
    run.error_summary = f"{type(exc).__name__}: {exc}"


def mark_run_interrupted(run: IngestionRun, *, reason: str) -> None:
    run.status = INTERRUPTED
    run.finished_at_utc = datetime.now(UTC)
    run.error_summary = reason


def heartbeat(run: IngestionRun) -> None:
    run.heartbeat_at_utc = datetime.now(UTC)


def create_ingestion_item(
    session: Session,
    *,
    run: IngestionRun,
    item_key: str,
    item_type: str,
    status: str = RUNNING,
    source_external_id: str | None = None,
    requested_start_utc: datetime | None = None,
    requested_end_utc: datetime | None = None,
    metadata_json: Mapping[str, Any] | None = None,
) -> IngestionItem:
    item = IngestionItem(
        run_id=run.id,
        item_key=item_key,
        item_type=item_type,
        status=status,
        source_external_id=source_external_id,
        requested_start_utc=_as_utc_or_none(requested_start_utc),
        requested_end_utc=_as_utc_or_none(requested_end_utc),
        started_at_utc=datetime.now(UTC),
        metadata_json=redact_secret_values(metadata_json or {}),
    )
    session.add(item)
    session.flush()
    return item


def finish_ingestion_item(item: IngestionItem, *, status: str = COMPLETED) -> None:
    item.status = status
    item.finished_at_utc = datetime.now(UTC)


def fail_ingestion_item(item: IngestionItem, exc: BaseException) -> None:
    item.status = FAILED
    item.failed_count += 1
    item.error_type = type(exc).__name__
    item.error_message = str(exc)
    item.finished_at_utc = datetime.now(UTC)


def update_sync_cursor(
    session: Session,
    *,
    source_code: str,
    scope: str,
    scope_key: str,
    cursor_type: str,
    cursor_value_json: Mapping[str, Any],
    last_successful_run: IngestionRun,
) -> SyncCursor:
    if last_successful_run.status not in {COMPLETED, COMPLETED_WITH_WARNINGS}:
        raise IngestionTraceError("Sync cursor can only advance after a successful run.")
    source = get_or_create_data_source(session, source_code)
    cursor = session.scalar(
        select(SyncCursor).where(
            SyncCursor.source_id == source.id,
            SyncCursor.scope == scope,
            SyncCursor.scope_key == scope_key,
        )
    )
    if cursor is None:
        cursor = SyncCursor(
            source_id=source.id,
            scope=scope,
            scope_key=scope_key,
            cursor_type=cursor_type,
            cursor_value_json=dict(cursor_value_json),
        )
        session.add(cursor)
    cursor.cursor_type = cursor_type
    cursor.cursor_value_json = dict(cursor_value_json)
    cursor.last_successful_run_id = last_successful_run.id
    cursor.updated_at_utc = datetime.now(UTC)
    session.flush()
    return cursor


def create_source_artifact(
    session: Session,
    *,
    source_code: str,
    storage_path: Path,
    artifact_type: str,
    role: str,
    run: IngestionRun | None = None,
    ingestion_item: IngestionItem | None = None,
    mime_type: str | None = None,
    immutable: bool = True,
    regenerable: bool = False,
    original_filename: str | None = None,
    provider_external_id: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
) -> SourceArtifact:
    if not storage_path.exists():
        raise IngestionTraceError(f"Artifact path does not exist: {storage_path}")
    source = get_or_create_data_source(session, source_code)
    artifact = SourceArtifact(
        source_id=source.id,
        run_id=run.id if run else None,
        ingestion_item_id=ingestion_item.id if ingestion_item else None,
        artifact_type=artifact_type,
        role=role,
        storage_backend="local_filesystem",
        storage_path=str(storage_path),
        mime_type=mime_type,
        size_bytes=storage_path.stat().st_size,
        sha256=sha256_file(storage_path),
        immutable=immutable,
        regenerable=regenerable,
        original_filename=original_filename or storage_path.name,
        provider_external_id=provider_external_id,
        verified_at_utc=datetime.now(UTC),
        metadata_json=redact_secret_values(metadata_json or {}),
    )
    session.add(artifact)
    session.flush()
    return artifact


def audit_source_artifacts(session: Session) -> list[ArtifactAuditIssue]:
    issues: list[ArtifactAuditIssue] = []
    for artifact in session.scalars(select(SourceArtifact).order_by(SourceArtifact.id)).all():
        path = _resolve_artifact_path(artifact.storage_path)
        if not path.exists():
            issues.append(ArtifactAuditIssue(artifact.id, artifact.storage_path, "missing_file"))
            continue
        if artifact.size_bytes is not None and artifact.size_bytes != path.stat().st_size:
            issues.append(ArtifactAuditIssue(artifact.id, artifact.storage_path, "size_mismatch"))
        if artifact.sha256 and artifact.sha256 != sha256_file(path):
            issues.append(ArtifactAuditIssue(artifact.id, artifact.storage_path, "sha256_mismatch"))
    return issues


def abandoned_runs(session: Session, *, older_than: timedelta, now: datetime | None = None) -> list[IngestionRun]:
    cutoff = _as_utc(now or datetime.now(UTC)) - older_than
    return list(
        session.scalars(
            select(IngestionRun)
            .where(IngestionRun.status == RUNNING, IngestionRun.heartbeat_at_utc < cutoff)
            .order_by(IngestionRun.heartbeat_at_utc, IngestionRun.id)
        ).all()
    )


def latest_runs(session: Session, *, source_code: str | None = None, status: str | None = None, limit: int = 20) -> list[IngestionRun]:
    statement = select(IngestionRun).join(DataSource).order_by(desc(IngestionRun.started_at_utc), desc(IngestionRun.id)).limit(limit)
    if source_code:
        statement = statement.where(DataSource.code == source_code)
    if status:
        statement = statement.where(IngestionRun.status == status)
    return list(session.scalars(statement).all())


def validate_cursor(cursor: SyncCursor) -> None:
    if not isinstance(cursor.cursor_value_json, dict):
        raise IngestionTraceError(f"Cursor {cursor.id} has invalid JSON value.")


def redact_secret_values(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if SECRET_KEY_PATTERN.search(str(key)):
            redacted[str(key)] = "<redacted>"
        elif isinstance(item, Mapping):
            redacted[str(key)] = redact_secret_values(item)
        else:
            redacted[str(key)] = item
    return redacted


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_artifact_path(storage_path: str) -> Path:
    path = Path(storage_path)
    if path.is_absolute() or path.exists():
        return path
    return Path(get_settings().argos_data_dir) / storage_path


def _as_utc_or_none(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
