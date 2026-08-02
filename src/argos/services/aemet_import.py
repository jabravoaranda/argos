from __future__ import annotations

from dataclasses import dataclass, field
import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from argos.config.settings import Settings, get_settings
from argos.integrations.aemet.client import AemetClient
from argos.repositories.aemet import AemetRepository
from argos.services.aemet_normalizer import normalize_aemet_daily_records
from argos.services.ingestion_trace import (
    create_ingestion_item,
    fail_ingestion_item,
    finalize_ingestion_run,
    finish_ingestion_item,
    start_ingestion_run,
    update_sync_cursor,
)


@dataclass(frozen=True, slots=True)
class AemetImportInterval:
    start: date
    end: date
    records_received: int = 0
    status: str = "pending"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "records_received": self.records_received,
            "status": self.status,
            "error": self.error,
        }


@dataclass(slots=True)
class AemetImportSummary:
    station_external_id: str
    start: date
    end: date
    intervals: list[AemetImportInterval] = field(default_factory=list)
    records_received: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors and self.records_received == 0:
            return "failed"
        if self.errors:
            return "partial"
        return "success"


class AemetImportRangeError(ValueError):
    """Raised when an AEMET import range is invalid."""


class AemetImportService:
    def __init__(self, *, session: Session, client: AemetClient, settings: Settings | None = None) -> None:
        self.session = session
        self.client = client
        self.settings = settings or get_settings()
        self.repository = AemetRepository(session)

    def backfill(
        self,
        *,
        station_id: str,
        start: date,
        end: date,
        block_days: int | None = None,
        mode: str = "backfill",
    ) -> AemetImportSummary:
        validate_import_range(start=start, end=end)
        block_size = block_days or self.settings.aemet_block_days
        if block_size < 1:
            raise AemetImportRangeError("AEMET block size must be at least 1 day.")

        station = self.repository.get_or_create_station(
            external_id=station_id,
            **station_defaults_from_metadata(self._fetch_station_metadata(station_id)),
        )
        run_trace = start_ingestion_run(
            self.session,
            source_code="aemet_api",
            mode=mode,
            trigger="manual" if mode == "backfill" else "scheduled",
            requested_start_utc=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
            requested_end_utc=datetime.combine(end, datetime.min.time(), tzinfo=UTC),
            parameters_json={"station_id": station_id, "block_days": block_size},
        )
        run = self.repository.create_sync_run(
            station_id=station.id,
            station_external_id=station_id,
            mode=mode,
            requested_start=start,
            requested_end=end,
            ingestion_run_id=run_trace.id,
        )
        self.session.commit()

        summary = AemetImportSummary(station_external_id=station_id, start=start, end=end)
        for interval_start, interval_end in split_date_range(start=start, end=end, block_days=block_size):
            item = create_ingestion_item(
                self.session,
                run=run_trace,
                item_key=f"{station_id}:{interval_start.isoformat()}:{interval_end.isoformat()}",
                item_type="aemet_interval",
                requested_start_utc=datetime.combine(interval_start, datetime.min.time(), tzinfo=UTC),
                requested_end_utc=datetime.combine(interval_end, datetime.min.time(), tzinfo=UTC),
            )
            try:
                records = self.client.daily_climatology(start=interval_start, end=interval_end, station_id=station_id)
                normalized_records = normalize_aemet_daily_records(records)
                for normalized in normalized_records:
                    _, action = self.repository.upsert_daily_observation(
                        station_id=station.id,
                        normalized=normalized,
                        ingestion_run_id=run_trace.id,
                        ingestion_item_id=item.id,
                    )
                    if action == "inserted":
                        summary.inserted += 1
                        item.inserted_count += 1
                    elif action == "updated":
                        summary.updated += 1
                        item.updated_count += 1
                    else:
                        summary.skipped += 1
                        item.unchanged_count += 1
                summary.records_received += len(records)
                item.inserted_count = item.inserted_count
                finish_ingestion_item(item)
                summary.intervals.append(
                    AemetImportInterval(
                        start=interval_start,
                        end=interval_end,
                        records_received=len(records),
                        status="success",
                    )
                )
                self._update_run(run, summary)
                self.session.commit()
            except Exception as exc:
                fail_ingestion_item(item, exc)
                error = {
                    "start": interval_start.isoformat(),
                    "end": interval_end.isoformat(),
                    "message": str(exc),
                }
                summary.errors.append(error)
                summary.intervals.append(
                    AemetImportInterval(start=interval_start, end=interval_end, status="failed", error=str(exc))
                )
                self._update_run(run, summary)
                self.session.commit()

        run.finished_at = datetime.now(UTC)
        self._update_run(run, summary)
        run_trace.discovered_count = summary.records_received
        run_trace.inserted_count = summary.inserted
        run_trace.updated_count = summary.updated
        run_trace.unchanged_count = summary.skipped
        run_trace.failed_count = len(summary.errors)
        run_trace.warning_count = len(summary.errors)
        if summary.errors:
            run_trace.error_summary = f"{len(summary.errors)} AEMET interval(s) failed."
        finalize_ingestion_run(run_trace)
        if run_trace.status in {"completed", "completed_with_warnings"} and not summary.errors:
            update_sync_cursor(
                self.session,
                source_code="aemet_api",
                scope="station",
                scope_key=station_id,
                cursor_type="date",
                cursor_value_json={"last_successful_date": end.isoformat()},
                last_successful_run=run_trace,
            )
        self.session.commit()
        return summary

    def sync(self, *, station_id: str, lookback_days: int) -> AemetImportSummary:
        if lookback_days < 1:
            raise AemetImportRangeError("AEMET lookback days must be at least 1.")
        end = datetime.now(UTC).date()
        start = end - timedelta(days=lookback_days - 1)
        return self.backfill(station_id=station_id, start=start, end=end, mode="sync")

    def import_csv(self, *, path: Path, station_id: str) -> AemetImportSummary:
        if not path.exists() or not path.is_file():
            raise AemetImportRangeError(f"AEMET CSV file not found: {path}")

        with path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = [dict(row) for row in csv.DictReader(file)]

        if not rows:
            today = datetime.now(UTC).date()
            return AemetImportSummary(station_external_id=station_id, start=today, end=today)

        normalized_records = normalize_aemet_daily_records(rows)
        observed_dates = [item.observation_date for item in normalized_records]
        station = self.repository.get_or_create_station(
            external_id=station_id,
            **station_defaults_from_csv_row(rows[0]),
        )
        run_trace = start_ingestion_run(
            self.session,
            source_code="aemet_csv",
            mode="csv",
            trigger="manual",
            requested_start_utc=datetime.combine(min(observed_dates), datetime.min.time(), tzinfo=UTC),
            requested_end_utc=datetime.combine(max(observed_dates), datetime.min.time(), tzinfo=UTC),
            parameters_json={"station_id": station_id, "path": str(path)},
        )
        item = create_ingestion_item(
            self.session,
            run=run_trace,
            item_key=str(path),
            item_type="aemet_csv_file",
            metadata_json={"filename": path.name},
        )
        run = self.repository.create_sync_run(
            station_id=station.id,
            station_external_id=station_id,
            mode="csv",
            requested_start=min(observed_dates),
            requested_end=max(observed_dates),
            ingestion_run_id=run_trace.id,
        )

        summary = AemetImportSummary(
            station_external_id=station_id,
            start=min(observed_dates),
            end=max(observed_dates),
        )
        for normalized in normalized_records:
            _, action = self.repository.upsert_daily_observation(
                station_id=station.id,
                normalized=normalized,
                ingestion_run_id=run_trace.id,
                ingestion_item_id=item.id,
            )
            if action == "inserted":
                summary.inserted += 1
                item.inserted_count += 1
            elif action == "updated":
                summary.updated += 1
                item.updated_count += 1
            else:
                summary.skipped += 1
                item.unchanged_count += 1

        summary.records_received = len(rows)
        summary.intervals.append(
            AemetImportInterval(
                start=summary.start,
                end=summary.end,
                records_received=len(rows),
                status="success",
            )
        )
        run.finished_at = datetime.now(UTC)
        self._update_run(run, summary)
        run_trace.discovered_count = summary.records_received
        run_trace.inserted_count = summary.inserted
        run_trace.updated_count = summary.updated
        run_trace.unchanged_count = summary.skipped
        finish_ingestion_item(item)
        finalize_ingestion_run(run_trace)
        update_sync_cursor(
            self.session,
            source_code="aemet_csv",
            scope="station",
            scope_key=station_id,
            cursor_type="date",
            cursor_value_json={"last_imported_date": summary.end.isoformat(), "path": str(path)},
            last_successful_run=run_trace,
        )
        self.session.commit()
        return summary

    def _fetch_station_metadata(self, station_id: str) -> dict[str, Any] | None:
        try:
            return self.client.station_metadata(station_id=station_id)
        except Exception:
            return None

    def _update_run(self, run, summary: AemetImportSummary) -> None:
        run.status = summary.status if run.finished_at else ("partial" if summary.errors else "running")
        run.intervals_json = [interval.as_dict() for interval in summary.intervals]
        run.records_received = summary.records_received
        run.inserted = summary.inserted
        run.updated = summary.updated
        run.skipped = summary.skipped
        run.errors_json = summary.errors


def split_date_range(*, start: date, end: date, block_days: int) -> list[tuple[date, date]]:
    ranges = []
    cursor = start
    while cursor <= end:
        interval_end = min(cursor + timedelta(days=block_days - 1), end)
        ranges.append((cursor, interval_end))
        cursor = interval_end + timedelta(days=1)
    return ranges


def validate_import_range(*, start: date, end: date) -> None:
    if end < start:
        raise AemetImportRangeError("AEMET import end date must be on or after start date.")


def station_defaults_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {
            "name": "Álora",
            "municipality": "Álora",
            "province": "Málaga",
            "metadata_json": {"default_station": True},
        }
    return {
        "name": str(metadata.get("nombre") or "Álora"),
        "municipality": str(metadata.get("nombre") or "Álora"),
        "province": str(metadata.get("provincia") or "Málaga"),
        "latitude": _parse_coordinate(metadata.get("latitud")),
        "longitude": _parse_coordinate(metadata.get("longitud")),
        "altitude_m": _parse_altitude(metadata.get("altitud")),
        "metadata_json": dict(metadata),
    }


def station_defaults_from_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(row.get("nombre") or "Álora"),
        "municipality": str(row.get("nombre") or "Álora").title(),
        "province": str(row.get("provincia") or "Málaga").title(),
        "altitude_m": _parse_altitude(row.get("altitud")),
        "metadata_json": {"source": "csv_seed", "columns": list(row.keys())},
    }


def _parse_coordinate(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        pass
    # AEMET inventory commonly uses sexagesimal DDMMSS[N/S/E/W].
    suffix = text[-1].upper()
    digits = text[:-1]
    if suffix not in {"N", "S", "E", "W"} or not digits.isdigit() or len(digits) < 5:
        return None
    degrees_width = len(digits) - 4
    degrees = int(digits[:degrees_width])
    minutes = int(digits[degrees_width : degrees_width + 2])
    seconds = int(digits[degrees_width + 2 :])
    decimal = degrees + minutes / 60 + seconds / 3600
    if suffix in {"S", "W"}:
        decimal *= -1
    return decimal


def _parse_altitude(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None
