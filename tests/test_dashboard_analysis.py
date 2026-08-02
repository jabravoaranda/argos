from __future__ import annotations

from datetime import date

from argos.dashboard.app import (
    analysis_frequency_label,
    analysis_missing_label,
    analysis_quick_dates,
    analytics_common_aggregations,
    analytics_variable_aggregations,
    analytics_variable_label,
)


VARIABLES = [
    {
        "variable_id": "ecowitt.outdoor_temperature",
        "source": "ecowitt",
        "label": "Temperatura Ecowitt",
        "unit": "deg C",
        "valid_aggregations": ["mean", "median", "last"],
    },
    {
        "variable_id": "controller.valve_state",
        "source": "controller",
        "label": "Estado EV",
        "unit": "0/1",
        "valid_aggregations": ["active_fraction", "last"],
    },
]


def test_analysis_variable_labels_and_aggregations() -> None:
    assert analytics_variable_label("ecowitt.outdoor_temperature", VARIABLES) == "ECOWITT · Temperatura Ecowitt [deg C]"
    assert analytics_variable_label("missing", VARIABLES) == "missing"
    assert analytics_variable_aggregations("controller.valve_state", VARIABLES) == ["active_fraction", "last"]
    assert analytics_common_aggregations("ecowitt.outdoor_temperature", "controller.valve_state", VARIABLES) == ["last"]


def test_analysis_labels_are_human_readable() -> None:
    assert analysis_frequency_label("weekly") == "Semanal"
    assert analysis_missing_label("linear_interpolation") == "Interpolación lineal"


def test_analysis_quick_dates_uses_current_filters_for_custom_range() -> None:
    start, end = analysis_quick_dates(
        "Personalizado",
        {
            "start": "2026-07-01T00:00:00+00:00",
            "end": "2026-07-31T23:59:59+00:00",
        },
    )

    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)
