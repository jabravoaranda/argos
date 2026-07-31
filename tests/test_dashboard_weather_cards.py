from __future__ import annotations

from argos.dashboard.app import format_wind_direction


def test_format_wind_direction_adds_compass_label() -> None:
    assert format_wind_direction(0) == "0 deg · N"
    assert format_wind_direction(196) == "196 deg · SSW"
    assert format_wind_direction(None) == "-"
