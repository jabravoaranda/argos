from __future__ import annotations

import pandas as pd
import pytest

from argos.dashboard.summaries import build_annual_summary, build_monthly_summary


def test_build_monthly_summary_aggregates_daily_statistics() -> None:
    daily = pd.DataFrame.from_records(
        [
            {
                "period_start": "2026-07-10",
                "period_end": "2026-07-10",
                "sample_count": 10,
                "outdoor_temperature_mean_c": 20.0,
                "outdoor_temperature_min_c": 15.0,
                "outdoor_temperature_max_c": 25.0,
                "rain_day_max_mm": 1.5,
                "wind_gust_max_ms": 4.0,
            },
            {
                "period_start": "2026-07-11",
                "period_end": "2026-07-11",
                "sample_count": 30,
                "outdoor_temperature_mean_c": 24.0,
                "outdoor_temperature_min_c": 17.0,
                "outdoor_temperature_max_c": 28.0,
                "rain_day_max_mm": 2.5,
                "wind_gust_max_ms": 6.0,
            },
        ]
    )

    monthly = build_monthly_summary(daily)

    assert len(monthly) == 1
    row = monthly.iloc[0]
    assert str(row["period_start"]) == "2026-07-01"
    assert str(row["period_end"]) == "2026-07-11"
    assert row["sample_count"] == 40
    assert row["outdoor_temperature_mean_c"] == pytest.approx(23.0)
    assert row["outdoor_temperature_min_c"] == 15.0
    assert row["outdoor_temperature_max_c"] == 28.0
    assert row["rain_day_max_mm"] == pytest.approx(4.0)
    assert row["wind_gust_max_ms"] == 6.0


def test_build_annual_summary_groups_by_year() -> None:
    daily = pd.DataFrame.from_records(
        [
            {"period_start": "2026-12-31", "sample_count": 1, "rain_day_max_mm": 3.0},
            {"period_start": "2027-01-01", "sample_count": 1, "rain_day_max_mm": 4.0},
        ]
    )

    annual = build_annual_summary(daily)

    assert list(annual["period_start"].astype(str)) == ["2026-01-01", "2027-01-01"]
    assert list(annual["rain_day_max_mm"]) == [3.0, 4.0]


def test_build_monthly_summary_returns_empty_frame_without_daily_data() -> None:
    assert build_monthly_summary(pd.DataFrame()).empty
