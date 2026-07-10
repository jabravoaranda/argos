from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from argos.models.ecowitt import DataGap, EcowittRawReport, IngestionEvent, UnknownField
from argos.repositories.weather import WeatherRepository


@dataclass(frozen=True, slots=True)
class EcowittStatus:
    station_slug: str | None
    gateway_id: int | None
    gateway_identifier: str | None
    station_type: str | None
    last_report_at: datetime | None
    online: bool
    reports_last_24h: int
    duplicate_events: int
    parser_warning_events: int
    unknown_fields: int
    open_gaps: int


def build_ecowitt_status(
    *,
    session: Session,
    offline_after_seconds: int,
    now_utc: datetime | None = None,
) -> EcowittStatus:
    now = now_utc or datetime.now(UTC)
    repository = WeatherRepository(session)
    gateway = repository.latest_gateway()
    last_report_at = _ensure_utc(gateway.last_seen_at) if gateway and gateway.last_seen_at else None
    seconds_since_last_report = (now - last_report_at).total_seconds() if last_report_at else None

    return EcowittStatus(
        station_slug=gateway.station.slug if gateway and gateway.station else None,
        gateway_id=gateway.id if gateway else None,
        gateway_identifier=gateway.mac_address if gateway else None,
        station_type=gateway.station_type if gateway else None,
        last_report_at=last_report_at,
        online=seconds_since_last_report is not None and seconds_since_last_report <= offline_after_seconds,
        reports_last_24h=_count_raw_reports_since(session, now - timedelta(hours=24)),
        duplicate_events=_count_events(session, "DUPLICATE"),
        parser_warning_events=_count_events(session, "PARSER_WARNING"),
        unknown_fields=_count_unknown_fields(session),
        open_gaps=_count_open_gaps(session),
    )


def _count_raw_reports_since(session: Session, cutoff_utc: datetime) -> int:
    naive_cutoff = cutoff_utc.replace(tzinfo=None)
    return int(
        session.scalar(
            select(func.count(EcowittRawReport.id)).where(
                or_(
                    EcowittRawReport.received_at_utc >= cutoff_utc,
                    EcowittRawReport.received_at_utc >= naive_cutoff,
                )
            )
        )
        or 0
    )


def _count_events(session: Session, event_type: str) -> int:
    return int(
        session.scalar(select(func.count(IngestionEvent.id)).where(IngestionEvent.event_type == event_type))
        or 0
    )


def _count_unknown_fields(session: Session) -> int:
    return int(session.scalar(select(func.count(UnknownField.id))) or 0)


def _count_open_gaps(session: Session) -> int:
    return int(session.scalar(select(func.count(DataGap.id)).where(DataGap.resolved.is_(False))) or 0)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
