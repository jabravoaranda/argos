from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class TrendSummary:
    variable: str
    sample_count: int
    mean: float | None
    slope_per_sample: float | None


def build_trend_frame(frame: pd.DataFrame, *, variable: str, rolling_window: int) -> tuple[pd.DataFrame, TrendSummary]:
    if frame.empty or variable not in frame.columns:
        return pd.DataFrame(), TrendSummary(variable=variable, sample_count=0, mean=None, slope_per_sample=None)

    trend_frame = frame[["observed_at_utc", variable]].dropna().copy()
    trend_frame = trend_frame.rename(columns={variable: "value"})
    trend_frame = trend_frame.sort_values("observed_at_utc").reset_index(drop=True)
    if trend_frame.empty:
        return trend_frame, TrendSummary(variable=variable, sample_count=0, mean=None, slope_per_sample=None)

    mean_value = float(trend_frame["value"].mean())
    trend_frame["rolling_mean"] = trend_frame["value"].rolling(window=max(1, rolling_window), min_periods=1).mean()
    trend_frame["anomaly"] = trend_frame["value"] - mean_value

    slope = linear_slope([float(value) for value in trend_frame["value"].tolist()])
    if slope is None:
        trend_frame["trend_line"] = None
    else:
        intercept = float(trend_frame["value"].iloc[0])
        trend_frame["trend_line"] = [intercept + slope * index for index in range(len(trend_frame))]

    return trend_frame, TrendSummary(
        variable=variable,
        sample_count=len(trend_frame),
        mean=mean_value,
        slope_per_sample=slope,
    )


def linear_slope(values: list[float]) -> float | None:
    if len(values) < 2:
        return None

    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(n))
    if denominator == 0:
        return None
    return numerator / denominator
