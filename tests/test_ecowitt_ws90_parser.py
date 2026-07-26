from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qsl

import pytest

from argos.parsers.ecowitt_ws90 import parse_decimal, parse_ecowitt_datetime, parse_ws90_payload


def test_parse_ws90_real_payload_fields() -> None:
    raw_body = (
        "PASSKEY=secret&stationtype=GW2000A_V3.3.2&dateutc=2026-07-10+12%3A45%3A26"
        "&tempinf=91.40&humidityin=23&baromrelin=29.297&baromabsin=29.297"
        "&tempf=95.18&humidity=19&vpd=1.352&winddir=345&winddir_avg10m=135"
        "&windspeedmph=2.01&windgustmph=3.13&maxdailygust=10.29&solarradiation=861.33&uv=8"
        "&rrain_piezo=0.000&erain_piezo=0.000&hrain_piezo=0.000&last24hrain_piezo=0.000"
        "&drain_piezo=0.000&wrain_piezo=0.024&mrain_piezo=0.024&yrain_piezo=0.024"
        "&srain_piezo=0&ws90cap_volt=5.3&ws90_ver=160&wh90batt=3.02&freq=868M&model=GW2000A&interval=60"
    )
    payload = dict(parse_qsl(raw_body, keep_blank_values=True))

    result = parse_ws90_payload(payload, datetime(2026, 7, 10, 12, 46, tzinfo=UTC))

    assert result.observed_at_utc == datetime(2026, 7, 10, 12, 45, 26, tzinfo=UTC)
    assert result.station_type == "GW2000A_V3.3.2"
    assert result.model == "GW2000A"
    assert result.normalized_values["outdoor_temperature_c"] == pytest.approx(35.1)
    assert result.normalized_values["indoor_temperature_c"] == pytest.approx(33.0)
    assert result.normalized_values["relative_pressure_hpa"] == pytest.approx(992.119, rel=1e-5)
    assert result.normalized_values["wind_speed_ms"] == pytest.approx(0.8985504)
    assert result.normalized_values["wind_direction_avg10m_deg"] == pytest.approx(135)
    assert result.normalized_values["rain_last_24h_mm"] == pytest.approx(0.0)
    assert result.normalized_values["rain_week_mm"] == pytest.approx(0.6096)
    assert result.normalized_values["piezo_rain_mm"] == pytest.approx(0.0)
    assert result.normalized_values["battery_voltage"] == pytest.approx(3.02)
    assert result.normalized_values["ws90_capacitor_voltage"] == pytest.approx(5.3)
    assert result.unknown_fields == {}
    assert result.warnings == []


def test_parser_helpers_are_fail_safe() -> None:
    fallback = datetime(2026, 7, 10, 12, 46, tzinfo=UTC)

    assert parse_decimal("") is None
    assert parse_decimal("bad") is None
    parsed_at, warning = parse_ecowitt_datetime("not-a-date", fallback)
    assert parsed_at == fallback
    assert warning == "invalid dateutc: 'not-a-date'"


def test_parser_records_invalid_values_as_warnings() -> None:
    result = parse_ws90_payload(
        {"dateutc": "2026-07-10 12:45:26", "humidity": "101", "winddir": "999", "tempf": "bad"},
        datetime(2026, 7, 10, 12, 46, tzinfo=UTC),
    )

    assert result.normalized_values["outdoor_humidity_pct"] is None
    assert result.normalized_values["wind_direction_deg"] is None
    assert result.normalized_values["outdoor_temperature_c"] is None
    assert "humidity out of range for humidity: 101.0" in result.warnings
    assert "wind direction out of range for winddir: 999.0" in result.warnings
    assert "invalid numeric value for tempf: 'bad'" in result.warnings
