from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class DuplicateCheck:
    name: str
    description: str
    severity: str
    query: str


@dataclass(frozen=True, slots=True)
class DuplicateCheckResult:
    name: str
    description: str
    severity: str
    duplicate_groups: int
    affected_rows: int
    examples: list[dict[str, Any]]

    @property
    def failed(self) -> bool:
        return self.severity == "error" and self.duplicate_groups > 0


DUPLICATE_CHECKS = (
    DuplicateCheck(
        name="ecowitt_observations",
        description="Ecowitt observations by gateway, observed_at_utc and source",
        severity="error",
        query="""
            SELECT gateway_id, observed_at_utc, source, count(*) AS duplicate_count,
                   group_concat(id) AS ids
            FROM weather_observations
            GROUP BY gateway_id, observed_at_utc, source
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
        """,
    ),
    DuplicateCheck(
        name="ecowitt_raw_payload_hash",
        description="Ecowitt direct raw reports by payload hash",
        severity="error",
        query="""
            SELECT payload_hash, count(*) AS duplicate_count, group_concat(id) AS ids
            FROM ecowitt_raw_reports
            GROUP BY payload_hash
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
        """,
    ),
    DuplicateCheck(
        name="ecowitt_cloud_payload_hash",
        description="Ecowitt Cloud raw reports by payload hash",
        severity="error",
        query="""
            SELECT payload_hash, count(*) AS duplicate_count, group_concat(id) AS ids
            FROM ecowitt_cloud_raw_reports
            GROUP BY payload_hash
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
        """,
    ),
    DuplicateCheck(
        name="aemet_daily",
        description="AEMET observations by station and date",
        severity="error",
        query="""
            SELECT station_id, observation_date, count(*) AS duplicate_count, group_concat(id) AS ids
            FROM weather_daily_observations
            GROUP BY station_id, observation_date
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
        """,
    ),
    DuplicateCheck(
        name="satellite_observations",
        description="Satellite observations by source, zone, external item and processing version",
        severity="error",
        query="""
            SELECT source_id, zone_id, external_item_id, processing_version,
                   count(*) AS duplicate_count, group_concat(id) AS ids
            FROM satellite_observations
            GROUP BY source_id, zone_id, external_item_id, processing_version
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
        """,
    ),
    DuplicateCheck(
        name="satellite_assets",
        description="Satellite assets by observation and asset type",
        severity="error",
        query="""
            SELECT observation_id, asset_type, count(*) AS duplicate_count, group_concat(id) AS ids
            FROM satellite_assets
            GROUP BY observation_id, asset_type
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
        """,
    ),
    DuplicateCheck(
        name="flowmeter_minutes",
        description="Flowmeter minute aggregates by node and minute",
        severity="error",
        query="""
            SELECT node_url, window_start_utc, count(*) AS duplicate_count, group_concat(id) AS ids
            FROM argos_node_flowmeter_minutes
            GROUP BY node_url, window_start_utc
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
        """,
    ),
    DuplicateCheck(
        name="field_events",
        description="Field events by date, type, title and zone",
        severity="warning",
        query="""
            SELECT occurred_at, event_type, title, coalesce(zone_slug, '') AS zone_slug,
                   count(*) AS duplicate_count, group_concat(id) AS ids
            FROM field_events
            GROUP BY occurred_at, event_type, title, coalesce(zone_slug, '')
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
        """,
    ),
)


def audit_duplicates(session: Session) -> list[DuplicateCheckResult]:
    return [_run_check(session, check) for check in DUPLICATE_CHECKS if _table_dependencies_exist(session, check.query)]


def format_duplicate_results(results: list[DuplicateCheckResult]) -> list[str]:
    lines: list[str] = []
    for result in results:
        status = "FAIL" if result.failed else ("WARN" if result.duplicate_groups else "OK")
        lines.append(
            f"{status} {result.name}: groups={result.duplicate_groups} affected_rows={result.affected_rows}"
        )
        lines.append(f"  {result.description}")
        for example in result.examples[:3]:
            lines.append(f"  example: {example}")
    return lines


def has_structural_duplicates(results: list[DuplicateCheckResult]) -> bool:
    return any(result.failed for result in results)


def _run_check(session: Session, check: DuplicateCheck) -> DuplicateCheckResult:
    rows = [dict(row._mapping) for row in session.execute(text(check.query)).all()]
    affected_rows = sum(int(row["duplicate_count"]) for row in rows)
    return DuplicateCheckResult(
        name=check.name,
        description=check.description,
        severity=check.severity,
        duplicate_groups=len(rows),
        affected_rows=affected_rows,
        examples=rows,
    )


def _table_dependencies_exist(session: Session, query: str) -> bool:
    existing = set(inspect(session.bind).get_table_names()) if session.bind is not None else set()
    required = {
        table_name
        for table_name in (
            "weather_observations",
            "ecowitt_raw_reports",
            "ecowitt_cloud_raw_reports",
            "weather_daily_observations",
            "satellite_observations",
            "satellite_assets",
            "argos_node_flowmeter_minutes",
            "field_events",
        )
        if table_name in query
    }
    return required <= existing
