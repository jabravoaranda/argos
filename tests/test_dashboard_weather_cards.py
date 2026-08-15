from __future__ import annotations

from datetime import timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from argos.dashboard.app import (
    DEFAULT_VARIABLES,
    DUAL_AXIS_CHART_HEIGHT,
    HOME_DUAL_AXIS_CHART_HEIGHT,
    LABELS,
    WIND_BARB_LANE_Y,
    aggregate_wind_vectors,
    build_observation_radiation_uv_figure,
    build_observation_rain_pressure_figure,
    build_observation_group_figures,
    build_observation_temperature_humidity_figure,
    build_observation_wind_figure,
    build_recent_weather_figure,
    default_ecowitt_gateway_identifier,
    element_key,
    format_utc_iso,
    format_wind_direction,
    local_time_values,
    mask_identifier,
    meteorological_direction_from_uv,
    observation_kpi_row_html,
    observation_local_xaxis_range,
    observation_period_meteogram_wind_frequency,
    observation_period_quality,
    observation_period_uses_recent_meteogram,
    observation_period_range,
    weather_metric_table_html,
    wind_components_ms,
    wind_direction_arrow,
)


def test_format_wind_direction_adds_compass_label() -> None:
    assert format_wind_direction(0) == "0 deg · N"
    assert format_wind_direction(196) == "196 deg · SSW"
    assert format_wind_direction(None) == "-"


def test_wind_direction_arrow_uses_direction_only_with_south_up() -> None:
    assert wind_direction_arrow(0) == "↓"
    assert wind_direction_arrow(90) == "←"
    assert wind_direction_arrow(180) == "↑"
    assert wind_direction_arrow(270) == "→"


def test_wind_components_follow_meteorological_direction() -> None:
    u_ms, v_ms = wind_components_ms(pd.Series([1.0, 1.0]), pd.Series([0.0, 180.0]))

    assert abs(u_ms.iloc[0]) < 1e-9
    assert v_ms.iloc[0] == -1.0
    assert abs(u_ms.iloc[1]) < 1e-9
    assert v_ms.iloc[1] == 1.0


def test_meteorological_direction_from_uv_handles_north_wraparound() -> None:
    u_ms, v_ms = wind_components_ms(pd.Series([1.0, 1.0]), pd.Series([350.0, 10.0]))
    mean_direction = meteorological_direction_from_uv(u_ms.mean(), v_ms.mean())

    assert mean_direction is not None
    assert min(mean_direction, 360 - mean_direction) < 1e-9


def test_meteorological_direction_from_uv_uses_speed_weighted_components() -> None:
    u_ms, v_ms = wind_components_ms(pd.Series([1.0, 3.0]), pd.Series([0.0, 180.0]))

    assert round(meteorological_direction_from_uv(u_ms.mean(), v_ms.mean())) == 180


def test_weather_metric_table_is_compact_3_by_4_layout() -> None:
    html = weather_metric_table_html(
        {
            "outdoor_temperature_c": 25.4,
            "outdoor_humidity_pct": 61,
            "relative_pressure_hpa": 1015.61,
            "wind_speed_ms": 0,
            "wind_direction_deg": 269,
            "wind_gust_ms": 0.7,
            "rain_last_24h_mm": 0,
            "rain_rate_mm_h": 0,
            "uv_index": 0,
            "solar_radiation_wm2": 0,
            "battery_voltage": 3.06,
            "ws90_capacitor_voltage": 5,
        }
    )

    assert html.count("<tr>") == 3
    assert html.count("<td") == 12
    assert "argos-weather-table" in html
    assert "argos-weather-card" not in html
    assert "Temperatura" in html
    assert "25.40 deg C" in html


def test_local_time_values_convert_utc_to_configured_timezone(monkeypatch) -> None:
    monkeypatch.setattr(
        "argos.dashboard.app.get_settings",
        lambda: SimpleNamespace(local_timezone="Europe/Madrid"),
    )

    values = local_time_values(pd.Series(pd.to_datetime(["2026-08-01T00:00:00Z"])))

    assert values.iloc[0] == pd.Timestamp("2026-08-01 02:00:00")


def test_recent_weather_figure_includes_temperature_and_humidity(monkeypatch) -> None:
    monkeypatch.setattr(
        "argos.dashboard.app.get_settings",
        lambda: SimpleNamespace(local_timezone="Europe/Madrid"),
    )
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(["2026-08-01T00:00:00Z", "2026-08-01T00:05:00Z"]),
            "outdoor_temperature_c": [25.4, 25.8],
            "outdoor_humidity_pct": [61.0, 60.0],
        }
    )

    figure = build_recent_weather_figure(frame)

    assert [trace.name for trace in figure.data] == ["Temperatura", "Humedad relativa"]
    assert figure.data[1].yaxis == "y2"
    assert figure.data[0].line.color == "#ff2d2d"
    assert figure.layout.yaxis.title.text == "deg C"
    assert figure.layout.yaxis2.title.text == "% HR"
    assert figure.layout.height == HOME_DUAL_AXIS_CHART_HEIGHT
    assert figure.layout.margin.t == 56
    assert figure.layout.legend.orientation == "h"
    assert figure.layout.legend.x == 0.5
    assert figure.layout.legend.xanchor == "center"
    assert figure.layout.legend.y == 1.14
    assert figure.layout.plot_bgcolor == "#ffffff"
    assert figure.layout.xaxis.showgrid is True
    assert figure.layout.xaxis3.title.text == "Tiempo local (Europe/Madrid)"
    assert list(figure.data[0].x)[0] == pd.Timestamp("2026-08-01 02:00:00")
    assert tuple(figure.layout.yaxis.range) == (0, 45)
    assert figure.layout.yaxis.dtick == 5
    assert tuple(figure.layout.yaxis2.range) == (0, 100)
    assert figure.layout.yaxis2.tickmode == "sync"
    assert figure.layout.yaxis2.showgrid is False
    assert figure.layout.yaxis3.title.text == "mm/h"
    assert figure.layout.yaxis4.visible is False


def test_recent_weather_figure_adds_wetterzentrale_style_day_markers() -> None:
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(
                ["2026-07-31T06:00:00Z", "2026-07-31T18:00:00Z", "2026-08-01T06:00:00Z"]
            ),
            "outdoor_temperature_c": [25.4, 35.8, 28.0],
        }
    )

    figure = build_recent_weather_figure(frame)

    assert any(annotation.text == "Fri Jul 31" for annotation in figure.layout.annotations)
    assert all(annotation.y <= 1.04 for annotation in figure.layout.annotations)
    assert len(figure.layout.shapes) == 1


def test_recent_weather_figure_includes_rain_bars_and_hourly_wind_arrows() -> None:
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(
                [
                    "2026-08-01T00:00:00Z",
                    "2026-08-01T01:00:00Z",
                    "2026-08-01T02:00:00Z",
                    "2026-08-01T03:00:00Z",
                ]
            ),
            "outdoor_temperature_c": [25.4, 25.8, 26.1, 26.3],
            "rain_rate_mm_h": [0.0, 0.2, 0.1, 0.0],
            "wind_speed_ms": [1.0, 1.0, 1.0, 1.0],
            "wind_direction_deg": [350.0, 10.0, 20.0, 90.0],
        }
    )

    figure = build_recent_weather_figure(frame)

    trace_names = [trace.name for trace in figure.data]
    assert "Precipitación" in trace_names
    assert "Viento" in trace_names
    wind_trace = next(trace for trace in figure.data if trace.name == "Viento")
    assert wind_trace.mode == "text"
    assert wind_trace.showlegend is False
    assert wind_trace.yaxis == "y4"
    assert set(wind_trace.y) == {WIND_BARB_LANE_Y}
    assert wind_trace.cliponaxis is False
    assert "↓" in list(wind_trace.text)


def test_aggregate_wind_vectors_supports_hourly_and_3h_resolution() -> None:
    wind = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(
                [
                    "2026-08-01T00:00:00Z",
                    "2026-08-01T01:00:00Z",
                    "2026-08-01T02:00:00Z",
                    "2026-08-01T03:00:00Z",
                ]
            ),
            "wind_speed_ms": [1.0, 1.0, 1.0, 1.0],
            "wind_direction_deg": [350.0, 10.0, 20.0, 90.0],
        }
    )

    assert len(aggregate_wind_vectors(wind, "1h")) == 4
    assert len(aggregate_wind_vectors(wind, "3h")) == 2


def test_default_ecowitt_gateway_identifier_prefers_configured_cloud_mac(monkeypatch) -> None:
    monkeypatch.setattr(
        "argos.dashboard.app.get_settings",
        lambda: SimpleNamespace(ecowitt_cloud_mac="14080871B1AF"),
    )

    assert default_ecowitt_gateway_identifier() == "14:08:08:71:B1:AF"


def test_mask_identifier_hides_middle_characters() -> None:
    assert mask_identifier("14:08:08:71:B1:AF") == "14...1:AF"


def test_observation_period_uses_recent_meteogram_for_day_and_week_only() -> None:
    assert observation_period_uses_recent_meteogram("Day") is True
    assert observation_period_uses_recent_meteogram("Week") is True
    assert observation_period_uses_recent_meteogram("Month") is False
    assert observation_period_uses_recent_meteogram("Year") is False
    assert observation_period_meteogram_wind_frequency("Day") == "1h"
    assert observation_period_meteogram_wind_frequency("Week") == "3h"


def test_observation_kpi_row_keeps_instrument_state_out_of_primary_cards() -> None:
    html = observation_kpi_row_html(
        pd.Series(
            {
                "outdoor_temperature_c": 31.4,
                "outdoor_humidity_pct": 42.0,
                "relative_pressure_hpa": 1012.3,
                "wind_speed_ms": 1.8,
                "wind_direction_deg": 225.0,
                "wind_gust_ms": 4.6,
                "rain_last_24h_mm": 2.4,
                "rain_rate_mm_h": 0.2,
                "solar_radiation_wm2": 827.0,
                "uv_index": 7.0,
                "battery_voltage": 3.06,
                "ws90_capacitor_voltage": 5.0,
            }
        )
    )

    for label in ["Temperatura", "Humedad", "Presión", "Viento SW", "Racha", "Lluvia 24 h", "Radiación", "UV"]:
        assert label in html
    assert "Batería" not in html
    assert "Capacitor" not in html
    assert "WS90" not in html


def test_observation_monitoring_figures_share_range_and_compact_axes(monkeypatch) -> None:
    monkeypatch.setattr(
        "argos.dashboard.app.get_settings",
        lambda: SimpleNamespace(local_timezone="Europe/Madrid"),
    )
    start = pd.Timestamp("2026-08-15T15:00:00Z").to_pydatetime()
    end = pd.Timestamp("2026-08-15T16:00:00Z").to_pydatetime()
    xaxis_range = observation_local_xaxis_range(start, end)
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(
                ["2026-08-15T15:00:00Z", "2026-08-15T15:30:00Z", "2026-08-15T16:00:00Z"],
            ),
            "outdoor_temperature_c": [31.0, 31.5, 32.0],
            "outdoor_humidity_pct": [42.0, 41.0, 40.0],
            "wind_speed_ms": [1.2, 1.4, 1.3],
            "wind_gust_ms": [3.4, 3.8, 3.2],
            "wind_direction_deg": [180.0, 225.0, 270.0],
            "solar_radiation_wm2": [700.0, 760.0, 720.0],
            "uv_index": [6.0, 7.0, 6.0],
            "rain_rate_mm_h": [0.0, 0.2, 0.0],
            "relative_pressure_hpa": [1012.0, 1011.8, 1011.6],
        }
    )

    figures = [
        build_observation_temperature_humidity_figure(frame, xaxis_range=xaxis_range),
        build_observation_wind_figure(frame, xaxis_range=xaxis_range),
        build_observation_radiation_uv_figure(frame, xaxis_range=xaxis_range),
        build_observation_rain_pressure_figure(frame, xaxis_range=xaxis_range),
    ]

    assert all(figure is not None for figure in figures)
    for figure in figures:
        assert figure.layout.height == 235
        assert list(figure.layout.xaxis.range) == xaxis_range
    assert figures[0].layout.yaxis.title.text == "Temperatura, deg C"
    assert figures[0].layout.yaxis2.title.text == "Humedad, %"
    assert figures[1].layout.yaxis.title.text == "Viento, m/s"
    assert figures[2].layout.yaxis.title.text == "Radiación, W/m2"
    assert figures[2].layout.yaxis2.title.text == "UV"
    assert figures[3].layout.yaxis.title.text == "Lluvia, mm/h"
    assert figures[3].layout.yaxis2.title.text == "Presión, hPa"
    assert [trace.name for trace in figures[3].data] == ["Lluvia", "Presión"]


def test_observation_period_quality_calculates_coverage_and_gaps() -> None:
    start = pd.Timestamp("2026-08-15T15:00:00Z").to_pydatetime().replace(tzinfo=timezone.utc)
    end = pd.Timestamp("2026-08-15T15:05:00Z").to_pydatetime().replace(tzinfo=timezone.utc)
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(
                [
                    "2026-08-15T15:00:00Z",
                    "2026-08-15T15:01:00Z",
                    "2026-08-15T15:02:00Z",
                    "2026-08-15T15:05:00Z",
                ],
            ),
        }
    )

    coverage, gaps = observation_period_quality(frame, start=start, end=end)

    assert coverage == pytest.approx(66.666, abs=0.01)
    assert gaps == 1


def test_observation_groups_use_secondary_axis_for_humidity() -> None:
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(["2026-08-01T00:00:00Z", "2026-08-01T00:05:00Z"]),
            "outdoor_temperature_c": [25.4, 25.8],
            "outdoor_humidity_pct": [61.0, 60.0],
        }
    )

    groups = dict(
        build_observation_group_figures(frame, ["outdoor_temperature_c", "outdoor_humidity_pct"]),
    )
    figure = groups["Temperatura y humedad relativa"]

    assert [trace.name for trace in figure.data] == ["Temperatura", "Humedad relativa"]
    assert figure.data[1].yaxis == "y2"
    assert figure.layout.yaxis.title.text == "deg C"
    assert figure.layout.yaxis2.title.text == "% HR"
    assert figure.layout.height == DUAL_AXIS_CHART_HEIGHT
    assert figure.layout.yaxis2.tickmode == "sync"


def test_wind_direction_group_uses_markers_on_circular_scale() -> None:
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(["2026-08-01T00:00:00Z", "2026-08-01T00:05:00Z"]),
            "wind_direction_deg": [359.0, 1.0],
        }
    )

    groups = dict(build_observation_group_figures(frame, ["wind_direction_deg"]))
    figure = groups["Dirección de viento"]

    assert figure.data[0].mode == "markers"
    assert list(figure.layout.yaxis.tickvals) == [0, 90, 180, 270, 360]
    assert list(figure.layout.yaxis.ticktext) == ["N", "E", "S", "W", "N"]


def test_remaining_measured_variables_are_plotted_after_irradiance_group() -> None:
    frame = pd.DataFrame(
        {
            "observed_at_utc": pd.to_datetime(["2026-08-01T00:00:00Z", "2026-08-01T00:05:00Z"]),
            "solar_radiation_wm2": [400.0, 420.0],
            "uv_index": [4.0, 4.2],
            "battery_voltage": [3.06, 3.05],
            "ws90_capacitor_voltage": [5.0, 4.98],
        }
    )

    groups = build_observation_group_figures(
        frame,
        ["solar_radiation_wm2", "uv_index", "battery_voltage", "ws90_capacitor_voltage"],
    )
    titles = [title for title, _figure in groups]
    battery_figure = dict(groups)["Otras variables medidas (V)"]

    assert titles == ["Irradiancia y UV", "Otras variables medidas (V)"]
    assert [trace.name for trace in battery_figure.data] == ["WS90 battery (V)", "WS90 capacitor (V)"]
    assert "battery_voltage" in DEFAULT_VARIABLES
    assert "ws90_capacitor_voltage" in DEFAULT_VARIABLES


def test_observation_period_range_uses_relative_utc_window() -> None:
    now = pd.Timestamp("2026-08-01T12:00:00Z").to_pydatetime()

    start, end = observation_period_range(now, pd.Timedelta(days=7).to_pytimedelta())

    assert format_utc_iso(start) == "2026-07-25T12:00:00Z"
    assert format_utc_iso(end) == "2026-08-01T12:00:00Z"


def test_element_key_is_stable_for_repeated_observation_charts() -> None:
    assert element_key("observations_day", "Irradiancia y UV") == "observations_day_irradiancia_y_uv"


def test_default_variables_are_available_as_selector_options() -> None:
    assert set(DEFAULT_VARIABLES).issubset(LABELS)
