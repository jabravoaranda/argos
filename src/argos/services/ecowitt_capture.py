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
from argos.parsers.ecowitt_ws90 import parse_ws90_payload
from argos.repositories.ecowitt_capture import EcowittCaptureRepository
from argos.services.data_quality import detect_gap_for_observation
from argos.services.weather_statistics import update_statistics_for_observation

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EcowittCapture:
    raw_report_id: int
    observation_id: int | None
    duplicate: bool
    payload_keys: list[str]
    warnings: list[str]
    unknown_field_count: int


def capture_ecowitt_payload(
    *,
    session: Session,
    payload: Mapping[str, Any],
    raw_body_text: str | None,
    http_method: str,
    source_ip: str | None,
    content_type: str | None,
    headers: Mapping[str, str] | None,
    query_string: str | None,
) -> EcowittCapture:
    payload_dict = dict(payload)
    received_at_utc = datetime.now(UTC)
    parse_result = parse_ws90_payload(payload_dict, received_at_utc)
    payload_hash = build_observation_hash(
        station_type=parse_result.station_type,
        model=parse_result.model,
        observed_at_utc=parse_result.observed_at_utc,
        normalized_values=parse_result.normalized_values,
        parser_version=parse_result.parser_version,
    )
    repository = EcowittCaptureRepository(session)
    station = repository.get_or_create_station(slug=get_settings().station_slug)
    existing = repository.get_raw_report_by_hash(payload_hash)
    if existing is not None:
        logger.info("duplicate ecowitt payload ignored", extra={"raw_report_id": existing.id})
        repository.create_event(
            station_uuid=existing.station_uuid,
            gateway_id=existing.gateway_id,
            raw_report_id=existing.id,
            event_type="DUPLICATE",
            severity="INFO",
            message="Duplicate Ecowitt capture ignored.",
        )
        session.commit()
        return EcowittCapture(
            raw_report_id=existing.id,
            observation_id=existing.observation.id if existing.observation else None,
            duplicate=True,
            payload_keys=sorted(payload_dict),
            warnings=parse_result.warnings,
            unknown_field_count=len(parse_result.unknown_fields),
        )

    gateway_identifier = parse_result.model or parse_result.station_type or source_ip or "unknown-gw2000"
    logger.info(
        "ecowitt payload received",
        extra={
            "payload_key_count": len(payload_dict),
            "gateway_identifier": gateway_identifier,
            "source_ip": source_ip,
        },
    )
    gateway = repository.get_or_create_gateway(
        station_uuid=station.uuid,
        identifier=gateway_identifier,
        station_type=parse_result.station_type,
        seen_at=received_at_utc,
        metadata_json=_gateway_metadata(payload_dict),
    )

    raw_report = repository.create_raw_report(
        station_uuid=station.uuid,
        gateway_id=gateway.id,
        received_at_utc=received_at_utc,
        device_timestamp_utc=parse_result.observed_at_utc,
        http_method=http_method,
        source_ip=source_ip,
        content_type=content_type,
        payload_json=payload_dict,
        raw_body_text=raw_body_text,
        payload_hash=payload_hash,
        headers_json=dict(headers) if headers is not None else None,
        query_string=query_string,
        parser_version=parse_result.parser_version,
    )
    observation = repository.create_weather_observation(
        station_uuid=station.uuid,
        gateway_id=gateway.id,
        raw_report_id=raw_report.id,
        observed_at_utc=parse_result.observed_at_utc,
        received_at_utc=received_at_utc,
        values=parse_result.normalized_values,
    )
    detect_gap_for_observation(
        session=session,
        observation=observation,
        expected_interval_seconds=get_settings().ecowitt_expected_interval_seconds,
    )
    update_statistics_for_observation(session, observation)
    repository.upsert_unknown_fields(parse_result.unknown_fields, received_at_utc)
    repository.create_event(
        station_uuid=station.uuid,
        gateway_id=gateway.id,
        raw_report_id=raw_report.id,
        event_type="REPORT_RECEIVED",
        severity="INFO",
        message="Ecowitt raw payload captured and normalized.",
    )
    for warning in parse_result.warnings:
        logger.warning("ecowitt parser warning: %s", warning)
        repository.create_event(
            station_uuid=station.uuid,
            gateway_id=gateway.id,
            raw_report_id=raw_report.id,
            event_type="PARSER_WARNING",
            severity="WARNING",
            message=warning,
        )
    for field_name in parse_result.unknown_fields:
        logger.info("ecowitt unknown field captured: %s", field_name)
        repository.create_event(
            station_uuid=station.uuid,
            gateway_id=gateway.id,
            raw_report_id=raw_report.id,
            event_type="UNKNOWN_FIELD",
            severity="INFO",
            message=f"Ecowitt field captured without normalized mapping: {field_name}",
        )
    session.commit()
    logger.info("ecowitt observation created", extra={"observation_id": observation.id, "raw_report_id": raw_report.id})
    return EcowittCapture(
        raw_report_id=raw_report.id,
        observation_id=observation.id,
        duplicate=False,
        payload_keys=sorted(payload_dict),
        warnings=parse_result.warnings,
        unknown_field_count=len(parse_result.unknown_fields),
    )


def build_observation_hash(
    *,
    station_type: str | None,
    model: str | None,
    observed_at_utc: datetime,
    normalized_values: Mapping[str, float | None],
    parser_version: str,
) -> str:
    canonical = json.dumps(
        {
            "model": model,
            "normalized_values": dict(normalized_values),
            "observed_at_utc": observed_at_utc.isoformat(),
            "parser_version": parser_version,
            "station_type": station_type,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _gateway_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata_keys = ("runtime", "heap", "freq", "interval", "ws90_ver", "model", "stationtype", "mac", "macaddress")
    return {key: payload[key] for key in metadata_keys if key in payload}
