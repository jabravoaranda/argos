from __future__ import annotations

import pandas as pd
import pytest

from argos.dashboard.period_profiles import build_hourly_profile


def test_build_hourly_profile_aggregates_numeric_variables_by_hour() -> None:
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(
                [
                    "2026-07-10T00:00:00Z",
                    "2026-07-10T00:30:00Z",
                    "2026-07-10T01:00:00Z",
                ]
            ),
            "outdoor_temperature_c": [10.0, 12.0, 16.0],
            "source": ["DIRECT", "DIRECT", "BACKFILLED"],
        }
    )

    profile = build_hourly_profile(frame, ["outdoor_temperature_c", "source"])

    assert list(profile["hour"].astype(str)) == ["2026-07-10 00:00:00+00:00", "2026-07-10 01:00:00+00:00"]
    assert list(profile["outdoor_temperature_c"]) == pytest.approx([11.0, 16.0])
    assert "source" not in profile


def test_build_hourly_profile_returns_empty_frame_without_numeric_variables() -> None:
    frame = pd.DataFrame({"observed_at_utc": pd.to_datetime(["2026-07-10T00:00:00Z"]), "source": ["DIRECT"]})

    assert build_hourly_profile(frame, ["source"]).empty
