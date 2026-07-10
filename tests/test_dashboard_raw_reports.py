from __future__ import annotations

from argos.dashboard.raw_reports import build_raw_report_table, format_payload_keys, latest_payload_preview


def test_build_raw_report_table_replaces_payload_with_key_summary() -> None:
    table = build_raw_report_table(
        [
            {
                "id": 1,
                "received_at_utc": "2026-07-10T12:45:00Z",
                "payload_json": {"stationtype": "GW2000A", "PASSKEY": "<redacted>"},
            }
        ]
    )

    assert "payload_json" not in table
    assert table.loc[0, "payload_keys"] == "PASSKEY, stationtype"


def test_latest_payload_preview_returns_first_payload() -> None:
    payload = {"PASSKEY": "<redacted>", "stationtype": "GW2000A"}

    assert latest_payload_preview([{"payload_json": payload}]) == payload
    assert latest_payload_preview([]) is None


def test_format_payload_keys_handles_unexpected_payloads() -> None:
    assert format_payload_keys({"b": 1, "a": 2}) == "a, b"
    assert format_payload_keys(None) == ""
