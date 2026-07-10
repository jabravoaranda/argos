from __future__ import annotations

from typing import Any

import pandas as pd


WEIGHTED_MEAN_COLUMNS = (
    "outdoor_temperature_mean_c",
    "outdoor_humidity_mean_pct",
    "relative_pressure_mean_hpa",
)

SUM_COLUMNS = ("sample_count", "rain_day_max_mm")

MIN_COLUMNS = ("outdoor_temperature_min_c",)

MAX_COLUMNS = (
    "outdoor_temperature_max_c",
    "wind_gust_max_ms",
    "solar_radiation_max_wm2",
    "uv_index_max",
    "rain_event_max_mm",
    "rain_last_24h_max_mm",
)


def build_monthly_summary(daily_df: pd.DataFrame) -> pd.DataFrame:
    return _build_period_summary(daily_df, period="M")


def build_annual_summary(daily_df: pd.DataFrame) -> pd.DataFrame:
    return _build_period_summary(daily_df, period="Y")


def build_seasonal_summary(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df.empty or "period_start" not in daily_df:
        return pd.DataFrame()

    frame = daily_df.copy()
    frame["period_start"] = pd.to_datetime(frame["period_start"])
    frame["season"] = frame["period_start"].map(meteorological_season)
    frame["season_year"] = frame["period_start"].map(meteorological_season_year)
    rows = [
        _summarize_season_group(season_year=season_year, season=season, group=group)
        for (season_year, season), group in frame.groupby(["season_year", "season"], sort=True)
    ]
    if not rows:
        return pd.DataFrame()
    columns = ["period_label", "season_year", "season"] + [
        column for column in rows[0] if column not in {"period_label", "season_year", "season"}
    ]
    return pd.DataFrame.from_records(rows)[columns]


def _build_period_summary(daily_df: pd.DataFrame, *, period: str) -> pd.DataFrame:
    if daily_df.empty or "period_start" not in daily_df:
        return pd.DataFrame()

    frame = daily_df.copy()
    frame["period_start"] = pd.to_datetime(frame["period_start"])
    frame["period"] = frame["period_start"].dt.to_period(period)

    rows = [_summarize_group(period_value, group) for period_value, group in frame.groupby("period", sort=True)]
    return pd.DataFrame.from_records(rows)


def _summarize_group(period_value: Any, group: pd.DataFrame) -> dict[str, Any]:
    period_start = period_value.start_time.date()
    period_end = min(period_value.end_time.date(), group["period_start"].max().date())
    row: dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
    }

    for column in SUM_COLUMNS:
        if column in group:
            row[column] = group[column].sum(skipna=True)

    for column in MIN_COLUMNS:
        if column in group:
            row[column] = group[column].min(skipna=True)

    for column in MAX_COLUMNS:
        if column in group:
            row[column] = group[column].max(skipna=True)

    for column in WEIGHTED_MEAN_COLUMNS:
        if column in group:
            row[column] = _weighted_mean(group, column)

    return row


def _summarize_season_group(*, season_year: Any, season: Any, group: pd.DataFrame) -> dict[str, Any]:
    year = int(str(season_year))
    season_label = str(season)
    return {
        **_summarize_group(_SeasonPeriod(group), group),
        "season_year": year,
        "season": season_label,
        "period_label": f"{year} {season_label}",
    }


def _weighted_mean(group: pd.DataFrame, column: str) -> float | None:
    values = group[[column, "sample_count"]].dropna() if "sample_count" in group else group[[column]].dropna()
    if values.empty:
        return None
    if "sample_count" not in values:
        return float(values[column].mean())

    weights = values["sample_count"]
    if weights.sum() == 0:
        return None
    return float((values[column] * weights).sum() / weights.sum())


def meteorological_season(value: pd.Timestamp) -> str:
    month = value.month
    if month in (12, 1, 2):
        return "DJF"
    if month in (3, 4, 5):
        return "MAM"
    if month in (6, 7, 8):
        return "JJA"
    return "SON"


def meteorological_season_year(value: pd.Timestamp) -> int:
    if value.month == 12:
        return int(value.year + 1)
    return int(value.year)


class _SeasonPeriod:
    def __init__(self, group: pd.DataFrame) -> None:
        self.start_time = group["period_start"].min()
        self.end_time = group["period_start"].max()
