from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import NoReturn

from argos.config.settings import get_settings
from argos.database.session import get_sessionmaker
from argos.integrations.ecowitt_cloud import DEFAULT_HISTORY_CALLBACKS, EcowittCloudClient, EcowittCloudConfigError
from argos.services.ecowitt_backfill import BackfillRangeError, backfill_ecowitt_cloud_range
from argos.services.ecowitt_status import EcowittStatus, build_ecowitt_status


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "ecowitt" and args.ecowitt_command == "status":
        run_ecowitt_status()
        return
    if args.command == "ecowitt-cloud" and args.ecowitt_cloud_command == "backfill":
        run_cloud_backfill(args)
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


def parse_utc_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid datetime: {value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_callbacks(value: str) -> tuple[str, ...]:
    callbacks = tuple(callback.strip() for callback in value.split(",") if callback.strip())
    if not callbacks:
        raise argparse.ArgumentTypeError("At least one callback must be provided.")
    return callbacks


def fail(message: str) -> NoReturn:
    raise SystemExit(message)
