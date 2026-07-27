from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedAemetDailyObservation:
    observation_date: date
    temperature_mean_c: float | None
    temperature_min_c: float | None
    temperature_max_c: float | None
    precipitation_mm: float | None
    precipitation_trace: bool
    wind_speed_mean_ms: float | None
    wind_gust_ms: float | None
    wind_gust_direction: str | None
    sunshine_hours: float | None
    pressure_max_hpa: float | None
    pressure_min_hpa: float | None
    humidity_mean_pct: float | None
    humidity_min_pct: float | None
    humidity_max_pct: float | None
    quality_flag: str | None
    raw_payload_json: dict[str, Any]


def normalize_aemet_daily_record(record: dict[str, Any]) -> NormalizedAemetDailyObservation:
    precipitation_raw = record.get("prec")
    return NormalizedAemetDailyObservation(
        observation_date=_parse_date(record.get("fecha")),
        temperature_mean_c=_parse_decimal(record.get("tmed")),
        temperature_min_c=_parse_decimal(record.get("tmin")),
        temperature_max_c=_parse_decimal(record.get("tmax")),
        precipitation_mm=_parse_precipitation(precipitation_raw),
        precipitation_trace=_is_precipitation_trace(precipitation_raw),
        wind_speed_mean_ms=_parse_decimal(record.get("velmedia")),
        wind_gust_ms=_parse_decimal(record.get("racha")),
        wind_gust_direction=_parse_string(record.get("dir")),
        sunshine_hours=_parse_decimal(record.get("sol")),
        pressure_max_hpa=_parse_decimal(record.get("presMax")),
        pressure_min_hpa=_parse_decimal(record.get("presMin")),
        humidity_mean_pct=_parse_decimal(record.get("hrMedia")),
        humidity_min_pct=_parse_decimal(record.get("hrMin")),
        humidity_max_pct=_parse_decimal(record.get("hrMax")),
        quality_flag=_quality_flag(record),
        raw_payload_json=dict(record),
    )


def normalize_aemet_daily_records(records: list[dict[str, Any]]) -> list[NormalizedAemetDailyObservation]:
    return [normalize_aemet_daily_record(record) for record in records]


def _parse_date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("AEMET daily record is missing fecha.")
    return date.fromisoformat(value.strip())


def _parse_decimal(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized == "" or normalized.upper() in {"N/A", "NULL"}:
        return None
    try:
        return float(normalized.replace(",", "."))
    except ValueError:
        return None


def _parse_precipitation(value: Any) -> float | None:
    if _is_precipitation_trace(value):
        return None
    return _parse_decimal(value)


def _is_precipitation_trace(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() == "ip"


def _parse_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _quality_flag(record: dict[str, Any]) -> str | None:
    for key in ("indicador", "incidencia", "incidencias", "quality_flag"):
        value = _parse_string(record.get(key))
        if value is not None:
            return value
    return None
