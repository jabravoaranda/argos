from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from argos.dashboard.app import (
    build_flowmeter_figure,
    cached_flowmeter_minutes,
    compact_metric_html,
    flowmeter_chart_window,
    flowmeter_trace_values,
    format_binary_signal,
    format_binary_ev_state,
    format_integer,
    format_valve_state,
    normalize_http_base_url,
    valve_estimation_message,
    valve_action_from_state,
    valve_phase_from_response,
    valve_phase_label,
)
from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_sessionmaker, reset_database_caches
from argos.models import ArgosNodeFlowmeterMinute


def test_format_valve_state_uses_boolean_open_fields() -> None:
    assert format_valve_state({"open": True}) == "Open"
    assert format_valve_state({"is_open": False}) == "Closed"


def test_format_valve_state_normalizes_status_fields() -> None:
    assert format_valve_state({"state": "closed"}) == "Closed"
    assert format_valve_state({"status": "OPEN"}) == "Open"


def test_format_valve_state_prefers_boolean_state_fields_over_generic_status() -> None:
    assert format_valve_state({"status": "ok", "open": False}) == "Closed"
    assert format_valve_state({"status": "ok", "relay_active": True}) == "Open"


def test_valve_action_from_state_returns_only_available_action() -> None:
    assert valve_action_from_state({"open": False}) == "open"
    assert valve_action_from_state({"open": True}) == "close"
    assert valve_action_from_state({"state": "moving"}) is None


def test_valve_phase_from_response_uses_explicit_state_names() -> None:
    assert valve_phase_from_response({"state": "closed"}) == "closed"
    assert valve_phase_from_response({"state": "open"}) == "open"
    assert valve_phase_from_response({"state": "moving"}) == "unknown"


def test_valve_phase_label_renders_transitional_states() -> None:
    assert valve_phase_label("sending_open_command") == "Sending open command"
    assert valve_phase_label("opening") == "Opening"
    assert valve_phase_label("closing") == "Closing"


def test_valve_estimation_message_is_explicit() -> None:
    assert valve_estimation_message("open") == "ARGOS estimates the valve is open; no independent position sensor confirms it."
    assert valve_estimation_message("closed") == "ARGOS estimates the valve is closed; no independent position sensor confirms it."


def test_normalize_http_base_url_adds_scheme_and_strips_slash() -> None:
    assert normalize_http_base_url("192.168.1.40") == "http://192.168.1.40"
    assert normalize_http_base_url(" http://192.168.1.40/ ") == "http://192.168.1.40"


def test_compact_metric_html_escapes_values() -> None:
    assert "&lt;bad&gt;" in compact_metric_html("State", "<bad>")


def test_format_binary_ev_state_uses_zero_one_labels() -> None:
    assert format_binary_ev_state(True) == "Abierta (1)"
    assert format_binary_ev_state(False) == "Cerrada (0)"
    assert format_binary_ev_state(1) == "Abierta (1)"
    assert format_binary_ev_state(0) == "Cerrada (0)"


def test_binary_and_integer_formatters_are_compact() -> None:
    assert format_binary_signal(True) == "1"
    assert format_binary_signal(False) == "0"
    assert format_integer(123.0) == "123"


def test_flowmeter_chart_window_limits_to_one_hour() -> None:
    start, end = flowmeter_chart_window("2026-07-31T00:00:00Z", "2026-07-31T12:00:00Z")

    assert start == "2026-07-31T11:00:00Z"
    assert end == "2026-07-31T12:00:00Z"


def test_cached_flowmeter_minutes_reads_aggregates_for_normalized_node_url(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    cached_flowmeter_minutes.clear()

    engine = get_sessionmaker().kw["bind"]
    Base.metadata.create_all(engine)
    window_start = datetime(2026, 7, 31, 8, 10, tzinfo=UTC)
    with get_sessionmaker()() as session:
        session.add(
            ArgosNodeFlowmeterMinute(
                node_url="http://192.168.1.40",
                window_start_utc=window_start,
                window_end_utc=window_start + timedelta(minutes=1),
                pulse_count_start=100,
                pulse_count_end=154,
                pulse_delta=54,
                volume_l=2.0,
                avg_flow_l_min=2.0,
                max_flow_l_min=4.5,
                samples_count=12,
                relay1_state_start=False,
                relay1_state_end=True,
                relay1_open_samples_count=8,
                relay1_open_fraction=8 / 12,
            )
        )
        session.commit()

    rows = cached_flowmeter_minutes(
        "192.168.1.40",
        "2026-07-31T08:00:00Z",
        "2026-07-31T09:00:00Z",
    )

    assert rows == [
        {
            "window_start_utc": window_start.replace(tzinfo=None),
            "window_end_utc": (window_start + timedelta(minutes=1)).replace(tzinfo=None),
            "pulse_delta": 54,
            "boot_total_l_start": None,
            "boot_total_l_end": None,
            "total_l_start": None,
            "total_l_end": None,
            "hydrological_year_l_start": None,
            "hydrological_year_l_end": None,
            "session_active_start": None,
            "session_active_end": None,
            "session_l_start": None,
            "session_l_end": None,
            "last_session_l_start": None,
            "last_session_l_end": None,
            "volume_l": 2.0,
            "avg_flow_l_min": 2.0,
            "max_flow_l_min": 4.5,
            "samples_count": 12,
            "relay1_state_start": False,
            "relay1_state_end": True,
            "relay1_open_samples_count": 8,
            "relay1_open_fraction": 8 / 12,
        }
    ]

    get_settings.cache_clear()
    reset_database_caches()
    cached_flowmeter_minutes.clear()


def test_build_flowmeter_figure_includes_relay1_open_trace() -> None:
    frame = pd.DataFrame(
        {
            "window_start_utc": [datetime(2026, 7, 31, 8, 10, tzinfo=UTC)],
            "avg_flow_l_min": [2.0],
            "max_flow_l_min": [4.5],
            "relay1_state_end": [True],
        }
    )

    figure = build_flowmeter_figure(
        frame,
        start_iso="2026-07-31T08:00:00Z",
        end_iso="2026-07-31T13:00:00Z",
    )

    assert [trace.name for trace in figure.data] == ["Caudal medio", "Caudal máximo", "EV"]
    assert list(figure.data[2].y) == [1]
    assert figure.layout.yaxis2.title.text == "EV"
    assert list(figure.layout.yaxis2.tickvals) == [0, 1]
    assert figure.layout.xaxis.range is not None


def test_flowmeter_trace_values_breaks_long_gaps() -> None:
    utc_values = pd.Series(
        [
            datetime(2026, 7, 31, 8, 10, tzinfo=UTC),
            datetime(2026, 7, 31, 8, 11, tzinfo=UTC),
            datetime(2026, 7, 31, 9, 0, tzinfo=UTC),
        ]
    )
    local_values = pd.Series(["08:10", "08:11", "09:00"])
    y_values = pd.Series([1.0, 2.0, 3.0])

    x_out, y_out = flowmeter_trace_values(utc_values, local_values, y_values)

    assert x_out == ["08:10", "08:11", "09:00", "09:00"]
    assert y_out == [1.0, 2.0, None, 3.0]
