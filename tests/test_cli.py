from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from argos.cli import build_parser, parse_callbacks, parse_utc_datetime


def test_parse_utc_datetime_accepts_z_suffix_and_naive_values() -> None:
    assert parse_utc_datetime("2026-07-10T12:45:00Z") == datetime(2026, 7, 10, 12, 45, tzinfo=UTC)
    assert parse_utc_datetime("2026-07-10 12:45:00") == datetime(2026, 7, 10, 12, 45, tzinfo=UTC)


def test_parse_callbacks_rejects_empty_values() -> None:
    assert parse_callbacks("outdoor, rainfall_piezo") == ("outdoor", "rainfall_piezo")

    with pytest.raises(argparse.ArgumentTypeError):
        parse_callbacks(" , ")


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
            "--cloud-mac",
            "AA:BB:CC:DD:EE:FF",
        ]
    )
    assert args.gateway_identifier == "GW2000A"
    assert args.cloud_mac == "AA:BB:CC:DD:EE:FF"
