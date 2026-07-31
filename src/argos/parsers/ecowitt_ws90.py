from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from argos.services.ecowitt_units import fahrenheit_to_celsius, inches_to_mm, inhg_to_hpa, mph_to_mps

PARSER_VERSION = "gw2000a-ws90-3.3.2.3"


@dataclass(frozen=True, slots=True)
class EcowittWs90ParseResult:
    observed_at_utc: datetime
    normalized_values: dict[str, float | None]
    unknown_fields: dict[str, Any]
    warnings: list[str]
    station_type: str | None
    model: str | None
    parser_version: str


@dataclass(frozen=True, slots=True)
class FieldSpec:
    target: str
    converter: Callable[[float], float]
    validator: Callable[[float, str, list[str]], float | None]


def parse_ws90_payload(payload: Mapping[str, Any], received_at_utc: datetime) -> EcowittWs90ParseResult:
    lookup = {key.lower(): (key, value) for key, value in payload.items()}
    warnings: list[str] = []

    observed_at_utc, timestamp_warning = parse_ecowitt_datetime(_lookup_value(lookup, "dateutc"), received_at_utc)
    if timestamp_warning is not None:
        warnings.append(timestamp_warning)

    values: dict[str, float | None] = {spec.target: None for spec in FIELD_MAP.values()}
    used_keys: set[str] = {"dateutc"}

    for payload_key, spec in FIELD_MAP.items():
        found = lookup.get(payload_key)
        if found is None:
            continue

        source_key, raw_value = found
        used_keys.add(source_key.lower())
        parsed = _parse_float(raw_value, source_key, warnings)
        if parsed is not None:
            parsed = spec.validator(spec.converter(parsed), source_key, warnings)
        values[spec.target] = parsed

    ignored_keys = {
        "passkey",
        "stationtype",
        "model",
        "runtime",
        "heap",
        "freq",
        "interval",
        "ws90_ver",
    }
    unknown_fields = {
        key: value
        for key, value in payload.items()
        if key.lower() not in used_keys and key.lower() not in ignored_keys
    }

    return EcowittWs90ParseResult(
        observed_at_utc=observed_at_utc,
        normalized_values=values,
        unknown_fields=unknown_fields,
        warnings=warnings,
        station_type=_optional_string(_lookup_value(lookup, "stationtype")),
        model=_optional_string(_lookup_value(lookup, "model")),
        parser_version=PARSER_VERSION,
    )


def parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_ecowitt_datetime(value: object, fallback: datetime) -> tuple[datetime, str | None]:
    if value is None or str(value).strip() == "":
        return fallback, "missing dateutc"

    raw_value = str(value).strip()
    normalized = raw_value.replace("+", " ")
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    )

    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=UTC), None
        except ValueError:
            continue

    return fallback, f"invalid dateutc: {raw_value!r}"


def _identity(value: float) -> float:
    return value


def _validate_any(value: float, _field_name: str, _warnings: list[str]) -> float:
    return value


def _validate_non_negative(value: float, field_name: str, warnings: list[str]) -> float | None:
    if value < 0:
        warnings.append(f"invalid negative value for {field_name}: {value}")
        return None
    return value


def _validate_humidity(value: float, field_name: str, warnings: list[str]) -> float | None:
    if not 0 <= value <= 100:
        warnings.append(f"humidity out of range for {field_name}: {value}")
        return None
    return value


def _validate_wind_direction(value: float, field_name: str, warnings: list[str]) -> float | None:
    if not 0 <= value <= 360:
        warnings.append(f"wind direction out of range for {field_name}: {value}")
        return None
    return value


FIELD_MAP: dict[str, FieldSpec] = {
    "tempinf": FieldSpec("indoor_temperature_c", fahrenheit_to_celsius, _validate_any),
    "humidityin": FieldSpec("indoor_humidity_pct", _identity, _validate_humidity),
    "tempf": FieldSpec("outdoor_temperature_c", fahrenheit_to_celsius, _validate_any),
    "humidity": FieldSpec("outdoor_humidity_pct", _identity, _validate_humidity),
    "dewptf": FieldSpec("dew_point_c", fahrenheit_to_celsius, _validate_any),
    "dew_point": FieldSpec("dew_point_c", fahrenheit_to_celsius, _validate_any),
    "feelslikef": FieldSpec("feels_like_c", fahrenheit_to_celsius, _validate_any),
    "feels_like": FieldSpec("feels_like_c", fahrenheit_to_celsius, _validate_any),
    "vpd": FieldSpec("vpd_kpa", _identity, _validate_non_negative),
    "baromabsin": FieldSpec("absolute_pressure_hpa", inhg_to_hpa, _validate_non_negative),
    "baromrelin": FieldSpec("relative_pressure_hpa", inhg_to_hpa, _validate_non_negative),
    "winddir": FieldSpec("wind_direction_deg", _identity, _validate_wind_direction),
    "winddir_avg10m": FieldSpec("wind_direction_avg10m_deg", _identity, _validate_wind_direction),
    "windspeedmph": FieldSpec("wind_speed_ms", mph_to_mps, _validate_non_negative),
    "windgustmph": FieldSpec("wind_gust_ms", mph_to_mps, _validate_non_negative),
    "maxdailygust": FieldSpec("daily_max_gust_ms", mph_to_mps, _validate_non_negative),
    "solarradiation": FieldSpec("solar_radiation_wm2", _identity, _validate_non_negative),
    "uv": FieldSpec("uv_index", _identity, _validate_non_negative),
    "rrain_piezo": FieldSpec("rain_rate_mm_h", inches_to_mm, _validate_non_negative),
    "erain_piezo": FieldSpec("rain_event_mm", inches_to_mm, _validate_non_negative),
    "hrain_piezo": FieldSpec("rain_hour_mm", inches_to_mm, _validate_non_negative),
    "last24hrain_piezo": FieldSpec("rain_last_24h_mm", inches_to_mm, _validate_non_negative),
    "drain_piezo": FieldSpec("rain_day_mm", inches_to_mm, _validate_non_negative),
    "wrain_piezo": FieldSpec("rain_week_mm", inches_to_mm, _validate_non_negative),
    "mrain_piezo": FieldSpec("rain_month_mm", inches_to_mm, _validate_non_negative),
    "yrain_piezo": FieldSpec("rain_year_mm", inches_to_mm, _validate_non_negative),
    "srain_piezo": FieldSpec("piezo_rain_mm", inches_to_mm, _validate_non_negative),
    "wh90batt": FieldSpec("battery_voltage", _identity, _validate_non_negative),
    "ws90cap_volt": FieldSpec("ws90_capacitor_voltage", _identity, _validate_non_negative),
}


def _lookup_value(lookup: Mapping[str, tuple[str, Any]], key: str) -> Any:
    found = lookup.get(key.lower())
    if found is None:
        return None
    return found[1]


def _parse_float(value: object, field_name: str, warnings: list[str]) -> float | None:
    parsed = parse_decimal(value)
    if parsed is None:
        if value is not None and str(value).strip() != "":
            warnings.append(f"invalid numeric value for {field_name}: {value!r}")
        return None
    return float(parsed)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
