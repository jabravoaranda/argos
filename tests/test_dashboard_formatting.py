from datetime import UTC, datetime

import pandas as pd

from argos.dashboard.formatting import (
    format_binary_ev_state,
    format_binary_signal,
    format_compact_date_range,
    format_file_size,
    format_number,
    format_percent,
    parse_datetime,
    short_identifier,
)


def test_numeric_and_binary_formatters_cover_empty_and_numeric_values() -> None:
    assert format_number(None, "mm") == "-"
    assert format_number(1.25, "mm") == "1.25 mm"
    assert format_percent(0.456) == "46%"
    assert format_binary_signal(float("nan")) == "-"
    assert format_binary_signal("high") == "1"
    assert format_binary_ev_state("closed") == "Cerrada (0)"


def test_date_and_identifier_formatters_are_stable() -> None:
    expected = datetime(2026, 9, 19, 12, 30, tzinfo=UTC)
    assert parse_datetime("2026-09-19T12:30:00Z") == expected
    assert parse_datetime(pd.Timestamp(expected)) == expected
    assert parse_datetime("not-a-date") is None
    assert format_compact_date_range("2026-09-01", "2026-09-19") == "1 sep 2026–19 sep 2026"
    assert short_identifier("1234567890123456") == "12345678...3456"


def test_file_size_formatter_preserves_dashboard_labels() -> None:
    assert format_file_size(None) == "tamaño desconocido"
    assert format_file_size(512) == "0.5 KB"
    assert format_file_size(2 * 1024 * 1024) == "2.0 MB"
