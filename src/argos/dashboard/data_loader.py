from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


DEFAULT_WEATHER_DIR = Path("data/weather")
DATETIME_COLUMN = "fecha_hora_local"

WEATHER_COLUMNS = [
    DATETIME_COLUMN,
    "temperatura_exterior",
    "humedad_exterior",
    "presion_absoluta",
    "presion_relativa",
    "lluvia_evento",
    "lluvia_diaria",
    "lluvia_intensidad",
    "viento_velocidad",
    "viento_racha",
    "viento_direccion",
    "radiacion_solar",
    "uv",
    "bateria_ws90",
    "condensador_ws90",
]

DEFAULT_VARIABLES = [
    "temperatura_exterior",
    "humedad_exterior",
    "lluvia_diaria",
    "viento_velocidad",
    "viento_racha",
    "radiacion_solar",
    "uv",
]


@dataclass(frozen=True)
class WeatherData:
    frame: pd.DataFrame
    files: list[Path]
    missing_columns: list[str]
    messages: list[str]


def load_weather_data(data_dir: Path = DEFAULT_WEATHER_DIR) -> WeatherData:
    files = sorted(data_dir.glob("[0-9][0-9][0-9][0-9]/*.csv"))
    messages: list[str] = []
    frames: list[pd.DataFrame] = []
    missing_columns: set[str] = set()

    if not files:
        return WeatherData(
            frame=_empty_frame(),
            files=[],
            missing_columns=WEATHER_COLUMNS.copy(),
            messages=[f"No weather CSV files found under {data_dir}."],
        )

    for csv_path in files:
        try:
            frame = pd.read_csv(csv_path)
        except Exception as exc:
            messages.append(f"Could not read {csv_path}: {exc}")
            continue

        missing = [column for column in WEATHER_COLUMNS if column not in frame.columns]
        missing_columns.update(missing)
        for column in missing:
            frame[column] = pd.NA

        frame["source_file"] = str(csv_path)
        frames.append(frame[WEATHER_COLUMNS + ["source_file"]])

    if not frames:
        return WeatherData(
            frame=_empty_frame(),
            files=files,
            missing_columns=sorted(missing_columns),
            messages=messages or ["No readable weather CSV files found."],
        )

    data = pd.concat(frames, ignore_index=True)
    data[DATETIME_COLUMN] = pd.to_datetime(data[DATETIME_COLUMN], errors="coerce")
    invalid_dates = int(data[DATETIME_COLUMN].isna().sum())
    if invalid_dates:
        messages.append(f"{invalid_dates} rows have invalid {DATETIME_COLUMN} values and were ignored.")
    data = data.dropna(subset=[DATETIME_COLUMN]).sort_values(DATETIME_COLUMN)

    for column in WEATHER_COLUMNS:
        if column != DATETIME_COLUMN:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    return WeatherData(
        frame=data.reset_index(drop=True),
        files=files,
        missing_columns=sorted(missing_columns),
        messages=messages,
    )


def available_variables(data: pd.DataFrame) -> list[str]:
    return [
        column
        for column in WEATHER_COLUMNS
        if column != DATETIME_COLUMN and column in data.columns and data[column].notna().any()
    ]


def filter_by_date_range(data: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    if data.empty:
        return data
    start = pd.Timestamp(start_date).tz_localize(data[DATETIME_COLUMN].dt.tz) if data[DATETIME_COLUMN].dt.tz else pd.Timestamp(start_date)
    end = pd.Timestamp(end_date).tz_localize(data[DATETIME_COLUMN].dt.tz) if data[DATETIME_COLUMN].dt.tz else pd.Timestamp(end_date)
    end = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return data[(data[DATETIME_COLUMN] >= start) & (data[DATETIME_COLUMN] <= end)].copy()


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=WEATHER_COLUMNS + ["source_file"])
