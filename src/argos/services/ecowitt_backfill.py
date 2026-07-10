from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from argos.config.settings import get_settings
from argos.integrations.ecowitt_cloud import DEFAULT_HISTORY_CALLBACKS, EcowittCloudClient
from argos.repositories.ecowitt_backfill import EcowittBackfillRepository
from argos.services.ecowitt_cloud_adapter import parse_cloud_history_payload
from argos.services.weather_statistics import update_statistics_for_observation

logger = logging.getLogger(__name__)

BACKFILL_PARSER_VERSION = "ecowitt-cloud-normalized-v1"
OBSERVATION_SOURCE_BACKFILLED = "BACKFILLED"

NORMALIZED_WEATHER_VALUE_KEYS = {
    "indoor_temperature_c",
    "indoor_humidity_pct",
    "outdoor_temperature_c",
    "outdoor_humidity_pct",
    "dew_point_c",
    "feels_like_c",
    "vpd_kpa",
    "absolute_pressure_hpa",
    "relative_pressure_hpa",
    "wind_direction_deg",
    "wind_direction_avg10m_deg",
    "wind_speed_ms",
    "wind_gust_ms",
    "daily_max_gust_ms",
    "solar_radiation_wm2",
    "uv_index",
    "rain_rate_mm_h",
    "rain_event_mm",
    "rain_hour_mm",
    "rain_last_24h_mm",
    "rain_day_mm",
    "rain_week_mm",
    "rain_month_mm",
    "rain_year_mm",
    "piezo_rain_mm",
    "battery_voltage",
    "ws90_capacitor_voltage",
    "signal_dbm",
}


@dataclass(frozen=True, slots=True)
class BackfillImportResult:
    cloud_raw_report_id: int
    observation_id: int | None
    duplicate: bool
    duplicate_reason: str | None


@dataclass(frozen=True, slots=True)
class BackfillRangeResult:
    imported_count: int
    duplicate_count: int
    warning_count: int
    warnings: list[str]
    results: list[BackfillImportResult]


def backfill_ecowitt_cloud_range(
    *,
    session: Session,
    client: EcowittCloudClient,
    gateway_identifier: str,
    start: datetime,
    end: datetime,
    station_slug: str | None = None,
    station_type: str | None = None,
    gateway_aliases: Mapping[str, str] | None = None,
    callbacks: tuple[str, ...] = DEFAULT_HISTORY_CALLBACKS,
) -> BackfillRangeResult:
    payload = client.get_history(start=start, end=end, callbacks=callbacks)
    parse_result = parse_cloud_history_payload(payload)
    import_results = [
        import_backfilled_observation(
            session=session,
            gateway_identifier=gateway_identifier,
            station_slug=station_slug,
            observed_at_utc=observation.observed_at_utc,
            normalized_values=observation.normalized_values,
            cloud_payload=observation.cloud_payload,
            station_type=station_type,
            gateway_aliases=gateway_aliases,
            requested_start_utc=start,
            requested_end_utc=end,
            api_version=client.api_version,
        )
        for observation in parse_result.observations
    ]
    duplicate_count = sum(1 for result in import_results if result.duplicate)
    return BackfillRangeResult(
        imported_count=len(import_results) - duplicate_count,
        duplicate_count=duplicate_count,
        warning_count=len(parse_result.warnings),
        warnings=parse_result.warnings,
        results=import_results,
    )


def import_backfilled_observation(
    *,
    session: Session,
    gateway_identifier: str,
    observed_at_utc: datetime,
    normalized_values: Mapping[str, float | None],
    cloud_payload: Mapping[str, Any],
    station_slug: str | None = None,
    station_type: str | None = None,
    gateway_aliases: Mapping[str, str] | None = None,
    requested_start_utc: datetime | None = None,
    requested_end_utc: datetime | None = None,
    api_version: str | None = "v3",
) -> BackfillImportResult:
    values = _validate_normalized_values(normalized_values)
    payload_dict = dict(cloud_payload)
    repository = EcowittBackfillRepository(session)
    station = repository.get_or_create_station(slug=station_slug or get_settings().station_slug)
    gateway = repository.get_or_create_gateway(
        station_uuid=station.uuid,
        identifier=gateway_identifier,
        station_type=station_type,
        metadata_json={"backfill_source": "ecowitt_cloud"},
        aliases=dict(gateway_aliases or {}),
    )
    payload_hash = build_cloud_backfill_hash(
        gateway_identifier=gateway_identifier,
        observed_at_utc=observed_at_utc,
        normalized_values=values,
        cloud_payload=payload_dict,
    )

    existing_raw = repository.get_cloud_raw_report_by_hash(payload_hash)
    if existing_raw is not None:
        repository.create_event(
            station_uuid=station.uuid,
            gateway_id=gateway.id,
            event_type="BACKFILL_DUPLICATE",
            severity="INFO",
            message=f"Duplicate Ecowitt Cloud raw report ignored: {existing_raw.id}.",
        )
        session.commit()
        return BackfillImportResult(
            cloud_raw_report_id=existing_raw.id,
            observation_id=existing_raw.observation.id if existing_raw.observation else None,
            duplicate=True,
            duplicate_reason="cloud_payload_hash",
        )

    cloud_raw_report = repository.create_cloud_raw_report(
        gateway_id=gateway.id,
        station_uuid=station.uuid,
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        observed_at_utc=observed_at_utc,
        payload_json=payload_dict,
        payload_hash=payload_hash,
        api_version=api_version,
        parser_version=BACKFILL_PARSER_VERSION,
    )

    existing_observation = repository.get_observation_by_gateway_and_observed_at(
        station_uuid=station.uuid,
        gateway_id=gateway.id,
        observed_at_utc=observed_at_utc,
    )
    if existing_observation is not None:
        repository.create_event(
            station_uuid=station.uuid,
            gateway_id=gateway.id,
            event_type="BACKFILL_DUPLICATE",
            severity="INFO",
            message=(
                "Ecowitt Cloud observation was preserved as raw payload but not imported because "
                f"observation {existing_observation.id} already exists."
            ),
        )
        session.commit()
        return BackfillImportResult(
            cloud_raw_report_id=cloud_raw_report.id,
            observation_id=existing_observation.id,
            duplicate=True,
            duplicate_reason="existing_observation_timestamp",
        )

    observation = repository.create_backfilled_observation(
        gateway_id=gateway.id,
        station_uuid=station.uuid,
        cloud_raw_report_id=cloud_raw_report.id,
        observed_at_utc=observed_at_utc,
        received_at_utc=datetime.now(UTC),
        values=values,
    )
    update_statistics_for_observation(session, observation)
    repository.create_event(
        station_uuid=station.uuid,
        gateway_id=gateway.id,
        event_type="BACKFILL_IMPORTED",
        severity="INFO",
        message="Ecowitt Cloud observation imported as BACKFILLED.",
    )
    session.commit()
    logger.info("ecowitt cloud backfill imported", extra={"observation_id": observation.id})
    return BackfillImportResult(
        cloud_raw_report_id=cloud_raw_report.id,
        observation_id=observation.id,
        duplicate=False,
        duplicate_reason=None,
    )


def build_cloud_backfill_hash(
    *,
    gateway_identifier: str,
    observed_at_utc: datetime,
    normalized_values: Mapping[str, float | None],
    cloud_payload: Mapping[str, Any],
) -> str:
    canonical = json.dumps(
        {
            "cloud_payload": dict(cloud_payload),
            "gateway_identifier": gateway_identifier,
            "normalized_values": dict(normalized_values),
            "observed_at_utc": observed_at_utc.isoformat(),
            "parser_version": BACKFILL_PARSER_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_normalized_values(values: Mapping[str, float | None]) -> dict[str, float | None]:
    unknown_keys = sorted(set(values) - NORMALIZED_WEATHER_VALUE_KEYS)
    if unknown_keys:
        raise ValueError(f"Unknown normalized weather fields for Ecowitt Cloud backfill: {', '.join(unknown_keys)}")
    return {key: values.get(key) for key in NORMALIZED_WEATHER_VALUE_KEYS}
