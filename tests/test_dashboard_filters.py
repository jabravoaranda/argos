from __future__ import annotations

import pandas as pd

from argos.dashboard.filters import filter_observations_by_source, observation_source_counts


def test_filter_observations_by_source_keeps_selected_sources() -> None:
    frame = pd.DataFrame(
        {
            "source": ["DIRECT", "BACKFILLED", "DIRECT"],
            "outdoor_temperature_c": [10.0, 11.0, 12.0],
        }
    )

    filtered = filter_observations_by_source(frame, ["BACKFILLED"])

    assert filtered["source"].tolist() == ["BACKFILLED"]
    assert filtered["outdoor_temperature_c"].tolist() == [11.0]


def test_filter_observations_by_source_is_noop_when_source_missing() -> None:
    frame = pd.DataFrame({"outdoor_temperature_c": [10.0]})

    filtered = filter_observations_by_source(frame, ["BACKFILLED"])

    assert filtered.equals(frame)


def test_observation_source_counts_handles_unknown_and_missing_source() -> None:
    frame = pd.DataFrame({"source": ["DIRECT", "BACKFILLED", "DIRECT", None]})

    assert observation_source_counts(frame) == {"BACKFILLED": 1, "DIRECT": 2, "UNKNOWN": 1}
    assert observation_source_counts(pd.DataFrame({"value": [1]})) == {}
