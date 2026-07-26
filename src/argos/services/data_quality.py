from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from argos.models.ecowitt import WeatherObservation
from argos.repositories.weather import WeatherRepository


def detect_gap_for_observation(
    *,
    session: Session,
    observation: WeatherObservation,
    expected_interval_seconds: int,
) -> None:
    previous = WeatherRepository(session).previous_observation(
        station_uuid=observation.station_uuid,
        gateway_id=observation.gateway_id,
        observed_at_utc=observation.observed_at_utc,
    )
    if previous is None:
        return

    observed_at_utc = _ensure_utc(observation.observed_at_utc)
    previous_at_utc = _ensure_utc(previous.observed_at_utc)
    delta_seconds = (observed_at_utc - previous_at_utc).total_seconds()
    max_expected_seconds = expected_interval_seconds * 2
    if delta_seconds <= max_expected_seconds:
        return

    missing_reports = max(int(delta_seconds // expected_interval_seconds) - 1, 1)
    WeatherRepository(session).create_data_gap(
        station_uuid=observation.station_uuid,
        gateway_id=observation.gateway_id,
        gap_start=previous_at_utc + timedelta(seconds=expected_interval_seconds),
        gap_end=observed_at_utc - timedelta(seconds=expected_interval_seconds),
        expected_reports=missing_reports,
        received_reports=0,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
