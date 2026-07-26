from __future__ import annotations

import pandas as pd
import pytest

from argos.dashboard.statistics import build_descriptive_statistics


def test_build_descriptive_statistics_calculates_common_scientific_metrics() -> None:
    frame = pd.DataFrame({"temperature": [10.0, 20.0, 30.0, None], "humidity": [50.0, None, None, None]})

    stats = build_descriptive_statistics(frame, ["temperature", "humidity", "missing"], {"temperature": "Temperature"})

    assert list(stats["variable"]) == ["Temperature", "humidity"]
    temperature = stats.iloc[0]
    assert temperature["samples"] == 4
    assert temperature["valid"] == 3
    assert temperature["missing"] == 1
    assert temperature["missing_pct"] == pytest.approx(25.0)
    assert temperature["mean"] == pytest.approx(20.0)
    assert temperature["median"] == pytest.approx(20.0)
    assert temperature["min"] == pytest.approx(10.0)
    assert temperature["max"] == pytest.approx(30.0)
    assert temperature["range"] == pytest.approx(20.0)

    humidity = stats.iloc[1]
    assert humidity["valid"] == 1
    assert humidity["std"] == pytest.approx(0.0)


def test_build_descriptive_statistics_handles_empty_frames() -> None:
    stats = build_descriptive_statistics(pd.DataFrame({"temperature": []}), ["temperature"], {})

    assert stats.iloc[0]["samples"] == 0
    assert stats.iloc[0]["valid"] == 0
    assert stats.iloc[0]["missing_pct"] == 0.0
