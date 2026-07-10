from __future__ import annotations

import pandas as pd
import pytest

from argos.dashboard.trends import build_trend_frame, linear_slope


def test_linear_slope_handles_simple_sequence() -> None:
    assert linear_slope([1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert linear_slope([3.0]) is None


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
    assert trend_frame["rolling_mean"].tolist() == pytest.approx([10.0, 11.0, 13.0])
    assert trend_frame["anomaly"].tolist() == pytest.approx([-2.0, 0.0, 2.0])
