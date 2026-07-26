from __future__ import annotations

from datetime import UTC, datetime

import pytest

from argos.services.ecowitt_cloud_adapter import parse_cloud_history_payload


def test_parse_cloud_history_payload_extracts_nested_series_with_units() -> None:
    payload = {
        "code": 0,
        "data": {
            "outdoor": {
                "temperature": {
                    "list": [
                        {"time": "2026-07-10 12:45:00", "value": "95.18", "unit": "F"},
                        {"time": "2026-07-10 12:50:00", "value": "96.98", "unit": "F"},
                    ]
                },
                "humidity": {
                    "list": [
                        {"time": "2026-07-10 12:45:00", "value": "24", "unit": "%"},
                        {"time": "2026-07-10 12:50:00", "value": "25", "unit": "%"},
                    ]
                },
            },
            "pressure": {
                "relative": {"list": [{"time": "2026-07-10 12:45:00", "value": "29.91", "unit": "inHg"}]}
            },
            "rainfall_piezo": {
                "daily": {"list": [{"time": "2026-07-10 12:45:00", "value": "0.10", "unit": "in"}]},
                "rain_rate": {"list": [{"time": "2026-07-10 12:45:00", "value": "0.20", "unit": "in/h"}]},
            },
        },
    }

    result = parse_cloud_history_payload(payload)

    assert result.warnings == []
    assert len(result.observations) == 2
    first = result.observations[0]
    assert first.observed_at_utc == datetime(2026, 7, 10, 12, 45, tzinfo=UTC)
    assert first.normalized_values["outdoor_temperature_c"] == pytest.approx(35.1)
    assert first.normalized_values["outdoor_humidity_pct"] == pytest.approx(24.0)
    assert first.normalized_values["relative_pressure_hpa"] == pytest.approx(1012.8688502)
    assert first.normalized_values["rain_day_mm"] == pytest.approx(2.54)
    assert first.normalized_values["rain_rate_mm_h"] == pytest.approx(5.08)
    assert "temperature" in first.cloud_payload


def test_parse_cloud_history_payload_supports_flat_record_lists() -> None:
    payload = {
        "data": {
            "outdoor": [
                {
                    "time": "2026-07-10T12:45:00+00:00",
                    "tempf": 95.18,
                    "humidity": 24,
                }
            ]
        }
    }

    result = parse_cloud_history_payload(payload)

    assert len(result.observations) == 1
    assert result.observations[0].normalized_values["outdoor_humidity_pct"] == pytest.approx(24.0)
    assert any("tempf" in warning and "ambiguous" in warning for warning in result.warnings)


def test_parse_cloud_history_payload_skips_ambiguous_units() -> None:
    payload = {
        "data": {
            "outdoor": {
                "temperature": {"list": [{"time": "2026-07-10 12:45:00", "value": "35.1"}]},
            }
        }
    }

    result = parse_cloud_history_payload(payload)

    assert result.observations == []
    assert result.warnings == ["Ecowitt Cloud field temperature ignored because unit is ambiguous: None."]


def test_parse_cloud_history_payload_warns_about_unknown_fields() -> None:
    payload = {"data": {"soil": {"soilmoisture1": {"list": [{"time": "2026-07-10 12:45:00", "value": "33"}]}}}}

    result = parse_cloud_history_payload(payload)

    assert result.observations == []
    assert result.warnings == ["Unsupported Ecowitt Cloud field ignored: soilmoisture1"]
