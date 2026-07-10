from __future__ import annotations

import pandas as pd
import pytest

from argos.dashboard.trends import build_trend_frame, linear_regression, linear_slope


def test_linear_slope_handles_simple_sequence() -> None:
    assert linear_slope([1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert linear_slope([3.0]) is None


def test_linear_regression_returns_slope_intercept_and_r_squared() -> None:
    regression = linear_regression([2.0, 4.0, 6.0])

    assert regression is not None
    slope, intercept, r_squared = regression
    assert slope == pytest.approx(2.0)
    assert intercept == pytest.approx(2.0)
    assert r_squared == pytest.approx(1.0)


def test_build_trend_frame_calculates_rolling_mean_and_anomaly() -> None:
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(["2026-07-10T00:00:00Z", "2026-07-10T00:01:00Z", "2026-07-10T00:02:00Z"]),
            "outdoor_temperature_c": [10.0, 12.0, 14.0],
        }
    )

    trend_frame, summary = build_trend_frame(frame, variable="outdoor_temperature_c", rolling_window=2)

    assert summary.sample_count == 3
    assert summary.mean == pytest.approx(12.0)
    assert summary.slope_per_sample == pytest.approx(2.0)
    assert summary.slope_per_day == pytest.approx(2880.0)
    assert summary.r_squared == pytest.approx(1.0)
    assert summary.estimated_change == pytest.approx(4.0)
    assert trend_frame["rolling_mean"].tolist() == pytest.approx([10.0, 11.0, 13.0])
    assert trend_frame["anomaly"].tolist() == pytest.approx([-2.0, 0.0, 2.0])
    assert trend_frame["trend_line"].tolist() == pytest.approx([10.0, 12.0, 14.0])
