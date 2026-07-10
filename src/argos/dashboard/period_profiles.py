from __future__ import annotations

import pandas as pd


def build_hourly_profile(frame: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    if frame.empty or "observed_at_utc" not in frame:
        return pd.DataFrame()

    available_variables = [
        variable
        for variable in variables
        if variable in frame.columns and pd.api.types.is_numeric_dtype(frame[variable])
    ]
    if not available_variables:
        return pd.DataFrame()

    profile = frame[["observed_at_utc", *available_variables]].copy()
    profile["hour"] = pd.to_datetime(profile["observed_at_utc"]).dt.floor("h")
    return (
        profile.groupby("hour", as_index=False)[available_variables]
        .mean(numeric_only=True)
        .sort_values("hour")
        .reset_index(drop=True)
    )


def build_rain_accumulation(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "observed_at_utc" not in frame or "rain_day_mm" not in frame:
        return pd.DataFrame()

    rain = frame[["observed_at_utc", "rain_day_mm"]].copy()
    rain["observed_at_utc"] = pd.to_datetime(rain["observed_at_utc"])
    rain["rain_day_mm"] = pd.to_numeric(rain["rain_day_mm"], errors="coerce")
    return rain.dropna().sort_values("observed_at_utc").reset_index(drop=True)
