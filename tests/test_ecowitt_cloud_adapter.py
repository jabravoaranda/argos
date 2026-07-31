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
    assert "outdoor.temperature" in first.cloud_payload


def test_parse_cloud_history_payload_extracts_ecowitt_dict_series() -> None:
    payload = {
        "data": {
            "outdoor": {
                "temperature": {"unit": "ºF", "list": {"1784930400": "84.9"}},
                "humidity": {"unit": "%", "list": {"1784930400": "47"}},
            },
            "solar_and_uvi": {
                "solar": {"unit": "W/m²", "list": {"1784930400": "531.2"}},
                "uvi": {"unit": "", "list": {"1784930400": "4"}},
            },
            "rainfall_piezo": {
                "rain_rate": {"unit": "in/hr", "list": {"1784930400": "0.03"}},
            },
            "wind": {
                "wind_speed": {"unit": "mph", "list": {"1784930400": "6.9"}},
                "wind_gust": {"unit": "mph", "list": {"1784930400": "10.3"}},
                "wind_direction": {"unit": "º", "list": {"1784930400": "202"}},
            },
            "pressure": {
                "relative": {"unit": "inHg", "list": {"1784930400": "29.86"}},
            },
            "battery": {
                "haptic_array_battery": {"unit": "V", "list": {"1784930400": "2.84"}},
            },
        }
    }

    result = parse_cloud_history_payload(payload)

    assert result.warnings == []
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.observed_at_utc == datetime.fromtimestamp(1784930400, tz=UTC)
    assert observation.normalized_values["outdoor_temperature_c"] == pytest.approx(29.3888889)
    assert observation.normalized_values["outdoor_humidity_pct"] == pytest.approx(47.0)
    assert observation.normalized_values["solar_radiation_wm2"] == pytest.approx(531.2)
    assert observation.normalized_values["uv_index"] == pytest.approx(4.0)
    assert observation.normalized_values["rain_rate_mm_h"] == pytest.approx(0.762)
    assert observation.normalized_values["wind_speed_ms"] == pytest.approx(3.084576)
    assert observation.normalized_values["wind_gust_ms"] == pytest.approx(4.604512)
    assert observation.normalized_values["wind_direction_deg"] == pytest.approx(202.0)
    assert observation.normalized_values["relative_pressure_hpa"] == pytest.approx(1011.1754212)
    assert observation.normalized_values["battery_voltage"] == pytest.approx(2.84)


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
    assert result.warnings == ["Ecowitt Cloud field outdoor.temperature ignored because unit is ambiguous: None."]


def test_parse_cloud_history_payload_warns_about_unknown_fields() -> None:
    payload = {"data": {"soil": {"soilmoisture1": {"list": [{"time": "2026-07-10 12:45:00", "value": "33"}]}}}}

    result = parse_cloud_history_payload(payload)

    assert result.observations == []
    assert result.warnings == ["Unsupported Ecowitt Cloud field ignored: soil.soilmoisture1"]
