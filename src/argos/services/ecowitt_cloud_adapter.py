from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from argos.services.ecowitt_units import fahrenheit_to_celsius, inches_to_mm, inhg_to_hpa, mph_to_mps


@dataclass(frozen=True, slots=True)
class CloudHistoryObservation:
    observed_at_utc: datetime
    normalized_values: dict[str, float | None]
    cloud_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CloudHistoryParseResult:
    observations: list[CloudHistoryObservation]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class CloudFieldMapping:
    normalized_name: str
    unit_kind: str


FIELD_MAPPINGS: dict[str, CloudFieldMapping] = {
    "tempf": CloudFieldMapping("outdoor_temperature_c", "temperature"),
    "temperature": CloudFieldMapping("outdoor_temperature_c", "temperature"),
    "humidity": CloudFieldMapping("outdoor_humidity_pct", "percent"),
    "baromabsin": CloudFieldMapping("absolute_pressure_hpa", "pressure"),
    "absolute": CloudFieldMapping("absolute_pressure_hpa", "pressure"),
    "baromrelin": CloudFieldMapping("relative_pressure_hpa", "pressure"),
    "relative": CloudFieldMapping("relative_pressure_hpa", "pressure"),
    "winddir": CloudFieldMapping("wind_direction_deg", "degree"),
    "winddir_avg10m": CloudFieldMapping("wind_direction_avg10m_deg", "degree"),
    "windspeedmph": CloudFieldMapping("wind_speed_ms", "speed"),
    "windgustmph": CloudFieldMapping("wind_gust_ms", "speed"),
    "maxdailygust": CloudFieldMapping("daily_max_gust_ms", "speed"),
    "solarradiation": CloudFieldMapping("solar_radiation_wm2", "solar"),
    "solar": CloudFieldMapping("solar_radiation_wm2", "solar"),
    "uv": CloudFieldMapping("uv_index", "plain"),
    "rrain_piezo": CloudFieldMapping("rain_rate_mm_h", "rain_rate"),
    "rain_rate": CloudFieldMapping("rain_rate_mm_h", "rain_rate"),
    "erain_piezo": CloudFieldMapping("rain_event_mm", "rain"),
    "event": CloudFieldMapping("rain_event_mm", "rain"),
    "hrain_piezo": CloudFieldMapping("rain_hour_mm", "rain"),
    "hourly": CloudFieldMapping("rain_hour_mm", "rain"),
    "last24hrain_piezo": CloudFieldMapping("rain_last_24h_mm", "rain"),
    "last_24h": CloudFieldMapping("rain_last_24h_mm", "rain"),
    "drain_piezo": CloudFieldMapping("rain_day_mm", "rain"),
    "daily": CloudFieldMapping("rain_day_mm", "rain"),
    "wrain_piezo": CloudFieldMapping("rain_week_mm", "rain"),
    "weekly": CloudFieldMapping("rain_week_mm", "rain"),
    "mrain_piezo": CloudFieldMapping("rain_month_mm", "rain"),
    "monthly": CloudFieldMapping("rain_month_mm", "rain"),
    "yrain_piezo": CloudFieldMapping("rain_year_mm", "rain"),
    "yearly": CloudFieldMapping("rain_year_mm", "rain"),
    "srain_piezo": CloudFieldMapping("piezo_rain_mm", "rain"),
}

TIME_KEYS = ("time", "datetime", "date", "dateutc", "timestamp")
VALUE_KEYS = ("value", "val")
UNIT_KEYS = ("unit", "unitid")


def parse_cloud_history_payload(payload: Mapping[str, Any]) -> CloudHistoryParseResult:
    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        return CloudHistoryParseResult(observations=[], warnings=["Ecowitt Cloud history payload data must be an object."])

    records: dict[datetime, dict[str, Any]] = defaultdict(dict)
    normalized: dict[datetime, dict[str, float | None]] = defaultdict(dict)
    warnings: list[str] = []

    for field_name, entry in _iter_field_entries(data):
        mapping = FIELD_MAPPINGS.get(_normalize_field_name(field_name))
        if mapping is None:
            warnings.append(f"Unsupported Ecowitt Cloud field ignored: {field_name}")
            continue

        observed_at = _parse_entry_time(entry)
        if observed_at is None:
            warnings.append(f"Ecowitt Cloud field {field_name} ignored because it has no parseable timestamp.")
            continue

        raw_value = _extract_entry_value(entry)
        value = _parse_float(raw_value)
        if value is None:
            warnings.append(f"Ecowitt Cloud field {field_name} ignored because value is not numeric: {raw_value!r}.")
            continue

        unit = _extract_entry_unit(entry)
        converted = _convert_value(value, unit=unit, unit_kind=mapping.unit_kind)
        if converted is None:
            warnings.append(f"Ecowitt Cloud field {field_name} ignored because unit is ambiguous: {unit!r}.")
            continue

        normalized[observed_at][mapping.normalized_name] = converted
        records[observed_at][field_name] = dict(entry)

    observations = [
        CloudHistoryObservation(
            observed_at_utc=observed_at,
            normalized_values=values,
            cloud_payload=records[observed_at],
        )
        for observed_at, values in sorted(normalized.items())
    ]
    return CloudHistoryParseResult(observations=observations, warnings=warnings)


def _iter_field_entries(data: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    entries: list[tuple[str, Mapping[str, Any]]] = []
    for group_value in data.values():
        if isinstance(group_value, Mapping):
            for field_name, field_value in group_value.items():
                entries.extend((field_name, entry) for entry in _coerce_entries(field_value))
        elif isinstance(group_value, list):
            for record in group_value:
                if isinstance(record, Mapping):
                    for field_name, field_value in record.items():
                        if field_name in TIME_KEYS:
                            continue
                        entry = {"value": field_value}
                        for time_key in TIME_KEYS:
                            if time_key in record:
                                entry[time_key] = record[time_key]
                        entries.append((field_name, entry))
    return entries


def _coerce_entries(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, Mapping)]
    if isinstance(value, Mapping):
        nested_list = value.get("list")
        if isinstance(nested_list, list):
            return [entry for entry in nested_list if isinstance(entry, Mapping)]
        if any(key in value for key in TIME_KEYS) and any(key in value for key in VALUE_KEYS):
            return [value]
    return []


def _parse_entry_time(entry: Mapping[str, Any]) -> datetime | None:
    for key in TIME_KEYS:
        raw_value = entry.get(key)
        if raw_value is None:
            continue
        if isinstance(raw_value, int | float):
            return datetime.fromtimestamp(raw_value, tz=UTC)
        if isinstance(raw_value, str):
            normalized = raw_value.strip().replace("Z", "+00:00")
            for candidate in (normalized, normalized.replace(" ", "T")):
                try:
                    parsed = datetime.fromisoformat(candidate)
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC)
    return None


def _extract_entry_value(entry: Mapping[str, Any]) -> Any:
    for key in VALUE_KEYS:
        if key in entry:
            return entry[key]
    return None


def _extract_entry_unit(entry: Mapping[str, Any]) -> str | None:
    for key in UNIT_KEYS:
        raw_unit = entry.get(key)
        if raw_unit is not None:
            return str(raw_unit).strip()
    return None


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _convert_value(value: float, *, unit: str | None, unit_kind: str) -> float | None:
    unit_key = _normalize_unit(unit)
    if unit_kind == "temperature":
        if unit_key in {"f", "fahrenheit", "degf"}:
            return fahrenheit_to_celsius(value)
        if unit_key in {"c", "celsius", "degc"}:
            return value
        return None
    if unit_kind == "pressure":
        if unit_key in {"inhg", "in"}:
            return inhg_to_hpa(value)
        if unit_key in {"hpa", "mbar"}:
            return value
        return None
    if unit_kind == "speed":
        if unit_key in {"mph"}:
            return mph_to_mps(value)
        if unit_key in {"m/s", "ms", "mps"}:
            return value
        if unit_key in {"km/h", "kmh"}:
            return value / 3.6
        return None
    if unit_kind == "rain":
        if unit_key in {"in", "inch", "inches"}:
            return inches_to_mm(value)
        if unit_key in {"mm"}:
            return value
        return None
    if unit_kind == "rain_rate":
        if unit_key in {"in/h", "inch/h", "inches/h"}:
            return inches_to_mm(value)
        if unit_key in {"mm/h", "mmh"}:
            return value
        return None
    if unit_kind in {"percent", "degree", "solar", "plain"}:
        return value
    return None


def _normalize_field_name(field_name: str) -> str:
    return field_name.strip().lower()


def _normalize_unit(unit: str | None) -> str:
    if unit is None:
        return ""
    return unit.strip().lower().replace("°", "").replace(" ", "")
