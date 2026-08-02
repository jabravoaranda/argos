from __future__ import annotations

import json
import mimetypes
import os
import shutil
import csv
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from argos.config.settings import Settings, get_settings
from argos.models.ingestion import SourceArtifact
from argos.models.ecowitt import WeatherObservation
from argos.models.satellite import SatelliteAsset, SatelliteMetric, SatelliteObservation, SatelliteZone
from argos.services.ingestion_trace import (
    create_source_artifact,
    finalize_ingestion_run,
    mark_run_failed,
    start_ingestion_run,
)

LAYOUT_CATEGORIES = ("raw", "staging", "processed", "exports", "cache", "legacy", "quarantine")
MANIFEST_SCHEMA_VERSION = "argos-data-inventory-v1"


@dataclass(frozen=True, slots=True)
class DataPaths:
    data: Path
    raw: Path
    staging: Path
    processed: Path
    exports: Path
    cache: Path
    legacy: Path
    quarantine: Path


@dataclass(frozen=True, slots=True)
class FileInventoryRecord:
    relative_path: str
    size_bytes: int
    modified_at_utc: str
    extension: str
    mime_type: str | None
    sha256: str
    probable_source: str
    known_producer: str | None
    known_consumer: str | None
    sql_reference: str | None
    proposed_classification: str
    regenerable: str
    immutable: bool
    proposed_decision: str


@dataclass(frozen=True, slots=True)
class MigrationPlanItem:
    source_path: str
    destination_path: str
    category: str
    sql_change: str | None
    checksum_sha256: str
    conflict: str | None = None


@dataclass(frozen=True, slots=True)
class RetentionCandidate:
    relative_path: str
    category: str
    age_days: int
    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class StagingAuditIssue:
    relative_path: str
    issue: str
    details: str


@dataclass(frozen=True, slots=True)
class OrphanSatelliteAssetRecord:
    relative_path: str
    filename: str
    size_bytes: int
    sha256: str
    modified_at_utc: str
    name_pattern: str
    probable_aoi_slug: str | None
    probable_acquisition_time: str | None
    probable_scene_id: str | None
    probable_asset_type: str | None
    probable_processing_version: str | None
    satellite_observation_ids: list[int]
    satellite_metric_count: int
    satellite_asset_ids: list[int]
    source_artifact_ids: list[int]
    duplicate_paths: list[str]
    canonical_duplicate_path: str | None
    regenerable: str
    scientific_or_operational_value: str
    proposed_classification: str
    proposed_destination: str
    ambiguity: str | None


def data_paths(settings: Settings | None = None) -> DataPaths:
    settings = settings or get_settings()
    root = Path(settings.argos_data_dir).expanduser().resolve()
    return DataPaths(
        data=root,
        raw=_configured_path(settings.argos_raw_dir, root / "raw"),
        staging=_configured_path(settings.argos_staging_dir, root / "staging"),
        processed=_configured_path(settings.argos_processed_dir, root / "processed"),
        exports=_configured_path(settings.argos_exports_dir, root / "exports"),
        cache=_configured_path(settings.argos_cache_dir, root / "cache"),
        legacy=_configured_path(settings.argos_legacy_dir, root / "legacy"),
        quarantine=_configured_path(settings.argos_quarantine_dir, root / "quarantine"),
    )


def satellite_asset_root(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    if settings.argos_satellite_asset_dir:
        return Path(settings.argos_satellite_asset_dir).expanduser().resolve()
    return data_paths(settings).processed / "satellite"


def storage_path_for_sql(path: Path, *, settings: Settings | None = None) -> str:
    paths = data_paths(settings)
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(paths.data).as_posix()
    except ValueError:
        return str(resolved)


def resolve_storage_path(storage_path: str, *, settings: Settings | None = None) -> Path:
    raw = Path(storage_path)
    if raw.is_absolute():
        return raw
    paths = data_paths(settings)
    data_relative = paths.data / raw
    if data_relative.exists():
        return data_relative
    cwd_relative = Path.cwd() / raw
    return cwd_relative


def safe_data_path(relative_path: str | Path, *, root: Path) -> Path:
    candidate = (root / relative_path).resolve()
    root = root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes data root: {relative_path}") from exc
    return candidate


def build_data_inventory(*, session: Session | None = None, settings: Settings | None = None) -> list[FileInventoryRecord]:
    paths = data_paths(settings)
    asset_refs = _satellite_asset_refs(session) if session is not None else {}
    records = []
    if not paths.data.exists():
        return records
    for path in sorted(item for item in paths.data.rglob("*") if item.is_file()):
        relative = path.relative_to(paths.data).as_posix()
        checksum = sha256_file(path)
        classification = classify_relative_path(relative)
        sql_reference = asset_refs.get(_normalize_ref(path)) or asset_refs.get(relative)
        records.append(
            FileInventoryRecord(
                relative_path=relative,
                size_bytes=path.stat().st_size,
                modified_at_utc=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                extension=path.suffix.lower(),
                mime_type=mimetypes.guess_type(path.name)[0],
                sha256=checksum,
                probable_source=probable_source(relative),
                known_producer=known_producer(relative),
                known_consumer=known_consumer(relative),
                sql_reference=sql_reference,
                proposed_classification=classification,
                regenerable=regenerable_condition(relative, sql_reference=sql_reference),
                immutable=classification in {"raw", "legacy", "quarantine"},
                proposed_decision=proposed_decision(relative, classification=classification, sql_reference=sql_reference),
            )
        )
    return records


def write_inventory_manifest(records: list[FileInventoryRecord], *, manifest_dir: Path) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = manifest_dir / f"data-inventory-{timestamp}.json"
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "records": [asdict(record) for record in records],
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def write_inventory_markdown(records: list[FileInventoryRecord], *, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for record in records:
        counts[record.proposed_classification] = counts.get(record.proposed_classification, 0) + 1
    lines = [
        "# ARGOS Data File Inventory",
        "",
        f"Date: {datetime.now(UTC).date().isoformat()}",
        "",
        "No files were moved while generating this inventory.",
        "",
        "## Summary",
        "",
        "| Classification | Files |",
        "|---|---:|",
    ]
    lines.extend(f"| `{key}` | {counts[key]} |" for key in sorted(counts))
    lines.extend(
        [
            "",
            "## Files",
            "",
            "| Path | Size | MIME | SHA-256 | SQL | Classification | Regenerable | Decision |",
            "|---|---:|---|---|---|---|---|---|",
        ]
    )
    for record in records:
        lines.append(
            "| "
            f"`{record.relative_path}` | {record.size_bytes} | {record.mime_type or '-'} | "
            f"`{record.sha256}` | {record.sql_reference or '-'} | "
            f"`{record.proposed_classification}` | {record.regenerable} | {record.proposed_decision} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def reconcile_legacy_weather(
    *,
    records: list[FileInventoryRecord],
    session: Session,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    observed_timestamps = _weather_observation_timestamps(session)
    checksum_counts: dict[str, int] = {}
    for record in records:
        if record.relative_path.startswith("weather/"):
            checksum_counts[record.sha256] = checksum_counts.get(record.sha256, 0) + 1
    results = []
    for record in records:
        if not record.relative_path.startswith("weather/"):
            continue
        schema = "json" if record.extension == ".json" else "csv" if record.extension == ".csv" else "unknown"
        file_path = data_paths(settings).data / record.relative_path
        timestamps = _legacy_weather_timestamps(file_path, schema=schema)
        matched = sum(1 for value in timestamps if value in observed_timestamps)
        status = _weather_sql_status(total=len(timestamps), matched=matched)
        results.append(
            {
                "relative_path": record.relative_path,
                "schema": schema,
                "temporal_range": _infer_temporal_range(record.relative_path),
                "station_or_gateway": "unknown",
                "sql_representation": status,
                "unique_records": max(0, len(timestamps) - matched),
                "matched_records": matched,
                "discrepancies": "timestamps missing from SQL" if matched < len(timestamps) else "none_detected",
                "duplicate_status": "duplicate_checksum" if checksum_counts[record.sha256] > 1 else "checksum_unique",
                "classification": "legacy",
                "decision": _weather_reconciliation_decision(status),
            }
        )
    return results


def write_weather_reconciliation(results: list[dict[str, Any]], *, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Legacy Weather Reconciliation",
        "",
        f"Date: {datetime.now(UTC).date().isoformat()}",
        "",
        "No `data/weather` file was moved or deleted. Current code does not consume these files directly.",
        "",
        "| File | Schema | Range | Gateway/Station | SQL representation | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| `{result['relative_path']}` | {result['schema']} | {result['temporal_range']} | "
            f"{result['station_or_gateway']} | {result['sql_representation']} | {result['decision']} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_migration_plan(*, session: Session, settings: Settings | None = None) -> list[MigrationPlanItem]:
    paths = data_paths(settings)
    records = build_data_inventory(session=session, settings=settings)
    plan = []
    for record in records:
        destination_relative = destination_for_record(record)
        if destination_relative is None:
            continue
        destination = safe_data_path(destination_relative, root=paths.data)
        conflict = None
        if destination.exists() and sha256_file(destination) != record.sha256:
            conflict = "destination_exists_with_different_checksum"
        sql_change = None
        if record.sql_reference and record.relative_path != destination_relative:
            sql_change = f"satellite_assets.storage_path={destination_relative}"
        plan.append(
            MigrationPlanItem(
                source_path=record.relative_path,
                destination_path=destination_relative,
                category=record.proposed_classification,
                sql_change=sql_change,
                checksum_sha256=record.sha256,
                conflict=conflict,
            )
        )
    return plan


def apply_migration_plan(*, session: Session, plan: list[MigrationPlanItem], settings: Settings | None = None) -> None:
    paths = data_paths(settings)
    run = start_ingestion_run(
        session,
        source_code="manual_field_event",
        mode="data_layout_migration",
        trigger="admin_cli",
        parameters_json={"items": len(plan)},
    )
    session.commit()
    try:
        for item in plan:
            if item.conflict:
                run.rejected_count += 1
                continue
            source = safe_data_path(item.source_path, root=paths.data)
            destination = safe_data_path(item.destination_path, root=paths.data)
            if not source.exists():
                run.failed_count += 1
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if sha256_file(destination) == item.checksum_sha256:
                    _update_satellite_asset_path(session, old_path=item.source_path, new_path=item.destination_path)
                    run.unchanged_count += 1
                    continue
                run.rejected_count += 1
                continue
            _move_verified(source, destination, expected_sha256=item.checksum_sha256)
            _update_satellite_asset_path(session, old_path=item.source_path, new_path=item.destination_path)
            _register_known_artifact(session, item=item, destination=destination, run=run, settings=settings)
            run.inserted_count += 1
        finalize_ingestion_run(run)
        session.commit()
    except Exception as exc:
        session.rollback()
        run = session.merge(run)
        mark_run_failed(run, exc)
        session.commit()
        raise


def retention_report(*, records: list[FileInventoryRecord], now: datetime | None = None) -> list[RetentionCandidate]:
    now = now or datetime.now(UTC)
    candidates = []
    for record in records:
        modified = datetime.fromisoformat(record.modified_at_utc)
        age_days = max(0, (now - modified).days)
        eligible = False
        reason = "automatic deletion disabled in this phase"
        if record.proposed_classification in {"staging", "exports", "cache"} and age_days >= 30:
            eligible = True
            reason = "would be eligible after manual policy activation"
        if record.proposed_classification in {"raw", "legacy", "quarantine"}:
            reason = "protected category"
        candidates.append(
            RetentionCandidate(
                relative_path=record.relative_path,
                category=record.proposed_classification,
                age_days=age_days,
                eligible=eligible,
                reason=reason,
            )
        )
    return candidates


def audit_staging(*, session: Session, settings: Settings | None = None, older_than: timedelta = timedelta(hours=24)) -> list[StagingAuditIssue]:
    paths = data_paths(settings)
    issues = []
    if not paths.staging.exists():
        return issues
    artifact_paths = {artifact.storage_path for artifact in session.scalars(select(SourceArtifact)).all()}
    cutoff = datetime.now(UTC) - older_than
    for path in sorted(item for item in paths.staging.rglob("*") if item.is_file()):
        relative = path.relative_to(paths.data).as_posix()
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if relative not in artifact_paths:
            issues.append(StagingAuditIssue(relative, "unregistered_file", "no source_artifacts row references this file"))
        if modified < cutoff:
            issues.append(StagingAuditIssue(relative, "old_temporary_file", f"modified_at_utc={modified.isoformat()}"))
        if path.stat().st_size == 0:
            issues.append(StagingAuditIssue(relative, "partial_or_empty_file", "size is 0 bytes"))
    return issues


def reconcile_orphan_satellite_assets(
    *,
    session: Session,
    settings: Settings | None = None,
) -> list[OrphanSatelliteAssetRecord]:
    paths = data_paths(settings)
    sql_asset_paths = _existing_satellite_asset_paths(session, settings=settings)
    checksum_paths = _png_paths_by_checksum(paths.data)
    records = []
    for path in sorted(paths.data.rglob("*.png")):
        resolved = path.resolve()
        if str(resolved) in sql_asset_paths:
            continue
        relative = path.relative_to(paths.data).as_posix()
        checksum = sha256_file(path)
        parsed = _parse_satellite_preview_path(relative)
        observation_rows = _matching_satellite_observations(session, parsed)
        asset_ids = _matching_satellite_asset_ids(session, observation_rows, parsed.get("asset_type"))
        source_artifact_ids = _matching_source_artifact_ids(session, relative_path=relative, checksum=checksum)
        duplicate_paths = sorted(item for item in checksum_paths.get(checksum, []) if item != relative)
        classification, destination, ambiguity = _classify_orphan_satellite_asset(
            parsed=parsed,
            observation_rows=observation_rows,
            asset_ids=asset_ids,
            source_artifact_ids=source_artifact_ids,
            duplicate_paths=duplicate_paths,
        )
        records.append(
            OrphanSatelliteAssetRecord(
                relative_path=relative,
                filename=path.name,
                size_bytes=path.stat().st_size,
                sha256=checksum,
                modified_at_utc=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                name_pattern=parsed["pattern"],
                probable_aoi_slug=parsed.get("aoi_slug"),
                probable_acquisition_time=parsed.get("acquisition_time"),
                probable_scene_id=parsed.get("scene_id"),
                probable_asset_type=parsed.get("asset_type"),
                probable_processing_version=parsed.get("processing_version"),
                satellite_observation_ids=[row["id"] for row in observation_rows],
                satellite_metric_count=sum(row["metric_count"] for row in observation_rows),
                satellite_asset_ids=asset_ids,
                source_artifact_ids=source_artifact_ids,
                duplicate_paths=duplicate_paths,
                canonical_duplicate_path=min([relative, *duplicate_paths]) if duplicate_paths else None,
                regenerable="conditional: requires Copernicus availability, AOI geometry and processing version",
                scientific_or_operational_value=(
                    "visual preview for inspection; SQL metrics remain authoritative for analysis"
                ),
                proposed_classification=classification,
                proposed_destination=destination,
                ambiguity=ambiguity,
            )
        )
    return records


def write_orphan_satellite_reconciliation(
    records: list[OrphanSatelliteAssetRecord],
    *,
    markdown_path: Path,
    manifest_dir: Path,
) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = manifest_dir / f"orphan-satellite-assets-{timestamp}.json"
    payload = {
        "schema_version": "argos-orphan-satellite-assets-v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "summary": orphan_satellite_summary(records),
        "records": [asdict(record) for record in records],
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Orphan Satellite Assets Reconciliation",
        "",
        f"Date: {datetime.now(UTC).date().isoformat()}",
        "",
        f"JSON manifest: `{manifest_path.as_posix()}`.",
        "",
        "No orphan PNG was deleted. Recoverable rows are applied only with `--apply-recoverable`.",
        "",
        "## Summary",
        "",
        "| Classification | Files |",
        "|---|---:|",
    ]
    summary = orphan_satellite_summary(records)
    for key in ("recoverable_asset", "duplicate_file", "legacy_preview", "regenerable_cache", "unknown", "corrupt", "conflicting"):
        lines.append(f"| `{key}` | {summary.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Files",
            "",
            "| Path | Scene | AOI | Asset type | Observations | Duplicates | Classification | Ambiguity |",
            "|---|---|---|---|---|---:|---|---|",
        ]
    )
    for record in records:
        lines.append(
            f"| `{record.relative_path}` | {record.probable_scene_id or '-'} | "
            f"{record.probable_aoi_slug or '-'} | {record.probable_asset_type or '-'} | "
            f"{','.join(str(item) for item in record.satellite_observation_ids) or '-'} | "
            f"{len(record.duplicate_paths)} | `{record.proposed_classification}` | {record.ambiguity or '-'} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


def orphan_satellite_summary(records: list[OrphanSatelliteAssetRecord]) -> dict[str, int]:
    summary = {key: 0 for key in ("recoverable_asset", "duplicate_file", "legacy_preview", "regenerable_cache", "unknown", "corrupt", "conflicting")}
    for record in records:
        summary[record.proposed_classification] = summary.get(record.proposed_classification, 0) + 1
    summary["total"] = len(records)
    summary["sql_rows_creatable"] = sum(1 for record in records if record.proposed_classification == "recoverable_asset")
    summary["ambiguous"] = sum(1 for record in records if record.ambiguity)
    return summary


def apply_recoverable_orphan_satellite_assets(
    *,
    session: Session,
    records: list[OrphanSatelliteAssetRecord],
    settings: Settings | None = None,
) -> int:
    created = 0
    for record in records:
        if record.proposed_classification != "recoverable_asset":
            continue
        if len(record.satellite_observation_ids) != 1 or record.probable_asset_type is None:
            continue
        exists = session.scalar(
            select(SatelliteAsset).where(
                SatelliteAsset.observation_id == record.satellite_observation_ids[0],
                SatelliteAsset.asset_type == record.probable_asset_type,
            )
        )
        if exists is not None:
            continue
        path = data_paths(settings).data / record.relative_path
        artifact = create_source_artifact(
            session,
            source_code="copernicus_sentinel2",
            storage_path=path,
            artifact_type=record.probable_asset_type,
            role="derived_preview",
            mime_type="image/png",
            immutable=False,
            regenerable=True,
            original_filename=record.filename,
            provider_external_id=record.probable_scene_id,
            metadata_json={"origin": "legacy_reconciliation", "historical_path": record.relative_path},
        )
        artifact.storage_path = record.relative_path
        session.add(
            SatelliteAsset(
                observation_id=record.satellite_observation_ids[0],
                asset_type=record.probable_asset_type,
                storage_path=record.relative_path,
                mime_type="image/png",
                checksum_sha256=record.sha256,
                size_bytes=record.size_bytes,
                source_artifact_id=artifact.id,
            )
        )
        created += 1
    session.commit()
    return created


def classify_relative_path(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if parts and parts[0] in LAYOUT_CATEGORIES:
        return parts[0]
    if relative_path.startswith("aemet/"):
        return "raw"
    if relative_path.startswith("satellite/") and relative_path.lower().endswith(".png"):
        return "processed"
    if relative_path.startswith("weather/"):
        return "legacy"
    return "legacy"


def destination_for_record(record: FileInventoryRecord) -> str | None:
    path = Path(record.relative_path)
    parts = path.parts
    if parts and parts[0] in LAYOUT_CATEGORIES:
        return None
    if record.relative_path.startswith("aemet/"):
        return Path("raw", record.relative_path).as_posix()
    if record.relative_path.startswith("satellite/"):
        return Path("processed", record.relative_path).as_posix()
    if record.relative_path.startswith("weather/"):
        return Path("legacy", record.relative_path).as_posix()
    return Path("legacy", record.relative_path).as_posix()


def probable_source(relative_path: str) -> str:
    if relative_path.startswith("aemet/") or relative_path.startswith("raw/aemet/"):
        return "aemet_csv"
    if "satellite" in Path(relative_path).parts:
        return "copernicus_sentinel2"
    if "weather" in Path(relative_path).parts:
        return "legacy_weather"
    return "unknown"


def known_producer(relative_path: str) -> str | None:
    if "satellite" in Path(relative_path).parts:
        return "SatelliteIngestionService._store_previews"
    if relative_path.startswith("aemet/"):
        return "manual AEMET export"
    return None


def known_consumer(relative_path: str) -> str | None:
    if "satellite" in Path(relative_path).parts:
        return "/api/v1/satellite/assets/{asset_id}"
    if relative_path.startswith("aemet/"):
        return "argos aemet import-csv"
    return None


def regenerable_condition(relative_path: str, *, sql_reference: str | None) -> str:
    if "satellite" in Path(relative_path).parts:
        return "conditional: requires provider availability, AOI geometry and processing version"
    if relative_path.startswith("aemet/") or relative_path.startswith("raw/aemet/"):
        return "possibly: public provider data may change or become unavailable"
    if relative_path.startswith("weather/"):
        return "unknown: legacy producer not fully identified"
    return "unknown"


def proposed_decision(relative_path: str, *, classification: str, sql_reference: str | None) -> str:
    if classification == "processed" and sql_reference:
        return "migrate after verifying SQL reference and checksum"
    if classification == "processed":
        return "keep as orphan candidate until reviewed"
    if classification == "raw":
        return "migrate to raw with immutable artifact record"
    if classification == "legacy":
        return "preserve in legacy until reconciliation is complete"
    return "review manually"


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _configured_path(value: str | None, default: Path) -> Path:
    return Path(value).expanduser().resolve() if value else default.resolve()


def _satellite_asset_refs(session: Session) -> dict[str, str]:
    refs = {}
    statement = select(SatelliteAsset.id, SatelliteAsset.storage_path, SatelliteAsset.checksum_sha256)
    for asset_id, storage_path, checksum in session.execute(statement):
        ref = f"satellite_assets:{asset_id}"
        refs[str(storage_path)] = ref
        refs[_normalize_ref(Path(str(storage_path)))] = ref
        refs[str(checksum)] = ref
    return refs


def _normalize_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(data_paths().data).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _infer_temporal_range(relative_path: str) -> str:
    digits = "".join(char if char.isdigit() else " " for char in relative_path).split()
    years = [item for item in digits if len(item) == 4 and item.startswith("20")]
    return ", ".join(sorted(set(years))) if years else "unknown"


def _weather_observation_timestamps(session: Session) -> set[str]:
    values = set()
    for observed_at in session.scalars(select(WeatherObservation.observed_at_utc)).all():
        if observed_at is None:
            continue
        values.add(_timestamp_key(observed_at))
    return values


def _legacy_weather_timestamps(path: Path, *, schema: str) -> list[str]:
    if schema == "csv":
        return _legacy_weather_csv_timestamps(path)
    if schema == "json":
        return _legacy_weather_json_timestamps(path)
    return []


def _legacy_weather_csv_timestamps(path: Path) -> list[str]:
    timestamps = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                value = row.get("fecha_hora_local") or row.get("observed_at_utc") or row.get("timestamp")
                if value:
                    timestamps.append(_timestamp_key(datetime.fromisoformat(value)))
    except (OSError, ValueError, csv.Error):
        return []
    return timestamps


def _legacy_weather_json_timestamps(path: Path) -> list[str]:
    try:
        stem = path.stem
        parsed = datetime.strptime(stem[:20], "%Y%m%dT%H%M%S%z")
    except ValueError:
        return []
    return [_timestamp_key(parsed)]


def _timestamp_key(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def _weather_sql_status(*, total: int, matched: int) -> str:
    if total == 0:
        return "unknown"
    if matched == total:
        return "already_represented_in_sql"
    if matched == 0:
        return "unknown"
    return "partially_represented"


def _weather_reconciliation_decision(status: str) -> str:
    if status == "already_represented_in_sql":
        return "ya representado en SQL; posible eliminacion futura tras revision"
    if status == "partially_represented":
        return "parcialmente representado; preservar en legacy"
    return "preservacion obligatoria hasta reconciliacion manual"


def _move_verified(source: Path, destination: Path, *, expected_sha256: str) -> None:
    if sha256_file(source) != expected_sha256:
        raise ValueError(f"Source checksum changed before move: {source}")
    same_drive = os.path.splitdrive(source)[0].lower() == os.path.splitdrive(destination)[0].lower()
    if same_drive:
        source.replace(destination)
    else:
        shutil.copy2(source, destination)
        if sha256_file(destination) != expected_sha256:
            destination.unlink(missing_ok=True)
            raise ValueError(f"Destination checksum mismatch after copy: {destination}")
        source.unlink()
    if sha256_file(destination) != expected_sha256:
        raise ValueError(f"Destination checksum mismatch after move: {destination}")


def _update_satellite_asset_path(session: Session, *, old_path: str, new_path: str) -> None:
    candidates = {old_path, str(Path.cwd() / "data" / old_path), str(data_paths().data / old_path)}
    for asset in session.scalars(select(SatelliteAsset).where(SatelliteAsset.storage_path.in_(candidates))).all():
        asset.storage_path = new_path


def _register_known_artifact(
    session: Session,
    *,
    item: MigrationPlanItem,
    destination: Path,
    run: Any,
    settings: Settings | None,
) -> None:
    if item.category not in {"raw", "processed"}:
        return
    source_code = "copernicus_sentinel2" if "satellite" in Path(item.destination_path).parts else "aemet_csv"
    artifact = create_source_artifact(
        session,
        source_code=source_code,
        storage_path=destination,
        artifact_type=Path(item.destination_path).suffix.lower().lstrip(".") or "file",
        role="raw" if item.category == "raw" else "derived_preview",
        run=None,
        mime_type=mimetypes.guess_type(destination.name)[0],
        immutable=item.category == "raw",
        regenerable=item.category != "raw",
        original_filename=Path(item.source_path).name,
        metadata_json={
            "layout_migration": True,
            "legacy_incorporated": True,
            "source_path": item.source_path,
            "administrative_run_uuid": run.run_uuid,
            "historical_ingestion_run": "not_reconstructed",
        },
    )
    artifact.storage_path = storage_path_for_sql(destination, settings=settings)
    if "satellite" in Path(item.destination_path).parts:
        observation = session.scalar(
            select(SatelliteObservation)
            .join(SatelliteAsset)
            .where(SatelliteAsset.storage_path == item.destination_path)
            .limit(1)
        )
        if observation is not None:
            for asset in observation.assets:
                if asset.storage_path == item.destination_path:
                    asset.source_artifact_id = artifact.id


def _existing_satellite_asset_paths(session: Session, *, settings: Settings | None) -> set[str]:
    root = data_paths(settings).data
    paths = set()
    for storage_path in session.scalars(select(SatelliteAsset.storage_path)).all():
        raw = Path(storage_path)
        candidates = [raw]
        if not raw.is_absolute():
            candidates.extend([root / raw, Path.cwd() / raw])
        for candidate in candidates:
            try:
                paths.add(str(candidate.resolve()))
            except OSError:
                paths.add(str(candidate))
    return paths


def _png_paths_by_checksum(root: Path) -> dict[str, list[str]]:
    by_checksum: dict[str, list[str]] = {}
    if not root.exists():
        return by_checksum
    for path in sorted(root.rglob("*.png")):
        checksum = sha256_file(path)
        by_checksum.setdefault(checksum, []).append(path.relative_to(root).as_posix())
    return by_checksum


def _parse_satellite_preview_path(relative_path: str) -> dict[str, str | None]:
    parts = Path(relative_path).parts
    result: dict[str, str | None] = {
        "pattern": "unknown",
        "aoi_slug": None,
        "scene_id": None,
        "asset_type": None,
        "acquisition_time": None,
        "processing_version": None,
    }
    if not relative_path.lower().endswith(".png"):
        return result | {"pattern": "non_png"}
    filename = Path(relative_path).name
    if filename.endswith("_preview_rgb_png.png"):
        result["asset_type"] = "preview_rgb_png"
    elif filename.endswith("_preview_ndvi_png.png"):
        result["asset_type"] = "preview_ndvi_png"
    if len(filename) >= 16:
        try:
            result["acquisition_time"] = datetime.strptime(filename[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat()
        except ValueError:
            pass
    for part in parts:
        if part.startswith("S2") and part.endswith(".SAFE"):
            result["scene_id"] = part
            pieces = part.split("_")
            result["processing_version"] = next((piece for piece in pieces if piece.startswith("N")), None)
            break
    if len(parts) >= 4 and parts[0] in {"satellite", "processed"}:
        if parts[0] == "satellite" and parts[2] == "sentinel-2-l2a":
            result["aoi_slug"] = parts[1]
            result["pattern"] = "aoi_scoped_preview"
        elif parts[0] == "satellite" and parts[1] == "sentinel-2-l2a":
            result["pattern"] = "legacy_unscoped_preview"
        elif parts[0] == "processed" and len(parts) >= 5 and parts[1] == "satellite":
            result["aoi_slug"] = parts[2]
            result["pattern"] = "processed_aoi_scoped_preview"
    return result


def _matching_satellite_observations(session: Session, parsed: dict[str, str | None]) -> list[dict[str, Any]]:
    scene_id = parsed.get("scene_id")
    if not scene_id:
        return []
    statement = (
        select(
            SatelliteObservation.id,
            SatelliteObservation.external_item_id,
            SatelliteObservation.processing_version,
            SatelliteObservation.zone_id,
            SatelliteObservation.acquisition_time,
        )
        .where(SatelliteObservation.external_item_id == scene_id)
        .order_by(SatelliteObservation.id)
    )
    rows = []
    for observation_id, external_item_id, processing_version, zone_id, acquisition_time in session.execute(statement):
        if parsed.get("aoi_slug"):
            zone_slug = session.scalar(select(SatelliteZone.slug).where(SatelliteZone.id == zone_id))
            if zone_slug != parsed["aoi_slug"]:
                continue
        metric_count = int(
            session.scalar(
                select(func.count()).select_from(SatelliteMetric).where(SatelliteMetric.observation_id == observation_id)
            )
            or 0
        )
        rows.append(
            {
                "id": observation_id,
                "external_item_id": external_item_id,
                "processing_version": processing_version,
                "zone_id": zone_id,
                "acquisition_time": acquisition_time,
                "metric_count": metric_count,
            }
        )
    return rows


def _matching_satellite_asset_ids(
    session: Session,
    observation_rows: list[dict[str, Any]],
    asset_type: str | None,
) -> list[int]:
    if not observation_rows or asset_type is None:
        return []
    observation_ids = [row["id"] for row in observation_rows]
    return list(
        session.scalars(
            select(SatelliteAsset.id).where(
                SatelliteAsset.observation_id.in_(observation_ids),
                SatelliteAsset.asset_type == asset_type,
            )
        ).all()
    )


def _matching_source_artifact_ids(session: Session, *, relative_path: str, checksum: str) -> list[int]:
    return list(
        session.scalars(
            select(SourceArtifact.id).where(
                (SourceArtifact.storage_path == relative_path) | (SourceArtifact.sha256 == checksum)
            )
        ).all()
    )


def _classify_orphan_satellite_asset(
    *,
    parsed: dict[str, str | None],
    observation_rows: list[dict[str, Any]],
    asset_ids: list[int],
    source_artifact_ids: list[int],
    duplicate_paths: list[str],
) -> tuple[str, str, str | None]:
    if parsed["pattern"] == "unknown" or parsed.get("asset_type") is None:
        return "unknown", "quarantine/satellite/unknown", "unrecognized satellite preview filename"
    if len(observation_rows) == 1 and not asset_ids:
        return "recoverable_asset", "processed/satellite", None
    if len(observation_rows) > 1 and not parsed.get("aoi_slug"):
        return "legacy_preview", "legacy/satellite", "scene matches multiple AOIs and path has no AOI"
    if asset_ids and duplicate_paths:
        return "duplicate_file", "legacy/satellite", None
    if source_artifact_ids and duplicate_paths:
        return "duplicate_file", "legacy/satellite", None
    if observation_rows:
        return "legacy_preview", "legacy/satellite", "observation exists but asset association is not safely recoverable"
    if duplicate_paths:
        return "duplicate_file", "legacy/satellite", None
    return "legacy_preview", "legacy/satellite", "no matching observation"
