from __future__ import annotations

import pandas as pd

from argos.dashboard.data_loader import DATETIME_COLUMN


SUMMARY_AGGREGATIONS = {
    "temperatura_exterior": ["mean", "min", "max"],
    "humedad_exterior": ["mean"],
    "lluvia_diaria": ["max"],
    "lluvia_intensidad": ["max"],
    "viento_velocidad": ["mean", "max"],
    "viento_racha": ["max"],
    "radiacion_solar": ["max"],
    "uv": ["max"],
}


def daily_summary(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    present = _present_aggregations(data, SUMMARY_AGGREGATIONS)
    if not present:
        return pd.DataFrame()
    return data.groupby(data[DATETIME_COLUMN].dt.date).agg(present).round(3)


def daily_hourly(data: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    if data.empty or not variables:
        return pd.DataFrame()
    return _resample(data, "h", variables, "mean")


def weekly_daily(data: pd.DataFrame) -> pd.DataFrame:
    return _daily_aggregates(data)


def monthly_daily(data: pd.DataFrame) -> pd.DataFrame:
    return _daily_aggregates(data)


def annual_monthly(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    variables = _numeric_variables(data)
    if not variables:
        return pd.DataFrame()
    indexed = data.set_index(DATETIME_COLUMN)
    return indexed[variables].resample("ME").agg(_variable_aggregator).round(3)


def moving_average(data: pd.DataFrame, variables: list[str], window: int) -> pd.DataFrame:
    if data.empty or not variables:
        return pd.DataFrame()
    result = data[[DATETIME_COLUMN, *variables]].copy()
    for variable in variables:
        result[f"{variable}_media_movil"] = result[variable].rolling(window=window, min_periods=1).mean()
    return result


def anomalies(data: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    if data.empty or not variables:
        return pd.DataFrame()
    result = data[[DATETIME_COLUMN, *variables]].copy()
    for variable in variables:
        result[f"{variable}_anomalia"] = result[variable] - result[variable].mean()
    return result


def linear_trend(data: pd.DataFrame, variable: str) -> pd.DataFrame:
    if data.empty or variable not in data.columns:
        return pd.DataFrame()

    frame = data[[DATETIME_COLUMN, variable]].dropna().copy()
    if len(frame) < 2:
        return pd.DataFrame()

    x = (frame[DATETIME_COLUMN] - frame[DATETIME_COLUMN].min()).dt.total_seconds()
    y = frame[variable]
    slope = ((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum()
    intercept = y.mean() - slope * x.mean()
    frame[f"{variable}_tendencia"] = intercept + slope * x
    return frame


def _daily_aggregates(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    variables = _numeric_variables(data)
    if not variables:
        return pd.DataFrame()
    indexed = data.set_index(DATETIME_COLUMN)
    return indexed[variables].resample("D").agg(_variable_aggregator).round(3)


def _resample(data: pd.DataFrame, rule: str, variables: list[str], method: str) -> pd.DataFrame:
    present = [variable for variable in variables if variable in data.columns]
    if not present:
        return pd.DataFrame()
    indexed = data.set_index(DATETIME_COLUMN)
    return getattr(indexed[present].resample(rule), method)().reset_index()


def _numeric_variables(data: pd.DataFrame) -> list[str]:
    return [
        column
        for column in data.columns
        if column != DATETIME_COLUMN and pd.api.types.is_numeric_dtype(data[column])
    ]


def _variable_aggregator(series: pd.Series):
    if series.name and "lluvia" in series.name:
        return series.max()
    if series.name in {"viento_racha", "radiacion_solar", "uv"}:
        return series.max()
    return series.mean()


def _present_aggregations(data: pd.DataFrame, aggregations: dict[str, list[str]]) -> dict[str, list[str]]:
    return {column: methods for column, methods in aggregations.items() if column in data.columns}
