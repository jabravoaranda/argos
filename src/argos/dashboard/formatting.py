from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd


SPANISH_MONTH_ABBR = {
    1: "ene",
    2: "feb",
    3: "mar",
    4: "abr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "ago",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dic",
}


def format_file_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "tamaño desconocido"
    if size_bytes < 1024 * 1024:
        return f"{max(size_bytes / 1024, 0.1):.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_number(value: Any, unit: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        suffix = f" {unit}" if unit else ""
        return f"{value:.2f}{suffix}"
    return str(value)


def format_integer(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return f"{value:d}"
    if isinstance(value, float):
        return f"{value:.0f}"
    return str(value)


def format_binary_signal(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return "1" if int(value) == 1 else "0"
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "on", "high"}:
        return "1"
    if normalized in {"false", "0", "off", "low"}:
        return "0"
    return str(value)


def format_wind_direction(value: Any) -> str:
    if value is None:
        return "-"
    if not isinstance(value, int | float):
        return str(value)

    normalized = value % 360
    compass_points = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    compass = compass_points[int((normalized + 11.25) // 22.5) % len(compass_points)]
    return f"{normalized:.0f} deg · {compass}"


def format_datetime(value: Any) -> str:
    if not value:
        return "-"
    return str(value).replace("T", " ").replace("Z", " UTC")


def format_local_datetime(value: Any) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return "-"
    local = parsed.astimezone()
    month = SPANISH_MONTH_ABBR[local.month]
    return f"{local.day} {month} {local.year} · {local:%H:%M}"


def format_compact_local_datetime(value: Any) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return "-"
    local = parsed.astimezone()
    month = SPANISH_MONTH_ABBR[local.month]
    return f"{local.day} {month} {local.year}, {local:%H:%M}"


def format_compact_date_range(start: str, end: str) -> str:
    return f"{format_compact_date(start)}–{format_compact_date(end)}"


def format_compact_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {SPANISH_MONTH_ABBR[parsed.month]} {parsed.year}"


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, pd.Timestamp):
        parsed = value.to_pydatetime()
    elif isinstance(value, datetime):
        parsed = value
    elif value:
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def format_float(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        return f"{value:.3f}"
    return str(value)


def format_percent(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        return f"{value * 100:.0f}%"
    return str(value)


def format_binary_ev_state(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    if isinstance(value, bool):
        return "Abierta (1)" if value else "Cerrada (0)"
    if isinstance(value, int | float):
        return "Abierta (1)" if int(value) == 1 else "Cerrada (0)"
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "open", "opened", "on"}:
        return "Abierta (1)"
    if normalized in {"false", "0", "closed", "close", "off"}:
        return "Cerrada (0)"
    return str(value)


def format_percent_100(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        return f"{value:.0f}%"
    return str(value)


def short_identifier(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    if len(text) <= 12:
        return text
    return f"{text[:8]}...{text[-4:]}"
