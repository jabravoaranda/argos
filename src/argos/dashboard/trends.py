from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd


@dataclass(frozen=True, slots=True)
class TrendSummary:
    variable: str
    sample_count: int
    mean: float | None
    slope_per_sample: float | None
    slope_per_day: float | None
    r_squared: float | None
    estimated_change: float | None


def build_trend_frame(frame: pd.DataFrame, *, variable: str, rolling_window: int) -> tuple[pd.DataFrame, TrendSummary]:
    if frame.empty or variable not in frame.columns:
        return pd.DataFrame(), empty_trend_summary(variable)

    trend_frame = frame[["observed_at_utc", variable]].dropna().copy()
    trend_frame = trend_frame.rename(columns={variable: "value"})
    trend_frame = trend_frame.sort_values("observed_at_utc").reset_index(drop=True)
    if trend_frame.empty:
        return trend_frame, empty_trend_summary(variable)

    mean_value = float(trend_frame["value"].mean())
    trend_frame["rolling_mean"] = trend_frame["value"].rolling(window=max(1, rolling_window), min_periods=1).mean()
    trend_frame["anomaly"] = trend_frame["value"] - mean_value

    values = [float(value) for value in trend_frame["value"].tolist()]
    regression = linear_regression(values)
    if regression is None:
        trend_frame["trend_line"] = None
        slope_per_sample = None
        r_squared = None
        estimated_change = None
    else:
        slope_per_sample, intercept, r_squared = regression
        trend_frame["trend_line"] = [intercept + slope_per_sample * index for index in range(len(trend_frame))]
        estimated_change = trend_frame["trend_line"].iloc[-1] - trend_frame["trend_line"].iloc[0]

    slope_per_day = estimate_slope_per_day(trend_frame, slope_per_sample)

    return trend_frame, TrendSummary(
        variable=variable,
        sample_count=len(trend_frame),
        mean=mean_value,
        slope_per_sample=slope_per_sample,
        slope_per_day=slope_per_day,
        r_squared=r_squared,
        estimated_change=float(estimated_change) if estimated_change is not None else None,
    )


def linear_slope(values: list[float]) -> float | None:
    regression = linear_regression(values)
    if regression is None:
        return None
    return regression[0]


def linear_regression(values: list[float]) -> tuple[float, float, float] | None:
    if len(values) < 2:
        return None

    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(n))
    if denominator == 0:
        return None
    slope = numerator / denominator
    intercept = y_mean - slope * x_mean
    predicted = [intercept + slope * index for index in range(n)]
    total_sum_squares = sum((value - y_mean) ** 2 for value in values)
    residual_sum_squares = sum((value - predicted_value) ** 2 for value, predicted_value in zip(values, predicted, strict=True))
    r_squared = 1.0 if total_sum_squares == 0 else 1.0 - residual_sum_squares / total_sum_squares
    return slope, intercept, r_squared


def estimate_slope_per_day(trend_frame: pd.DataFrame, slope_per_sample: float | None) -> float | None:
    if slope_per_sample is None or len(trend_frame) < 2:
        return None
    elapsed = trend_frame["observed_at_utc"].iloc[-1] - trend_frame["observed_at_utc"].iloc[0]
    if not isinstance(elapsed, timedelta) or elapsed.total_seconds() <= 0:
        return None
    samples_per_day = (len(trend_frame) - 1) / (elapsed.total_seconds() / 86400.0)
    return slope_per_sample * samples_per_day


def empty_trend_summary(variable: str) -> TrendSummary:
    return TrendSummary(
        variable=variable,
        sample_count=0,
        mean=None,
        slope_per_sample=None,
        slope_per_day=None,
        r_squared=None,
        estimated_change=None,
    )
