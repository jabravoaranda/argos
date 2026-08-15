from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from argos.dashboard import app as dashboard_app
from argos.dashboard.argos_node_client import ArgosNodeError
from argos.dashboard.app import (
    VALVE_CONTROLS,
    ValveControl,
    build_flowmeter_figure,
    build_irrigation_water_figure,
    cached_flowmeter_minutes,
    close_all_configured_valves,
    compact_metric_html,
    flowmeter_chart_window,
    flowmeter_status_html,
    flowmeter_visible_xaxis_range,
    flowmeter_trace_values,
    format_binary_signal,
    format_binary_ev_state,
    format_integer,
    irrigation_summary_html,
    format_valve_state,
    normalize_http_base_url,
    valve_control_options,
    valve_estimation_message,
    valve_action_from_state,
    valve_control_label,
    valve_name_for_id,
    valve_availability_label,
    valve_card_state_label,
    valve_phase_from_response,
    valve_phase_label,
)
from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_sessionmaker, reset_database_caches
from argos.models import ArgosNodeFlowmeterMinute


class FakeValveClient:
    def __init__(self, *, failures: set[int] | None = None) -> None:
        self.failures = failures or set()
        self.closed: list[int] = []

    def close_valve(self, valve_id: int) -> dict[str, Any]:
        self.closed.append(valve_id)
        if valve_id in self.failures:
            raise ArgosNodeError(f"valve {valve_id} failed")
        return {"id": valve_id, "state": "closed"}


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


def test_valve_control_options_include_general_and_four_sector_valves() -> None:
    assert [
        (valve.functional_name, valve.technical_id, valve.valve_id, valve.relay_id, valve.enabled_for_control)
        for valve in VALVE_CONTROLS
    ] == [
        ("General", "EV8", 8, 8, True),
        ("Sector I", "EV6", 6, 6, True),
        ("Sector II", "EV7", 7, 7, True),
        ("Sector III", "EV4", 4, 4, False),
        ("Sector IV", "EV5", 5, 5, False),
    ]
    assert valve_control_options() == {
        "General · EV8": 8,
        "Sector I · EV6": 6,
        "Sector II · EV7": 7,
        "Sector III · EV4": 4,
        "Sector IV · EV5": 5,
    }
    assert [valve_control_label(valve) for valve in VALVE_CONTROLS] == [
        "General · EV8",
        "Sector I · EV6",
        "Sector II · EV7",
        "Sector III · EV4",
        "Sector IV · EV5",
    ]
    assert valve_name_for_id(8) == "General"
    assert valve_name_for_id(6) == "Sector I"
    assert valve_name_for_id(7) == "Sector II"
    assert valve_name_for_id(4) == "Sector III"
    assert valve_name_for_id(5) == "Sector IV"
    assert valve_name_for_id(99) == "EV99"


def test_close_all_configured_valves_closes_every_valve() -> None:
    client = FakeValveClient()

    result = close_all_configured_valves(client)  # type: ignore[arg-type]

    assert result.ok is True
    assert client.closed == [8, 6, 7]


def test_close_all_configured_valves_is_idempotent_for_already_closed_valves() -> None:
    client = FakeValveClient()

    first = close_all_configured_valves(client)  # type: ignore[arg-type]
    second = close_all_configured_valves(client)  # type: ignore[arg-type]

    assert first.ok is True
    assert second.ok is True
    assert client.closed == [8, 6, 7, 8, 6, 7]


def test_close_all_configured_valves_attempts_remaining_valves_after_failure() -> None:
    client = FakeValveClient(failures={6})

    result = close_all_configured_valves(client)  # type: ignore[arg-type]

    assert result.ok is False
    assert client.closed == [8, 6, 7]
    assert [valve_control_label(item.valve) for item in result.succeeded] == [
        "General · EV8",
        "Sector II · EV7",
    ]
    assert [(valve_control_label(item.valve), item.error) for item in result.failed] == [("Sector I · EV6", "valve 6 failed")]


def test_close_all_configured_valves_skips_non_irrigation_outputs(monkeypatch) -> None:
    client = FakeValveClient()
    monkeypatch.setattr(
        dashboard_app,
        "VALVE_CONTROLS",
        (
            ValveControl(technical_id="EV8", functional_name="General", valve_id=8, relay_id=8),
            ValveControl(technical_id="OUT1", functional_name="Aux output", valve_id=1, relay_id=1, irrigation=False),
        ),
    )

    result = close_all_configured_valves(client)  # type: ignore[arg-type]

    assert result.ok is True
    assert client.closed == [8]


def test_close_all_configured_valves_skips_irrigation_valves_not_enabled_for_control(monkeypatch) -> None:
    client = FakeValveClient()
    monkeypatch.setattr(
        dashboard_app,
        "VALVE_CONTROLS",
        (
            ValveControl(technical_id="EV8", functional_name="General", valve_id=8, relay_id=8),
            ValveControl(
                technical_id="EV4",
                functional_name="Sector III",
                valve_id=4,
                relay_id=4,
                enabled_for_control=False,
            ),
        ),
    )

    result = close_all_configured_valves(client)  # type: ignore[arg-type]

    assert result.ok is True
    assert client.closed == [8]


def test_valve_availability_and_card_state_labels_are_explicit() -> None:
    assert valve_availability_label(VALVE_CONTROLS[0]) == "Operativa"
    assert valve_availability_label(VALVE_CONTROLS[3]) == "No operativa"
    assert valve_card_state_label("closed") == "Cerrada estimada"
    assert valve_card_state_label("not_operational") == "Pendiente servicio"
    assert valve_card_state_label("error") == "Error de comunicación"


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


def test_flowmeter_status_html_keeps_water_metrics_separate_from_valves() -> None:
    parsed = type(
        "ParsedFlowmeter",
        (),
        {
            "flow_l_min": 12.5,
            "session_l": 3.0,
            "last_session_l": 8.0,
            "hydrological_year_l": 120.0,
        },
    )()

    html = flowmeter_status_html(parsed)

    assert "Lectura instantánea" in html
    assert "Cierres de periodo" in html
    assert "Caudal actual" in html
    assert "Sesión actual" in html
    assert "Última sesión" in html
    assert "Año hidrológico" in html
    assert "Electroválvula" not in html
    assert "Total histórico" not in html


def test_irrigation_summary_html_contains_only_operational_state() -> None:
    html = irrigation_summary_html(open_count=2, active_count=3, error_count=1, unknown_count=0)

    assert "Resumen operativo" in html
    assert "Electroválvulas abiertas" in html
    assert "Sectores activos" in html
    assert "Alertas activas" in html
    assert "Sin respuesta" in html
    assert "Caudal" not in html
    assert "Sesión" not in html
    assert "Total histórico" not in html


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
    assert figure.layout.height == 240


def test_build_irrigation_water_figure_composes_flow_and_accumulated_shared_xaxis() -> None:
    frame = pd.DataFrame(
        {
            "window_start_utc": [
                datetime(2026, 7, 31, 8, 10, tzinfo=UTC),
                datetime(2026, 7, 31, 8, 11, tzinfo=UTC),
            ],
            "avg_flow_l_min": [2.0, 1.0],
            "max_flow_l_min": [4.5, 2.0],
            "relay1_state_end": [True, False],
            "total_l_end": [100.0, 101.0],
            "session_l_end": [3.0, 4.0],
            "hydrological_year_l_end": [50.0, 51.0],
        }
    )

    figure = build_irrigation_water_figure(
        frame,
        start_iso="2026-07-31T08:00:00Z",
        end_iso="2026-07-31T09:00:00Z",
    )

    assert figure is not None
    assert [trace.name for trace in figure.data] == [
        "Caudal medio",
        "Caudal máximo",
        "EV",
        "Total histórico",
        "Sesión actual",
        "Año hidrológico",
    ]
    assert figure.layout.xaxis.matches == "x2"
    assert figure.layout.xaxis2.title.text == "Tiempo local (Europe/Madrid)"
    assert figure.layout.yaxis.title.text == "Caudal, L/min"
    assert figure.layout.yaxis2.title.text == "EV"
    assert figure.layout.yaxis3.title.text == "Riego acumulado, L"
    assert figure.layout.height == 360
    assert not figure.layout.annotations


def test_flowmeter_visible_xaxis_range_starts_one_minute_before_first_data() -> None:
    frame = pd.DataFrame(
        {
            "window_start_utc": [
                datetime(2026, 7, 31, 8, 10, tzinfo=UTC),
                datetime(2026, 7, 31, 8, 11, tzinfo=UTC),
            ],
        }
    )

    xaxis_range = flowmeter_visible_xaxis_range(
        frame,
        start_iso="2026-07-31T04:00:00Z",
        end_iso="2026-07-31T09:00:00Z",
    )

    assert xaxis_range is not None
    assert xaxis_range[0] == datetime(2026, 7, 31, 10, 9)
    assert xaxis_range[1] == datetime(2026, 7, 31, 11, 0)


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
