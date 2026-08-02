from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from argos.cli import build_parser, format_ecowitt_status, parse_callbacks, parse_date, parse_utc_datetime
from argos.services.ecowitt_status import EcowittStatus


def test_parse_utc_datetime_accepts_z_suffix_and_naive_values() -> None:
    assert parse_utc_datetime("2026-07-10T12:45:00Z") == datetime(2026, 7, 10, 12, 45, tzinfo=UTC)
    assert parse_utc_datetime("2026-07-10 12:45:00") == datetime(2026, 7, 10, 12, 45, tzinfo=UTC)


def test_parse_callbacks_rejects_empty_values() -> None:
    assert parse_callbacks("outdoor, rainfall_piezo") == ("outdoor", "rainfall_piezo")

    with pytest.raises(argparse.ArgumentTypeError):
        parse_callbacks(" , ")


def test_parse_date_accepts_iso_dates() -> None:
    assert parse_date("2026-07-10") == datetime(2026, 7, 10).date()


def test_build_parser_requires_gateway_identifier_for_backfill() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["ecowitt-cloud", "backfill", "--start", "2026-07-10T00:00:00Z", "--end", "2026-07-10T01:00:00Z"])

    args = parser.parse_args(
        [
            "ecowitt-cloud",
            "backfill",
            "--start",
            "2026-07-10T00:00:00Z",
            "--end",
            "2026-07-10T01:00:00Z",
            "--gateway-identifier",
            "GW2000A",
            "--station-slug",
            "tomillar",
            "--cloud-mac",
            "AA:BB:CC:DD:EE:FF",
        ]
    )
    assert args.gateway_identifier == "GW2000A"
    assert args.station_slug == "tomillar"
    assert args.cloud_mac == "AA:BB:CC:DD:EE:FF"


def test_build_parser_accepts_ecowitt_status_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["ecowitt", "status"])

    assert args.command == "ecowitt"
    assert args.ecowitt_command == "status"


def test_build_parser_accepts_aemet_commands() -> None:
    parser = build_parser()

    backfill = parser.parse_args(["aemet", "backfill", "--station", "6127X", "--start", "2026-07-01", "--end", "2026-07-31"])
    sync = parser.parse_args(["aemet", "sync", "--station", "6127X", "--lookback-days", "7"])
    csv = parser.parse_args(["aemet", "import-csv", "--station", "6127X", "--path", "6127X.csv"])

    assert backfill.aemet_command == "backfill"
    assert backfill.station == "6127X"
    assert sync.aemet_command == "sync"
    assert sync.lookback_days == 7
    assert csv.aemet_command == "import-csv"


def test_build_parser_accepts_node_capture_flowmeter_minutely_command() -> None:
    parser = build_parser()

    args = parser.parse_args(
        ["node", "capture-flowmeter-minutely", "--node-url", "http://192.168.1.40", "--poll-seconds", "5"]
    )

    assert args.command == "node"
    assert args.node_command == "capture-flowmeter-minutely"
    assert args.node_url == "http://192.168.1.40"
    assert args.poll_seconds == 5


def test_build_parser_accepts_satellite_aoi_slug() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "satellite",
            "backfill",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--aoi-slug",
            "olivos_pequenos",
        ]
    )

    assert args.satellite_command == "backfill"
    assert args.aoi_slug == "olivos_pequenos"


def test_build_parser_accepts_data_audit_duplicates() -> None:
    parser = build_parser()

    args = parser.parse_args(["data", "audit-duplicates"])

    assert args.command == "data"
    assert args.data_command == "audit-duplicates"


def test_build_parser_accepts_ingestion_traceability_data_commands() -> None:
    parser = build_parser()

    list_runs = parser.parse_args(["data", "list-ingestion-runs", "--source", "aemet_api", "--limit", "5"])
    show_run = parser.parse_args(["data", "show-ingestion-run", "run-uuid"])
    audit_runs = parser.parse_args(["data", "audit-ingestion-runs", "--older-than-minutes", "30"])
    reconcile = parser.parse_args(["data", "reconcile-ingestion-runs", "--mark-interrupted"])
    cursors = parser.parse_args(["data", "show-sync-cursors", "--source", "ecowitt_cloud"])
    artifacts = parser.parse_args(["data", "audit-source-artifacts"])
    nullability = parser.parse_args(["data", "audit-ecowitt-nullability"])
    inventory = parser.parse_args(["data", "inventory-files"])
    weather = parser.parse_args(["data", "reconcile-legacy-weather"])
    layout = parser.parse_args(["data", "migrate-layout", "--apply"])
    retention = parser.parse_args(["data", "retention-report", "--limit", "10"])
    staging = parser.parse_args(["data", "audit-staging", "--older-than-hours", "12"])

    assert list_runs.data_command == "list-ingestion-runs"
    assert list_runs.source == "aemet_api"
    assert list_runs.limit == 5
    assert show_run.run_uuid == "run-uuid"
    assert audit_runs.older_than_minutes == 30
    assert reconcile.mark_interrupted
    assert cursors.source == "ecowitt_cloud"
    assert artifacts.data_command == "audit-source-artifacts"
    assert nullability.data_command == "audit-ecowitt-nullability"
    assert inventory.data_command == "inventory-files"
    assert weather.data_command == "reconcile-legacy-weather"
    assert layout.apply
    assert retention.limit == 10
    assert staging.older_than_hours == 12


def test_format_ecowitt_status_outputs_operator_summary() -> None:
    status = EcowittStatus(
        station_slug="tomillar",
        gateway_id=1,
        gateway_identifier="GW2000A",
        station_type="GW2000A_V3.3.2",
        last_report_at=datetime(2026, 7, 10, 12, 45, tzinfo=UTC),
        online=True,
        reports_last_24h=10,
        duplicate_events=1,
        parser_warning_events=2,
        unknown_fields=3,
        open_gaps=4,
    )

    lines = format_ecowitt_status(status)

    assert "Station: tomillar" in lines
    assert "Online: yes" in lines
    assert "Reports last 24h: 10" in lines
    assert "Open gaps: 4" in lines
