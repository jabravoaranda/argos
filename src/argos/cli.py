from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NoReturn

from argos.config.settings import get_settings
from argos.database.session import get_sessionmaker
from argos.dashboard.argos_node_client import ArgosNodeClient, ArgosNodeError
from argos.integrations.aemet.client import AemetClient, AemetConfigError
from argos.integrations.ecowitt_cloud import DEFAULT_HISTORY_CALLBACKS, EcowittCloudClient, EcowittCloudConfigError
from argos.services.argos_node_flowmeter import ArgosNodeStatusError, run_flowmeter_minute_capture
from argos.services.aemet_import import AemetImportRangeError, AemetImportService
from argos.services.ecowitt_backfill import BackfillRangeError, backfill_ecowitt_cloud_range
from argos.services.ecowitt_status import EcowittStatus, build_ecowitt_status
from argos.services.satellite_ingestion import SatelliteIngestionService
from argos.ops.data_duplicates import audit_duplicates, format_duplicate_results, has_structural_duplicates
from argos.models.ingestion import DataSource, IngestionRun, SyncCursor
from argos.services.ingestion_trace import (
    abandoned_runs,
    audit_source_artifacts,
    mark_run_interrupted,
    validate_cursor,
)
from sqlalchemy import func, select
from argos.models.ecowitt import WeatherObservation


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "ecowitt" and args.ecowitt_command == "status":
        run_ecowitt_status()
        return
    if args.command == "ecowitt-cloud" and args.ecowitt_cloud_command == "backfill":
        run_cloud_backfill(args)
        return
    if args.command == "satellite":
        run_satellite(args)
        return
    if args.command == "aemet":
        run_aemet(args)
        return
    if args.command == "node":
        run_node(args)
        return
    if args.command == "data":
        run_data(args)
        return
    parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="argos")
    subparsers = parser.add_subparsers(dest="command")

    ecowitt_parser = subparsers.add_parser("ecowitt", help="Direct Ecowitt LAN ingestion utilities.")
    ecowitt_subparsers = ecowitt_parser.add_subparsers(dest="ecowitt_command")
    ecowitt_subparsers.add_parser("status", help="Report local Ecowitt ingestion status.")

    cloud_parser = subparsers.add_parser("ecowitt-cloud", help="Ecowitt Cloud backfill utilities.")
    cloud_subparsers = cloud_parser.add_subparsers(dest="ecowitt_cloud_command")
    backfill_parser = cloud_subparsers.add_parser("backfill", help="Import a bounded Ecowitt Cloud history range.")
    backfill_parser.add_argument("--start", required=True, type=parse_utc_datetime, help="UTC start datetime.")
    backfill_parser.add_argument("--end", required=True, type=parse_utc_datetime, help="UTC end datetime.")
    backfill_parser.add_argument(
        "--station-slug",
        default=None,
        help="Logical station slug. Defaults to STATION_SLUG from settings.",
    )
    backfill_parser.add_argument(
        "--gateway-identifier",
        required=True,
        help="Gateway identity used for deduplication. Use the current LAN identity until aliases exist.",
    )
    backfill_parser.add_argument("--station-type", default=None, help="Optional station type metadata.")
    backfill_parser.add_argument(
        "--cloud-mac",
        default=None,
        help="Optional Ecowitt Cloud MAC alias to link Cloud data to an existing LAN gateway.",
    )
    backfill_parser.add_argument(
        "--callbacks",
        default=",".join(DEFAULT_HISTORY_CALLBACKS),
        help="Comma-separated Ecowitt Cloud call_back groups.",
    )

    satellite_parser = subparsers.add_parser("satellite", help="Satellite observation utilities.")
    satellite_subparsers = satellite_parser.add_subparsers(dest="satellite_command")
    satellite_subparsers.add_parser("status", help="Report satellite module status.")
    satellite_backfill = satellite_subparsers.add_parser("backfill", help="Import Sentinel-2 history.")
    satellite_backfill.add_argument("--aoi-slug", default=None, help="Configured AOI slug. Defaults to all AOIs.")
    satellite_backfill.add_argument("--zone", default=None, help="Deprecated alias for --aoi-slug.")
    satellite_backfill.add_argument("--from", dest="start", default=None, type=parse_utc_datetime, help="UTC start datetime.")
    satellite_backfill.add_argument("--to", dest="end", default=None, type=parse_utc_datetime, help="UTC end datetime.")
    satellite_backfill.add_argument("--force", action="store_true", help="Reprocess existing observations.")
    satellite_backfill.add_argument("--dry-run", action="store_true", help="Search only; do not write observations.")
    satellite_update = satellite_subparsers.add_parser("update", help="Import new Sentinel-2 observations.")
    satellite_update.add_argument("--aoi-slug", default=None, help="Configured AOI slug. Defaults to all AOIs.")
    satellite_update.add_argument("--zone", default=None, help="Deprecated alias for --aoi-slug.")
    satellite_update.add_argument("--force", action="store_true", help="Reprocess existing observations.")
    satellite_update.add_argument("--dry-run", action="store_true", help="Search only; do not write observations.")

    aemet_parser = subparsers.add_parser("aemet", help="AEMET OpenData daily climatology utilities.")
    aemet_subparsers = aemet_parser.add_subparsers(dest="aemet_command")
    aemet_backfill = aemet_subparsers.add_parser("backfill", help="Import an AEMET daily climatology range.")
    aemet_backfill.add_argument("--station", default=None, help="AEMET station id. Defaults to AEMET_STATION_ID.")
    aemet_backfill.add_argument("--start", required=True, type=parse_date, help="Start date YYYY-MM-DD.")
    aemet_backfill.add_argument("--end", required=True, type=parse_date, help="End date YYYY-MM-DD.")
    aemet_backfill.add_argument("--block-days", default=None, type=int, help="Maximum days per AEMET request block.")
    aemet_sync = aemet_subparsers.add_parser("sync", help="Refresh recent AEMET daily climatology data.")
    aemet_sync.add_argument("--station", default=None, help="AEMET station id. Defaults to AEMET_STATION_ID.")
    aemet_sync.add_argument("--lookback-days", default=None, type=int, help="Days to refresh. Defaults to AEMET_SYNC_LOOKBACK_DAYS.")
    aemet_csv = aemet_subparsers.add_parser("import-csv", help="Import a local AEMET daily climatology CSV export.")
    aemet_csv.add_argument("--station", default=None, help="AEMET station id. Defaults to AEMET_STATION_ID.")
    aemet_csv.add_argument("--path", required=True, type=Path, help="Path to the AEMET CSV file.")

    node_parser = subparsers.add_parser("node", help="argos-node capture utilities.")
    node_subparsers = node_parser.add_subparsers(dest="node_command")
    flowmeter_parser = node_subparsers.add_parser(
        "capture-flowmeter-minutely",
        help="Poll GET /status and persist one aggregated flowmeter row per UTC minute.",
    )
    flowmeter_parser.add_argument("--node-url", default=None, help="argos-node base URL. Defaults to ARGOS_NODE_URL.")
    flowmeter_parser.add_argument(
        "--poll-seconds",
        default=None,
        type=float,
        help="Polling interval in seconds. Defaults to ARGOS_NODE_POLL_INTERVAL_SECONDS.",
    )

    data_parser = subparsers.add_parser("data", help="Data protection and audit utilities.")
    data_subparsers = data_parser.add_subparsers(dest="data_command")
    data_subparsers.add_parser("audit-duplicates", help="Read-only duplicate audit for persisted data.")
    runs_parser = data_subparsers.add_parser("list-ingestion-runs", help="List recent ingestion runs.")
    runs_parser.add_argument("--source", default=None)
    runs_parser.add_argument("--status", default=None)
    runs_parser.add_argument("--limit", type=int, default=20)
    show_run_parser = data_subparsers.add_parser("show-ingestion-run", help="Show one ingestion run.")
    show_run_parser.add_argument("run_uuid")
    audit_runs_parser = data_subparsers.add_parser("audit-ingestion-runs", help="Audit abandoned ingestion runs.")
    audit_runs_parser.add_argument("--older-than-minutes", type=int, default=60)
    reconcile_parser = data_subparsers.add_parser("reconcile-ingestion-runs", help="List or mark abandoned ingestion runs.")
    reconcile_parser.add_argument("--older-than-minutes", type=int, default=60)
    reconcile_parser.add_argument("--mark-interrupted", action="store_true")
    cursors_parser = data_subparsers.add_parser("show-sync-cursors", help="Show sync cursors.")
    cursors_parser.add_argument("--source", default=None)
    data_subparsers.add_parser("audit-source-artifacts", help="Audit source artifact files and checksums.")
    data_subparsers.add_parser("audit-ecowitt-nullability", help="Audit Ecowitt observation identity NULL values.")

    return parser


def run_ecowitt_status() -> None:
    settings = get_settings()
    with get_sessionmaker()() as session:
        status = build_ecowitt_status(
            session=session,
            offline_after_seconds=settings.ecowitt_offline_after_seconds,
        )

    for line in format_ecowitt_status(status):
        print(line)


def format_ecowitt_status(status: EcowittStatus) -> list[str]:
    return [
        f"Station: {status.station_slug or '-'}",
        f"Gateway: {status.gateway_identifier or '-'}",
        f"Gateway ID: {status.gateway_id or '-'}",
        f"Station type: {status.station_type or '-'}",
        f"Last report: {status.last_report_at.isoformat() if status.last_report_at else '-'}",
        f"Online: {'yes' if status.online else 'no'}",
        f"Reports last 24h: {status.reports_last_24h}",
        f"Duplicate events: {status.duplicate_events}",
        f"Parser warnings: {status.parser_warning_events}",
        f"Unknown fields: {status.unknown_fields}",
        f"Open gaps: {status.open_gaps}",
    ]


def run_cloud_backfill(args: argparse.Namespace) -> None:
    settings = get_settings()
    try:
        client = EcowittCloudClient.from_settings(settings)
    except EcowittCloudConfigError as exc:
        raise SystemExit(str(exc)) from exc

    callbacks = parse_callbacks(args.callbacks)
    with get_sessionmaker()() as session:
        try:
            result = backfill_ecowitt_cloud_range(
                session=session,
                client=client,
                gateway_identifier=args.gateway_identifier,
                station_slug=args.station_slug or settings.station_slug,
                station_type=args.station_type,
                gateway_aliases={"ecowitt_cloud_mac": args.cloud_mac} if args.cloud_mac else None,
                start=args.start,
                end=args.end,
                callbacks=callbacks,
            )
        except BackfillRangeError as exc:
            raise SystemExit(str(exc)) from exc

    print(f"Imported: {result.imported_count}")
    print(f"Duplicates: {result.duplicate_count}")
    print(f"Warnings: {result.warning_count}")
    for warning in result.warnings:
        print(f"- {warning}")


def run_satellite(args: argparse.Namespace) -> None:
    with get_sessionmaker()() as session:
        service = SatelliteIngestionService(session=session)
        if args.satellite_command == "status":
            status = service.status()
            for line in format_satellite_status(status):
                print(line)
            return
        if args.satellite_command == "backfill":
            result = service.backfill(
                start=args.start,
                end=args.end,
                aoi_slug=args.aoi_slug or args.zone,
                force=args.force,
                dry_run=args.dry_run,
            )
            print_satellite_result(result)
            return
        if args.satellite_command == "update":
            result = service.update(aoi_slug=args.aoi_slug or args.zone, force=args.force, dry_run=args.dry_run)
            print_satellite_result(result)
            return
    fail("Unknown satellite command.")


def run_aemet(args: argparse.Namespace) -> None:
    settings = get_settings()

    station = args.station or settings.aemet_station_id
    with get_sessionmaker()() as session:
        client = None
        if args.aemet_command in {"backfill", "sync"}:
            try:
                client = AemetClient.from_settings(settings)
            except AemetConfigError as exc:
                raise SystemExit(str(exc)) from exc
        service = AemetImportService(
            session=session,
            client=client or AemetClient(base_url=settings.aemet_base_url, api_key="csv-import"),
            settings=settings,
        )
        try:
            if args.aemet_command == "backfill":
                result = service.backfill(
                    station_id=station,
                    start=args.start,
                    end=args.end,
                    block_days=args.block_days,
                )
                print_aemet_result(result)
                return
            if args.aemet_command == "sync":
                result = service.sync(
                    station_id=station,
                    lookback_days=args.lookback_days or settings.aemet_sync_lookback_days,
                )
                print_aemet_result(result)
                return
            if args.aemet_command == "import-csv":
                result = service.import_csv(station_id=station, path=args.path)
                print_aemet_result(result)
                return
        except AemetImportRangeError as exc:
            raise SystemExit(str(exc)) from exc
    fail("Unknown AEMET command.")


def run_node(args: argparse.Namespace) -> None:
    settings = get_settings()
    if args.node_command != "capture-flowmeter-minutely":
        fail("Unknown node command.")
    node_url = args.node_url or settings.argos_node_url
    if not node_url:
        fail("Missing node URL. Pass --node-url or set ARGOS_NODE_URL.")
    client = ArgosNodeClient(base_url=node_url, timeout_seconds=settings.argos_node_timeout_seconds)
    poll_seconds = args.poll_seconds or settings.argos_node_poll_interval_seconds
    print(f"Capturing flowmeter minutes from {node_url.rstrip('/')} every {poll_seconds:g}s. Press Ctrl+C to stop.")
    try:
        run_flowmeter_minute_capture(
            session_factory=get_sessionmaker(),
            client=client,
            poll_interval_seconds=poll_seconds,
            hydrological_year_reset_month=settings.argos_flowmeter_hydrological_year_reset_month,
            hydrological_year_reset_day=settings.argos_flowmeter_hydrological_year_reset_day,
        )
    except KeyboardInterrupt:
        print("Stopped flowmeter minute capture.")
    except (ArgosNodeError, ArgosNodeStatusError) as exc:
        raise SystemExit(str(exc)) from exc


def run_data(args: argparse.Namespace) -> None:
    if args.data_command == "audit-duplicates":
        with get_sessionmaker()() as session:
            results = audit_duplicates(session)
        for line in format_duplicate_results(results):
            print(line)
        if has_structural_duplicates(results):
            raise SystemExit(1)
        return
    if args.data_command == "list-ingestion-runs":
        with get_sessionmaker()() as session:
            statement = select(IngestionRun, DataSource.code).join(DataSource).order_by(
                IngestionRun.started_at_utc.desc(), IngestionRun.id.desc()
            ).limit(args.limit)
            if args.source:
                statement = statement.where(DataSource.code == args.source)
            if args.status:
                statement = statement.where(IngestionRun.status == args.status)
            for run, source_code in session.execute(statement):
                print(
                    f"{run.run_uuid} {source_code} {run.mode} {run.status} "
                    f"started={run.started_at_utc} finished={run.finished_at_utc or '-'} "
                    f"inserted={run.inserted_count} updated={run.updated_count} failed={run.failed_count}"
                )
        return
    if args.data_command == "show-ingestion-run":
        with get_sessionmaker()() as session:
            row = session.execute(
                select(IngestionRun, DataSource.code)
                .join(DataSource)
                .where(IngestionRun.run_uuid == args.run_uuid)
            ).first()
            if row is None:
                raise SystemExit("Ingestion run not found.")
            run, source_code = row
            print(f"Run: {run.run_uuid}")
            print(f"Source: {source_code}")
            print(f"Mode: {run.mode}")
            print(f"Status: {run.status}")
            print(f"Requested: {run.requested_start_utc or '-'} to {run.requested_end_utc or '-'}")
            print(f"Started: {run.started_at_utc}")
            print(f"Finished: {run.finished_at_utc or '-'}")
            print(f"Heartbeat: {run.heartbeat_at_utc or '-'}")
            print(
                "Counts: "
                f"discovered={run.discovered_count} inserted={run.inserted_count} "
                f"updated={run.updated_count} unchanged={run.unchanged_count} "
                f"skipped={run.skipped_count} rejected={run.rejected_count} "
                f"failed={run.failed_count} warnings={run.warning_count}"
            )
            print(f"Error: {run.error_summary or '-'}")
        return
    if args.data_command in {"audit-ingestion-runs", "reconcile-ingestion-runs"}:
        with get_sessionmaker()() as session:
            runs = abandoned_runs(session, older_than=timedelta(minutes=args.older_than_minutes))
            for run in runs:
                print(f"{run.run_uuid} status={run.status} heartbeat={run.heartbeat_at_utc} started={run.started_at_utc}")
            if args.data_command == "reconcile-ingestion-runs" and args.mark_interrupted:
                for run in runs:
                    mark_run_interrupted(run, reason=f"Marked interrupted by CLI after {args.older_than_minutes} minutes without heartbeat.")
                session.commit()
                print(f"Marked interrupted: {len(runs)}")
            if runs:
                raise SystemExit(2 if args.data_command == "audit-ingestion-runs" else 0)
        return
    if args.data_command == "show-sync-cursors":
        with get_sessionmaker()() as session:
            statement = select(SyncCursor, DataSource.code).join(DataSource).order_by(DataSource.code, SyncCursor.scope, SyncCursor.scope_key)
            if args.source:
                statement = statement.where(DataSource.code == args.source)
            for cursor, source_code in session.execute(statement):
                validate_cursor(cursor)
                print(
                    f"{source_code} scope={cursor.scope} key={cursor.scope_key} "
                    f"type={cursor.cursor_type} value={cursor.cursor_value_json} updated={cursor.updated_at_utc}"
                )
        return
    if args.data_command == "audit-source-artifacts":
        with get_sessionmaker()() as session:
            issues = audit_source_artifacts(session)
        for issue in issues:
            print(f"{issue.issue}: artifact_id={issue.artifact_id} path={issue.storage_path}")
        if issues:
            raise SystemExit(1)
        print("OK source_artifacts: issues=0")
        return
    if args.data_command == "audit-ecowitt-nullability":
        with get_sessionmaker()() as session:
            counts = {
                "gateway_id": session.execute(select(func.count()).select_from(WeatherObservation).where(WeatherObservation.gateway_id.is_(None))).scalar_one(),
                "observed_at_utc": session.execute(select(func.count()).select_from(WeatherObservation).where(WeatherObservation.observed_at_utc.is_(None))).scalar_one(),
                "source": session.execute(select(func.count()).select_from(WeatherObservation).where(WeatherObservation.source.is_(None))).scalar_one(),
            }
        for key, count in counts.items():
            print(f"{key}: null_rows={count}")
        if any(counts.values()):
            raise SystemExit(1)
        return
    fail("Unknown data command.")


def format_satellite_status(status) -> list[str]:
    lines = [
        f"Status: {status.status}",
        f"Enabled: {'yes' if status.enabled else 'no'}",
        f"Configured: {'yes' if status.configured else 'no'}",
        f"Credentials: {'available' if status.credentials_available else 'missing'}",
        f"Geometry: {'defined' if status.geometry_defined else 'missing'}",
        f"Latest acquisition: {status.latest_acquisition_time.isoformat() if status.latest_acquisition_time else '-'}",
        f"Latest update: {status.latest_update_time.isoformat() if status.latest_update_time else '-'}",
        f"Zones: {status.zone_count}",
        f"Observations: {status.observation_count}",
        f"Message: {status.message}",
    ]
    for aoi in status.aois or []:
        lines.append(f"AOI: {aoi.slug} · {aoi.name} · {aoi.geometry_hash} · {aoi.area_m2:.1f} m2")
    return lines


def print_satellite_result(result) -> None:
    print(f"Status: {result.status}")
    print(f"Found: {result.found_count}")
    print(f"Processed: {result.processed_count}")
    print(f"Skipped: {result.skipped_count}")
    print(f"Failed: {result.failed_count}")
    print(f"Dry run: {'yes' if result.dry_run else 'no'}")
    print(f"Processing units: {result.processing_units if result.processing_units is not None else '-'}")
    for warning in result.warnings:
        print(f"- {warning}")


def print_aemet_result(result) -> None:
    print(f"Status: {result.status}")
    print(f"Station: {result.station_external_id}")
    print(f"Range: {result.start.isoformat()} to {result.end.isoformat()}")
    print(f"Intervals queried: {len(result.intervals)}")
    print(f"Records received: {result.records_received}")
    print(f"Inserted: {result.inserted}")
    print(f"Updated: {result.updated}")
    print(f"Skipped: {result.skipped}")
    print(f"Errors: {len(result.errors)}")
    for error in result.errors:
        print(f"- {error['start']} to {error['end']}: {error['message']}")


def parse_utc_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid datetime: {value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date: {value}") from exc


def parse_callbacks(value: str) -> tuple[str, ...]:
    callbacks = tuple(callback.strip() for callback in value.split(",") if callback.strip())
    if not callbacks:
        raise argparse.ArgumentTypeError("At least one callback must be provided.")
    return callbacks


def fail(message: str) -> NoReturn:
    raise SystemExit(message)
