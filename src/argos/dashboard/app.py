from __future__ import annotations

import logging
import time as monotonic_time
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import streamlit as st

from argos.config.settings import get_settings
from argos.dashboard.api_client import ArgosApiClient, ArgosApiError
from argos.dashboard.argos_node_client import ArgosNodeClient, ArgosNodeError
from argos.dashboard.filters import filter_observations_by_source, observation_source_counts
from argos.dashboard.period_profiles import build_hourly_profile, build_rain_accumulation
from argos.dashboard.raw_reports import build_raw_report_table, latest_payload_preview
from argos.dashboard.statistics import build_descriptive_statistics
from argos.dashboard.summaries import build_annual_summary, build_monthly_summary, build_seasonal_summary
from argos.dashboard.trends import build_trend_frame
from argos.database.session import get_sessionmaker
from argos.integrations.aemet.client import AemetClient, AemetConfigError
from argos.services.aemet_import import AemetImportRangeError, AemetImportService


logger = logging.getLogger(__name__)

st.set_page_config(page_title="ARGOS dashboard", page_icon=":material/monitoring:", layout="wide")


DEFAULT_VARIABLES = [
    "outdoor_temperature_c",
    "outdoor_humidity_pct",
    "relative_pressure_hpa",
    "wind_speed_ms",
    "wind_gust_ms",
    "rain_rate_mm_h",
    "solar_radiation_wm2",
    "uv_index",
]

DEFAULT_VALVE_OPENING_DURATION_S = 7.0
DEFAULT_VALVE_CLOSING_DURATION_S = 7.0
DEFAULT_AEMET_STATION = "6127X"
AEMET_BACKFILL_DEFAULT_START = date(1900, 1, 1)


LABELS = {
    "observed_at_utc": "Observed UTC",
    "outdoor_temperature_c": "Outdoor temperature (deg C)",
    "outdoor_humidity_pct": "Outdoor humidity (%)",
    "relative_pressure_hpa": "Relative pressure (hPa)",
    "wind_speed_ms": "Wind speed (m/s)",
    "wind_gust_ms": "Wind gust (m/s)",
    "rain_rate_mm_h": "Rain rate (mm/h)",
    "rain_day_mm": "Daily rain (mm)",
    "rain_last_24h_mm": "Rain last 24 h (mm)",
    "solar_radiation_wm2": "Solar radiation (W/m2)",
    "uv_index": "UV index",
    "battery_voltage": "WS90 battery (V)",
    "ws90_capacitor_voltage": "WS90 capacitor (V)",
}

AEMET_LABELS = {
    "temperature_mean_c": "Temperatura media (deg C)",
    "temperature_min_c": "Temperatura mínima (deg C)",
    "temperature_max_c": "Temperatura máxima (deg C)",
    "precipitation_mm": "Precipitación (mm)",
    "wind_speed_mean_ms": "Viento medio (m/s)",
    "wind_gust_ms": "Racha (m/s)",
    "sunshine_hours": "Horas de sol",
    "pressure_max_hpa": "Presión máxima (hPa)",
    "pressure_min_hpa": "Presión mínima (hPa)",
    "humidity_mean_pct": "Humedad media (%)",
    "humidity_min_pct": "Humedad mínima (%)",
    "humidity_max_pct": "Humedad máxima (%)",
}

SATELLITE_LABELS = {
    "ndvi": "NDVI",
    "savi": "SAVI",
    "ndre": "NDRE",
    "ndmi": "NDMI",
}

SATELLITE_QUALITY_LABELS = {
    "all": "Todas",
    "valid": "Válidas",
    "partial": "Parciales",
    "invalid": "Inválidas",
}


def main() -> None:
    st.title("ARGOS dashboard")
    st.caption("Agricultural Remote Gateway for Observation and Sensing")

    (
        client,
        node_client,
        start_iso,
        end_iso,
        selected_variables,
        selected_sources,
        valve_opening_duration_s,
        valve_closing_duration_s,
    ) = sidebar()

    try:
        health = cached_health(client.base_url)
        station = cached_station(client.base_url)
        hardware = cached_station_hardware(client.base_url)
        latest = cached_latest(client.base_url)
        status = cached_status(client.base_url)
        observations = cached_observations(client.base_url, start_iso, end_iso)
        daily = cached_daily(client.base_url, start_iso, end_iso)
        weekly = cached_weekly(client.base_url, start_iso, end_iso)
    except ArgosApiError as exc:
        st.error(str(exc))
        st.stop()

    observations_df = dataframe_from_records(observations, "observed_at_utc")
    observations_df = filter_observations_by_source(observations_df, selected_sources)
    daily_df = dataframe_from_records(daily, "period_start")
    weekly_df = dataframe_from_records(weekly, "period_start")

    home_tab, observations_tab, summaries_tab, trends_tab, aemet_tab, satellite_tab, valves_tab, quality_tab = st.tabs(
        ["Home", "Observations", "Summaries", "Trends", "AEMET", "Observación satelital", "Valves", "Quality"]
    )

    with home_tab:
        render_home(
            health=health,
            station=station,
            hardware=hardware,
            latest=latest,
            status=status,
            observations_df=observations_df,
        )

    with observations_tab:
        render_observations(observations_df, selected_variables)

    with summaries_tab:
        render_summaries(daily_df, weekly_df)

    with trends_tab:
        render_trends(observations_df, selected_variables)

    with aemet_tab:
        render_aemet(client, start_date=start_iso[:10], end_date=end_iso[:10])

    with satellite_tab:
        render_satellite(client, start_iso=start_iso, end_iso=end_iso)

    with valves_tab:
        render_valves(
            node_client,
            valve_opening_duration_s=valve_opening_duration_s,
            valve_closing_duration_s=valve_closing_duration_s,
        )

    with quality_tab:
        render_quality(client)


def sidebar() -> tuple[ArgosApiClient, ArgosNodeClient, str, str, list[str], list[str], float, float]:
    with st.sidebar:
        st.header("Connection")
        base_url = st.text_input("ARGOS API URL", value="http://127.0.0.1:8080")
        node_url = st.text_input("argos-node URL", value="http://10.194.83.1")
        admin_token = st.text_input("Admin token", value="", type="password")

        st.header("Time range")
        today = date.today()
        default_start = today - timedelta(days=1)
        selected_dates = st.date_input(
            "Date range",
            value=(default_start, today),
            min_value=date(2000, 1, 1),
            max_value=today,
        )
        if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
            start_date, end_date = selected_dates
        else:
            start_date = end_date = today

        start_iso = datetime.combine(start_date, time.min, tzinfo=UTC).isoformat().replace("+00:00", "Z")
        end_iso = datetime.combine(end_date, time.max, tzinfo=UTC).isoformat().replace("+00:00", "Z")

        st.header("Variables")
        selected_variables = st.multiselect("Chart variables", options=list(LABELS), default=DEFAULT_VARIABLES)

        st.header("Observation source")
        selected_sources = st.pills(
            "Sources",
            options=["DIRECT", "BACKFILLED"],
            default=["DIRECT", "BACKFILLED"],
            selection_mode="multi",
        )

        st.header("Valve timing")
        valve_opening_duration_s = st.number_input(
            "Opening duration (s)",
            min_value=0.0,
            value=DEFAULT_VALVE_OPENING_DURATION_S,
            step=0.5,
        )
        valve_closing_duration_s = st.number_input(
            "Closing duration (s)",
            min_value=0.0,
            value=DEFAULT_VALVE_CLOSING_DURATION_S,
            step=0.5,
        )

        if st.button("Refresh data", icon=":material/refresh:"):
            st.cache_data.clear()
            st.rerun()

    return (
        ArgosApiClient(base_url=base_url, admin_token=admin_token or None),
        ArgosNodeClient(base_url=node_url),
        start_iso,
        end_iso,
        selected_variables,
        list(selected_sources or []),
        float(valve_opening_duration_s),
        float(valve_closing_duration_s),
    )


@st.cache_data(ttl=15)
def cached_health(base_url: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_health()


@st.cache_data(ttl=15)
def cached_latest(base_url: str) -> dict[str, Any] | None:
    return ArgosApiClient(base_url=base_url).get_latest()


@st.cache_data(ttl=60)
def cached_station(base_url: str) -> dict[str, Any] | None:
    return ArgosApiClient(base_url=base_url).get_station()


@st.cache_data(ttl=60)
def cached_station_hardware(base_url: str) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_station_hardware()


@st.cache_data(ttl=15)
def cached_status(base_url: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_gateway_status()


@st.cache_data(ttl=30)
def cached_observations(base_url: str, start: str, end: str) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_observations(start=start, end=end)


@st.cache_data(ttl=60)
def cached_daily(base_url: str, start: str, end: str) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_daily_summary(start=start, end=end)


@st.cache_data(ttl=60)
def cached_weekly(base_url: str, start: str, end: str) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_weekly_summary(start=start, end=end)


@st.cache_data(ttl=60)
def cached_satellite_status(base_url: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_satellite_status()


@st.cache_data(ttl=60)
def cached_satellite_latest(base_url: str) -> dict[str, Any] | None:
    return ArgosApiClient(base_url=base_url).get_satellite_latest()


@st.cache_data(ttl=60)
def cached_satellite_zones(base_url: str) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_satellite_zones()


@st.cache_data(ttl=60)
def cached_satellite_bounds(base_url: str, quality_status: str | None) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_satellite_bounds(quality_status=quality_status)


@st.cache_data(ttl=60)
def cached_satellite_export_rows(
    base_url: str,
    start: str | None,
    end: str | None,
    quality_status: str | None,
) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url, timeout_seconds=20).get_satellite_export_json(
        start=start,
        end=end,
        quality_status=quality_status,
    )


@st.cache_data(ttl=60)
def cached_satellite_timeseries(
    base_url: str,
    metric: str,
    start: str,
    end: str,
    quality_status: str | None,
) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_satellite_timeseries(
        metric=metric,
        start=start,
        end=end,
        quality_status=quality_status,
    )


@st.cache_data(ttl=60)
def cached_aemet_stations(base_url: str) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_weather_stations(provider="aemet")


@st.cache_data(ttl=60)
def cached_aemet_observations(base_url: str, station: str, start: str, end: str) -> list[dict[str, Any]]:
    client = ArgosApiClient(base_url=base_url)
    records: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        page = client.get_aemet_observations(
            station=station,
            start=start,
            end=end,
            limit=page_size,
            offset=offset,
        )
        records.extend(page)
        if len(page) < page_size:
            return records
        offset += page_size


@st.cache_data(ttl=30)
def cached_latest_aemet_sync(base_url: str, station: str) -> dict[str, Any] | None:
    return ArgosApiClient(base_url=base_url).get_latest_aemet_sync(station=station)


@st.cache_data(ttl=60)
def cached_aemet_bounds(base_url: str, station: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_aemet_bounds(station=station)


def dataframe_from_records(records: list[dict[str, Any]], date_column: str) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(records)
    if not frame.empty and date_column in frame:
        frame[date_column] = pd.to_datetime(frame[date_column])
    return frame


def render_home(
    *,
    health: dict[str, Any],
    station: dict[str, Any] | None,
    hardware: list[dict[str, Any]],
    latest: dict[str, Any] | None,
    status: dict[str, Any],
    observations_df: pd.DataFrame,
) -> None:
    render_station_identity(station=station, hardware=hardware, status=status)

    if latest is None:
        st.info("No weather observations received yet.")
        return

    with st.container(horizontal=True):
        st.metric("API", health.get("status", "unknown"), border=True)
        st.metric("Gateway", "Online" if status.get("online") else "Offline", border=True)
        st.metric("Last seen", format_datetime(status.get("last_seen_at")), border=True)
        st.metric("Outdoor temperature", format_number(latest.get("outdoor_temperature_c"), "deg C"), border=True)

    source_counts = observation_source_counts(observations_df)
    if source_counts:
        with st.container(horizontal=True):
            st.metric("Direct observations", source_counts.get("DIRECT", 0), border=True)
            st.metric("Backfilled observations", source_counts.get("BACKFILLED", 0), border=True)
            st.metric("Unknown source", source_counts.get("UNKNOWN", 0), border=True)

    with st.container(horizontal=True):
        st.metric("Humidity", format_number(latest.get("outdoor_humidity_pct"), "%"), border=True)
        st.metric("Pressure", format_number(latest.get("relative_pressure_hpa"), "hPa"), border=True)
        st.metric("Wind gust", format_number(latest.get("wind_gust_ms"), "m/s"), border=True)
        st.metric("Rain 24 h", format_number(latest.get("rain_last_24h_mm"), "mm"), border=True)
        st.metric("UV", format_number(latest.get("uv_index"), ""), border=True)

    with st.container(horizontal=True):
        st.metric("Solar radiation", format_number(latest.get("solar_radiation_wm2"), "W/m2"), border=True)
        st.metric("WS90 battery", format_number(latest.get("battery_voltage"), "V"), border=True)
        st.metric("WS90 capacitor", format_number(latest.get("ws90_capacitor_voltage"), "V"), border=True)

    if not observations_df.empty:
        with st.container(border=True):
            st.subheader("Recent temperature")
            st.line_chart(
                observations_df[["observed_at_utc", "outdoor_temperature_c"]].dropna(),
                x="observed_at_utc",
                y="outdoor_temperature_c",
                x_label="Observed UTC",
                y_label="deg C",
            )


def render_station_identity(
    *,
    station: dict[str, Any] | None,
    hardware: list[dict[str, Any]],
    status: dict[str, Any],
) -> None:
    with st.container(border=True):
        st.subheader("Station identity")
        if station is None:
            st.info("Station identity is not available yet.")
            return

        active_hardware = hardware[0] if hardware else {}
        with st.container(horizontal=True):
            st.metric("Station", station.get("slug", "-"), border=True)
            st.metric("Station UUID", short_identifier(station.get("uuid")), border=True)
            st.metric("Gateway status", "Online" if status.get("online") else "Offline", border=True)
            st.metric(
                "Hardware",
                active_hardware.get("station_type") or active_hardware.get("mac_address") or "-",
                border=True,
            )

        if hardware:
            hardware_df = pd.DataFrame.from_records(hardware)
            visible_columns = [
                column
                for column in ["id", "mac_address", "station_type", "last_seen_at", "enabled"]
                if column in hardware_df
            ]
            if visible_columns:
                st.dataframe(hardware_df[visible_columns], hide_index=True)


def render_observations(observations_df: pd.DataFrame, selected_variables: list[str]) -> None:
    if observations_df.empty:
        st.info("No observations in the selected range.")
        return

    available_variables = [variable for variable in selected_variables if variable in observations_df.columns]
    if available_variables:
        long_df = observations_df.melt(
            id_vars=["observed_at_utc"],
            value_vars=available_variables,
            var_name="Variable",
            value_name="Value",
        ).dropna()
        long_df["Variable"] = long_df["Variable"].map(lambda value: LABELS.get(value, value))
        figure = px.line(long_df, x="observed_at_utc", y="Value", color="Variable", markers=True)
        figure.update_layout(xaxis_title="Observed UTC", yaxis_title="Value", legend_title_text="")
        st.plotly_chart(figure, width="stretch")
    else:
        st.warning("Select at least one available variable.")

    hourly_profile = build_hourly_profile(observations_df, available_variables)
    if not hourly_profile.empty:
        hourly_long_df = hourly_profile.melt(
            id_vars=["hour"],
            value_vars=[variable for variable in available_variables if variable in hourly_profile.columns],
            var_name="Variable",
            value_name="Hourly mean",
        ).dropna()
        hourly_long_df["Variable"] = hourly_long_df["Variable"].map(lambda value: LABELS.get(value, value))
        with st.container(border=True):
            st.subheader("Hourly profile")
            hourly_figure = px.line(hourly_long_df, x="hour", y="Hourly mean", color="Variable", markers=True)
            hourly_figure.update_layout(xaxis_title="Hour UTC", yaxis_title="Hourly mean", legend_title_text="")
            st.plotly_chart(hourly_figure, width="stretch")

    rain_accumulation = build_rain_accumulation(observations_df)
    if not rain_accumulation.empty:
        with st.container(border=True):
            st.subheader("Rain accumulation")
            rain_figure = px.line(
                rain_accumulation,
                x="observed_at_utc",
                y="rain_day_mm",
                markers=True,
            )
            rain_figure.update_layout(xaxis_title="Observed UTC", yaxis_title="Daily rain (mm)")
            st.plotly_chart(rain_figure, width="stretch")

    with st.container(border=True):
        st.subheader("Observation table")
        st.dataframe(observations_df, hide_index=True)
        add_csv_download(observations_df, "Download observations CSV", "argos_observations.csv")


def render_summaries(daily_df: pd.DataFrame, weekly_df: pd.DataFrame) -> None:
    monthly_df = build_monthly_summary(daily_df)
    seasonal_df = build_seasonal_summary(daily_df)
    annual_df = build_annual_summary(daily_df)
    daily_tab, weekly_tab, monthly_tab, seasonal_tab, annual_tab = st.tabs(
        ["Daily", "Weekly", "Monthly", "Seasonal", "Annual"]
    )

    with daily_tab:
        render_summary_table(daily_df, "Daily summary")

    with weekly_tab:
        render_summary_table(weekly_df, "Weekly summary")

    with monthly_tab:
        render_summary_table(monthly_df, "Monthly summary")

    with seasonal_tab:
        render_summary_table(seasonal_df, "Seasonal summary")

    with annual_tab:
        render_summary_table(annual_df, "Annual summary")


def render_summary_table(frame: pd.DataFrame, title: str) -> None:
    if frame.empty:
        st.info(f"No {title.lower()} data in the selected range.")
        return

    with st.container(border=True):
        st.subheader(title)
        st.dataframe(frame, hide_index=True)
        add_csv_download(frame, f"Download {title.lower()} CSV", f"argos_{title.lower().replace(' ', '_')}.csv")
        if "period_start" in frame and "outdoor_temperature_mean_c" in frame:
            st.line_chart(
                frame[["period_start", "outdoor_temperature_mean_c"]].dropna(),
                x="period_start",
                y="outdoor_temperature_mean_c",
                x_label="Period",
                y_label="deg C",
            )
        if "period_start" in frame and "rain_day_max_mm" in frame:
            st.bar_chart(
                frame[["period_start", "rain_day_max_mm"]].dropna(),
                x="period_start",
                y="rain_day_max_mm",
                x_label="Period",
                y_label="mm",
            )


def render_trends(observations_df: pd.DataFrame, selected_variables: list[str]) -> None:
    if observations_df.empty:
        st.info("No observations in the selected range.")
        return

    numeric_variables = [
        variable
        for variable in selected_variables
        if variable in observations_df.columns and pd.api.types.is_numeric_dtype(observations_df[variable])
    ]
    if not numeric_variables:
        st.info("Select at least one numeric variable in the sidebar.")
        return

    with st.container(horizontal=True, vertical_alignment="bottom"):
        variable = st.selectbox(
            "Trend variable",
            options=numeric_variables,
            format_func=lambda value: LABELS.get(value, value),
        )
        rolling_window = st.slider("Moving average window", min_value=2, max_value=60, value=10)

    trend_df, summary = build_trend_frame(observations_df, variable=variable, rolling_window=rolling_window)
    if trend_df.empty:
        st.info("No valid values for the selected variable.")
        return

    with st.container(horizontal=True):
        st.metric("Samples", summary.sample_count, border=True)
        st.metric("Mean", format_number(summary.mean, ""), border=True)
        st.metric("Slope / sample", format_number(summary.slope_per_sample, ""), border=True)
        st.metric("Slope / day", format_number(summary.slope_per_day, ""), border=True)
        st.metric("R2", format_number(summary.r_squared, ""), border=True)
        st.metric("Estimated change", format_number(summary.estimated_change, ""), border=True)

    plot_df = trend_df.melt(
        id_vars=["observed_at_utc"],
        value_vars=["value", "rolling_mean", "trend_line"],
        var_name="Series",
        value_name="Value",
    ).dropna()
    plot_df["Series"] = plot_df["Series"].map(
        {"value": "Value", "rolling_mean": "Moving average", "trend_line": "Linear trend"}
    )
    figure = px.line(plot_df, x="observed_at_utc", y="Value", color="Series", markers=True)
    figure.update_layout(xaxis_title="Observed UTC", yaxis_title=LABELS.get(variable, variable), legend_title_text="")
    st.plotly_chart(figure, width="stretch")

    anomaly = trend_df[["observed_at_utc", "anomaly"]].dropna()
    if not anomaly.empty:
        anomaly_figure = px.bar(anomaly, x="observed_at_utc", y="anomaly")
        anomaly_figure.update_layout(xaxis_title="Observed UTC", yaxis_title="Anomaly from selected period mean")
        st.plotly_chart(anomaly_figure, width="stretch")

    descriptive_df = build_descriptive_statistics(observations_df, numeric_variables, LABELS)
    if not descriptive_df.empty:
        with st.container(border=True):
            st.subheader("Descriptive statistics")
            st.dataframe(descriptive_df, hide_index=True)
            add_csv_download(descriptive_df, "Download descriptive statistics CSV", "argos_descriptive_statistics.csv")

    with st.container(border=True):
        st.subheader("Trend data")
        st.dataframe(trend_df, hide_index=True)
        add_csv_download(trend_df, "Download trend CSV", "argos_trend.csv")


def render_aemet(client: ArgosApiClient, *, start_date: str, end_date: str) -> None:
    st.subheader("AEMET")
    settings = get_settings()
    station_id = DEFAULT_AEMET_STATION

    try:
        stations = cached_aemet_stations(client.base_url)
        latest_sync = cached_latest_aemet_sync(client.base_url, station_id)
        bounds = cached_aemet_bounds(client.base_url, station_id)
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    station = next((item for item in stations if item.get("external_id") == station_id), None)
    query_start, query_end = render_aemet_date_range_selector(
        global_start=start_date,
        global_end=end_date,
        bounds=bounds,
    )
    try:
        records = cached_aemet_observations(client.base_url, station_id, query_start, query_end)
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    frame = dataframe_from_records(records, "observation_date")

    station_name = station.get("name") if station else "Álora"
    latest_sync_label = format_datetime(latest_sync.get("finished_at") if latest_sync else None)
    st.caption(
        f"{station_name} ({station_id}) · {query_start} a {query_end} · {len(frame)} registros · "
        f"última sync: {latest_sync_label}"
    )

    with st.expander("Actualizar datos", expanded=False):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            station_id = st.text_input("Indicativo", value=station_id, max_chars=16, key="aemet_station_update")
            lookback_days = st.number_input(
                "Días a refrescar",
                min_value=1,
                max_value=366,
                value=settings.aemet_sync_lookback_days,
                step=1,
            )
            if st.button("Actualizar", icon=":material/sync:", type="primary"):
                run_aemet_sync_from_dashboard(station_id=station_id, lookback_days=int(lookback_days))

        csv_path = st.text_input("CSV histórico local", value=settings.aemet_seed_csv_path or "")
        if st.button("Importar CSV histórico", icon=":material/upload_file:", type="secondary"):
            run_aemet_csv_import_from_dashboard(station_id=station_id, path=csv_path)

        with st.container(horizontal=True, vertical_alignment="bottom"):
            history_start = st.date_input("Inicio histórico", value=settings.aemet_backfill_start_date)
            history_end = st.date_input("Fin histórico", value=date.today())
            block_days = st.number_input(
                "Días por bloque",
                min_value=1,
                max_value=366,
                value=settings.aemet_block_days,
                step=1,
            )
            if st.button("Descargar histórico", icon=":material/download:", type="secondary"):
                run_aemet_backfill_from_dashboard(
                    station_id=station_id,
                    start=history_start.isoformat(),
                    end=history_end.isoformat(),
                    block_days=int(block_days),
                )

    if frame.empty:
        st.info("No hay datos AEMET guardados para el rango seleccionado.")
        return

    render_aemet_charts(frame)

    if station is not None:
        with st.expander("Detalles de la estación", expanded=False):
            station_df = pd.DataFrame.from_records([station])
            st.dataframe(station_df, hide_index=True)

    with st.container(border=True):
        st.subheader("Serie diaria")
        visible_columns = [
            column
            for column in ["observation_date", *AEMET_LABELS, "precipitation_trace", "quality_flag"]
            if column in frame
        ]
        st.dataframe(frame[visible_columns], hide_index=True)
        add_csv_download(frame, "Descargar AEMET CSV", "argos_aemet_daily.csv")


def run_aemet_sync_from_dashboard(*, station_id: str, lookback_days: int) -> None:
    try:
        with st.spinner("Actualizando AEMET..."):
            settings = get_settings()
            with get_sessionmaker()() as session:
                result = AemetImportService(
                    session=session,
                    client=AemetClient.from_settings(settings),
                    settings=settings,
                ).sync(station_id=station_id, lookback_days=lookback_days)
    except (AemetConfigError, AemetImportRangeError, RuntimeError) as exc:
        st.error(str(exc))
        return
    st.cache_data.clear()
    st.success(format_aemet_import_result(result_to_dict(result)))


def run_aemet_backfill_from_dashboard(*, station_id: str, start: str, end: str, block_days: int) -> None:
    try:
        with st.spinner("Descargando histórico AEMET..."):
            settings = get_settings()
            with get_sessionmaker()() as session:
                result = AemetImportService(
                    session=session,
                    client=AemetClient.from_settings(settings),
                    settings=settings,
                ).backfill(
                    station_id=station_id,
                    start=date.fromisoformat(start),
                    end=date.fromisoformat(end),
                    block_days=block_days,
                )
    except (AemetConfigError, AemetImportRangeError, RuntimeError, ValueError) as exc:
        st.error(str(exc))
        return
    st.cache_data.clear()
    st.success(format_aemet_import_result(result_to_dict(result)))


def run_aemet_csv_import_from_dashboard(*, station_id: str, path: str) -> None:
    if not path.strip():
        st.warning("Indica la ruta del CSV histórico.")
        return
    try:
        with st.spinner("Importando CSV histórico AEMET..."):
            settings = get_settings()
            with get_sessionmaker()() as session:
                result = AemetImportService(
                    session=session,
                    client=AemetClient(base_url=settings.aemet_base_url, api_key="csv-import"),
                    settings=settings,
                ).import_csv(path=Path(path.strip()), station_id=station_id)
    except (AemetImportRangeError, RuntimeError) as exc:
        st.error(str(exc))
        return
    st.cache_data.clear()
    st.success(format_aemet_import_result(result_to_dict(result)))


def render_aemet_charts(frame: pd.DataFrame) -> None:
    variables = [column for column in AEMET_LABELS if column in frame and pd.api.types.is_numeric_dtype(frame[column])]
    selected = st.multiselect(
        "Variables AEMET",
        options=variables,
        default=[item for item in ("temperature_mean_c", "temperature_min_c", "temperature_max_c") if item in variables],
        format_func=lambda value: AEMET_LABELS.get(value, value),
    )
    if selected:
        plot_df = frame.melt(
            id_vars=["observation_date"],
            value_vars=selected,
            var_name="Variable",
            value_name="Valor",
        ).dropna()
        plot_df["Variable"] = plot_df["Variable"].map(lambda value: AEMET_LABELS.get(value, value))
        figure = px.line(plot_df, x="observation_date", y="Valor", color="Variable", markers=True)
        figure.update_layout(xaxis_title="Fecha", yaxis_title="Valor", legend_title_text="")
        st.plotly_chart(figure, width="stretch")

    if "precipitation_mm" in frame:
        rain_df = frame[["observation_date", "precipitation_mm"]].dropna()
        if not rain_df.empty:
            rain_figure = px.bar(rain_df, x="observation_date", y="precipitation_mm")
            rain_figure.update_layout(xaxis_title="Fecha", yaxis_title="Precipitación (mm)")
            st.plotly_chart(rain_figure, width="stretch")


def resolve_aemet_range(*, start_date: str, end_date: str, bounds: dict[str, Any]) -> tuple[str, str, bool]:
    first = bounds.get("first_date")
    last = bounds.get("last_date")
    if not first or not last:
        return start_date, end_date, True
    if start_date <= last and end_date >= first:
        return max(start_date, first), min(end_date, last), True
    last_date = date.fromisoformat(last)
    fallback_start = max(date.fromisoformat(first), last_date - timedelta(days=365))
    return fallback_start.isoformat(), last, False


def render_aemet_date_range_selector(*, global_start: str, global_end: str, bounds: dict[str, Any]) -> tuple[str, str]:
    first = bounds.get("first_date")
    last = bounds.get("last_date")
    if not first or not last:
        return global_start, global_end

    first_date = date.fromisoformat(first)
    last_date = date.fromisoformat(last)
    selected = st.date_input(
        "Rango AEMET",
        value=(first_date, last_date),
        min_value=first_date,
        max_value=last_date,
        key="aemet_date_range",
    )
    if isinstance(selected, tuple) and len(selected) == 2:
        start, end = selected
    else:
        start = end = last_date
    return start.isoformat(), end.isoformat()


def render_satellite_date_range_selector(*, global_start: str, global_end: str, bounds: dict[str, Any]) -> tuple[str, str]:
    first = bounds.get("first_date")
    last = bounds.get("last_date")
    if not first or not last:
        return global_start, global_end

    first_date = date.fromisoformat(first)
    last_date = date.fromisoformat(last)
    selected = st.date_input(
        "Rango satelital",
        value=(first_date, last_date),
        min_value=first_date,
        max_value=last_date,
        key="satellite_date_range",
    )
    if isinstance(selected, tuple) and len(selected) == 2:
        start, end = selected
    else:
        start = end = last_date
    return start.isoformat(), end.isoformat()


def satellite_day_bounds(start: str, end: str) -> tuple[str, str]:
    start_iso = datetime.combine(date.fromisoformat(start), time.min, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    end_iso = datetime.combine(date.fromisoformat(end), time.max, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return start_iso, end_iso


def satellite_frame_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        return frame
    if "acquisition_time" in frame:
        frame["acquisition_time"] = pd.to_datetime(frame["acquisition_time"], format="ISO8601")
    if "metric_code" in frame:
        frame["metric_code"] = frame["metric_code"].map(lambda value: str(value).lower())
        frame["metric"] = frame["metric_code"].map(lambda value: SATELLITE_LABELS.get(value, value.upper()))
    return frame


def render_satellite(client: ArgosApiClient, *, start_iso: str, end_iso: str) -> None:
    st.subheader("Observación satelital")
    try:
        status = cached_satellite_status(client.base_url)
        latest = cached_satellite_latest(client.base_url)
        zones = cached_satellite_zones(client.base_url)
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    status_value = status.get("status", "unknown")
    state_labels = {
        "disabled": "No configurado",
        "not_configured": "No configurado",
        "ready": "Configurado",
        "running": "Actualizando",
        "degraded": "Última actualización fallida",
        "error": "Última actualización fallida",
    }

    if status_value in {"disabled", "not_configured"}:
        st.caption(status.get("message") or state_labels.get(status_value, status_value))
        if not status.get("geometry_defined"):
            st.info("Geometría no definida. Configure ARGOS_SATELLITE_AOI_GEOJSON con un polígono GeoJSON WGS84.")
        if not status.get("credentials_available"):
            st.info("Credenciales no disponibles. Configure COPERNICUS_CLIENT_ID y COPERNICUS_CLIENT_SECRET.")
        return

    quality_filter = st.selectbox(
        "Calidad satelital",
        ["all", "valid", "partial", "invalid"],
        format_func=lambda value: SATELLITE_QUALITY_LABELS.get(value, value),
        key="satellite_quality_filter",
    )
    quality_status = None if quality_filter == "all" else quality_filter
    try:
        bounds = cached_satellite_bounds(client.base_url, quality_status)
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    query_start, query_end = render_satellite_date_range_selector(
        global_start=start_iso[:10],
        global_end=end_iso[:10],
        bounds=bounds,
    )
    range_start_iso, range_end_iso = satellite_day_bounds(query_start, query_end)
    try:
        rows = cached_satellite_export_rows(
            client.base_url,
            range_start_iso,
            range_end_iso,
            quality_status,
        )
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    frame = satellite_frame_from_rows(rows)
    acquisition_count = int(frame["acquisition_time"].nunique()) if "acquisition_time" in frame else 0
    zone_name = next((str(zone.get("name")) for zone in zones if zone.get("enabled")), "Finca")
    latest_update_label = format_datetime(status.get("latest_update_time"))
    st.caption(
        f"{zone_name} · {query_start} a {query_end} · {acquisition_count} adquisiciones · "
        f"{len(frame)} métricas · última actualización: {latest_update_label}"
    )

    with st.expander("Actualizar datos", expanded=False):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            force = st.checkbox("Forzar reproceso", value=False, key="satellite_force_update")
            dry_run = st.checkbox("Dry-run", value=False, key="satellite_dry_run_update")
            if st.button("Actualizar", icon=":material/sync:", type="primary"):
                run_satellite_update_from_dashboard(client=client, force=force, dry_run=dry_run)

        with st.container(horizontal=True, vertical_alignment="bottom"):
            history_start = st.date_input("Inicio histórico", value=date(2021, 1, 1), key="satellite_history_start")
            history_end = st.date_input("Fin histórico", value=date.today(), key="satellite_history_end")
            history_dry_run = st.checkbox("Dry-run histórico", value=True, key="satellite_history_dry_run")
            if st.button("Descargar histórico", icon=":material/download:", type="secondary"):
                run_satellite_backfill_from_dashboard(
                    client=client,
                    start=history_start.isoformat(),
                    end=history_end.isoformat(),
                    force=force,
                    dry_run=history_dry_run,
                )

    if frame.empty:
        st.info("No hay observaciones satelitales guardadas para el rango seleccionado.")
        return

    render_satellite_charts(frame)

    details = []
    if latest is not None:
        details.append(
            {
                "Última adquisición": format_datetime(latest.get("acquisition_time")),
                "Calidad": SATELLITE_QUALITY_LABELS.get(str(latest.get("quality_status")), latest.get("quality_status")),
                "Píxeles válidos": format_percent(latest.get("valid_pixel_fraction")),
                "Nubosidad metadatos": format_percent_100(latest.get("cloud_cover_metadata")),
                "Estado": state_labels.get(status_value, status_value),
                "Observaciones": status.get("observation_count", 0),
            }
        )
    if details:
        with st.expander("Detalles satelitales", expanded=False):
            st.dataframe(pd.DataFrame.from_records(details), hide_index=True)

    with st.container(border=True):
        st.subheader("Serie satelital")
        visible_columns = [
            column
            for column in [
                "acquisition_time",
                "zone_name",
                "metric_code",
                "mean",
                "median",
                "minimum",
                "maximum",
                "standard_deviation",
                "percentile_10",
                "percentile_25",
                "percentile_75",
                "percentile_90",
                "valid_pixel_fraction",
                "cloud_cover_metadata",
                "quality_status",
                "processing_version",
            ]
            if column in frame
        ]
        st.dataframe(frame[visible_columns], hide_index=True)
        add_csv_download(frame[visible_columns], "Descargar satélite CSV", "argos_satellite_series.csv")


def render_satellite_charts(frame: pd.DataFrame) -> None:
    if "metric_code" not in frame or "mean" not in frame:
        return
    metrics = [metric for metric in SATELLITE_LABELS if metric in set(frame["metric_code"])]
    selected = st.multiselect(
        "Índices satelitales",
        options=metrics,
        default=metrics,
        format_func=lambda value: SATELLITE_LABELS.get(value, value.upper()),
    )
    if selected:
        plot_df = frame[frame["metric_code"].isin(selected)].copy()
        plot_df["Índice"] = plot_df["metric_code"].map(lambda value: SATELLITE_LABELS.get(value, value.upper()))
        figure = px.line(
            plot_df,
            x="acquisition_time",
            y="mean",
            color="Índice",
            markers=True,
            hover_data=[
                "median",
                "percentile_25",
                "percentile_75",
                "valid_pixel_fraction",
                "cloud_cover_metadata",
                "quality_status",
            ],
        )
        figure.update_layout(xaxis_title="Fecha", yaxis_title="Media", legend_title_text="")
        st.plotly_chart(figure, width="stretch")

    quality_df = (
        frame[["acquisition_time", "valid_pixel_fraction", "quality_status"]]
        .drop_duplicates(subset=["acquisition_time"])
        .dropna(subset=["valid_pixel_fraction"])
    )
    if not quality_df.empty:
        quality_figure = px.bar(
            quality_df,
            x="acquisition_time",
            y="valid_pixel_fraction",
            color="quality_status",
        )
        quality_figure.update_layout(
            xaxis_title="Fecha",
            yaxis_title="Fracción de píxeles válidos",
            legend_title_text="Calidad",
        )
        st.plotly_chart(quality_figure, width="stretch")


def run_satellite_update_from_dashboard(*, client: ArgosApiClient, force: bool, dry_run: bool) -> None:
    try:
        with st.spinner("Actualizando observación satelital..."):
            api_client = ArgosApiClient(
                base_url=client.base_url,
                admin_token=client.admin_token,
                timeout_seconds=600,
            )
            result = api_client.update_satellite(force=force, dry_run=dry_run)
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    st.cache_data.clear()
    st.success(format_satellite_ingestion_result(result))


def run_satellite_backfill_from_dashboard(
    *,
    client: ArgosApiClient,
    start: str,
    end: str,
    force: bool,
    dry_run: bool,
) -> None:
    try:
        with st.spinner("Descargando histórico satelital..."):
            api_client = ArgosApiClient(
                base_url=client.base_url,
                admin_token=client.admin_token,
                timeout_seconds=600,
            )
            range_start, range_end = satellite_day_bounds(start, end)
            result = api_client.backfill_satellite(
                start=range_start,
                end=range_end,
                force=force,
                dry_run=dry_run,
            )
    except (ArgosApiError, ValueError) as exc:
        st.error(str(exc))
        return
    st.cache_data.clear()
    st.success(format_satellite_ingestion_result(result))


def render_valves(
    client: ArgosNodeClient,
    *,
    valve_opening_duration_s: float,
    valve_closing_duration_s: float,
) -> None:
    render_valve_control(
        client,
        valve_id=1,
        name="Electrovalve 1",
        valve_opening_duration_s=valve_opening_duration_s,
        valve_closing_duration_s=valve_closing_duration_s,
    )


def render_valve_control(
    client: ArgosNodeClient,
    *,
    valve_id: int,
    name: str,
    valve_opening_duration_s: float,
    valve_closing_duration_s: float,
) -> None:
    keys = valve_session_keys(valve_id)
    initialize_valve_session(keys)
    update_timed_valve_state(keys)

    phase = st.session_state[keys["phase"]]
    if phase in {"unknown", "closed", "open"}:
        refresh_valve_from_backend(client, valve_id=valve_id, keys=keys)
        phase = st.session_state[keys["phase"]]

    with st.container(border=True):
        st.subheader(name)
        st.metric("State", valve_phase_label(phase), border=True)
        render_valve_status_line(keys, phase)
        render_valve_progress(keys, phase, valve_opening_duration_s, valve_closing_duration_s)
        render_valve_primary_action(valve_id, keys, phase)
        render_valve_message(st.session_state[keys["message"]], st.session_state[keys["error"]])

    if phase in {"sending_open_command", "sending_close_command"} and not st.session_state[keys["command_in_flight"]]:
        run_valve_command(
            client,
            valve_id=valve_id,
            keys=keys,
            command="open" if phase == "sending_open_command" else "close",
            movement_duration_s=valve_opening_duration_s if phase == "sending_open_command" else valve_closing_duration_s,
        )

    if st.session_state[keys["raw_response"]]:
        with st.expander("Raw valve response"):
            st.json(st.session_state[keys["raw_response"]])
            st.caption(
                "The exact relay switching instant is not observable from the dashboard yet. "
                "Movement start is approximated by the HTTP response reception time. "
                "Do not attribute the observed pre-movement delay to a specific component until argos-node logs it "
                "or returns an applied_at field after physically applying the relay state."
            )
            st.json(st.session_state[keys["timing"]])

    if st.session_state[keys["phase"]] in {"opening", "closing"}:
        monotonic_time.sleep(1)
        st.rerun()


def valve_session_keys(valve_id: int) -> dict[str, str]:
    prefix = f"valve_{valve_id}"
    return {
        "phase": f"{prefix}_phase",
        "last_confirmed_phase": f"{prefix}_last_confirmed_phase",
        "raw_response": f"{prefix}_raw_response",
        "message": f"{prefix}_message",
        "error": f"{prefix}_error",
        "timing": f"{prefix}_timing",
        "command_in_flight": f"{prefix}_command_in_flight",
        "movement_started_monotonic": f"{prefix}_movement_started_monotonic",
        "movement_complete_monotonic": f"{prefix}_movement_complete_monotonic",
        "movement_complete_at": f"{prefix}_movement_complete_at",
    }


def initialize_valve_session(keys: dict[str, str]) -> None:
    st.session_state.setdefault(keys["phase"], "unknown")
    st.session_state.setdefault(keys["last_confirmed_phase"], "unknown")
    st.session_state.setdefault(keys["raw_response"], None)
    st.session_state.setdefault(keys["message"], None)
    st.session_state.setdefault(keys["error"], None)
    st.session_state.setdefault(keys["timing"], {})
    st.session_state.setdefault(keys["command_in_flight"], False)
    st.session_state.setdefault(keys["movement_started_monotonic"], None)
    st.session_state.setdefault(keys["movement_complete_monotonic"], None)
    st.session_state.setdefault(keys["movement_complete_at"], None)


def update_timed_valve_state(keys: dict[str, str]) -> None:
    phase = st.session_state[keys["phase"]]
    if phase not in {"opening", "closing"}:
        return

    movement_complete = st.session_state[keys["movement_complete_monotonic"]]
    if movement_complete is None or monotonic_time.monotonic() < movement_complete:
        return

    final_phase = "open" if phase == "opening" else "closed"
    st.session_state[keys["phase"]] = final_phase
    st.session_state[keys["last_confirmed_phase"]] = final_phase
    st.session_state[keys["message"]] = (
        f"Valve is estimated {final_phase}. No independent end-stop signal is available."
    )


def refresh_valve_from_backend(client: ArgosNodeClient, *, valve_id: int, keys: dict[str, str]) -> None:
    try:
        state = client.get_valve(valve_id)
    except ArgosNodeError as exc:
        st.session_state[keys["phase"]] = "error"
        st.session_state[keys["error"]] = str(exc)
        return

    if state is None:
        st.session_state[keys["phase"]] = "unknown"
        return

    phase = valve_phase_from_response(state)
    st.session_state[keys["raw_response"]] = state
    st.session_state[keys["phase"]] = phase
    if phase in {"open", "closed"}:
        st.session_state[keys["last_confirmed_phase"]] = phase
        st.session_state[keys["error"]] = None


def render_valve_status_line(keys: dict[str, str], phase: str) -> None:
    if phase == "sending_open_command":
        st.info("Sending open command...")
    elif phase == "sending_close_command":
        st.info("Sending close command...")
    elif phase == "opening":
        st.info("Opening...")
    elif phase == "closing":
        st.info("Closing...")
    elif phase == "open":
        st.caption("Open is estimated after the configured movement duration.")
    elif phase == "closed":
        st.caption("Closed is estimated after the configured movement duration.")
    elif phase == "error":
        st.caption(f"Last confirmed state: {valve_phase_label(st.session_state[keys['last_confirmed_phase']])}")


def render_valve_progress(
    keys: dict[str, str],
    phase: str,
    valve_opening_duration_s: float,
    valve_closing_duration_s: float,
) -> None:
    if phase not in {"opening", "closing"}:
        return

    duration = valve_opening_duration_s if phase == "opening" else valve_closing_duration_s
    complete_at = st.session_state[keys["movement_complete_monotonic"]]
    if complete_at is None:
        return

    remaining_s = max(0.0, complete_at - monotonic_time.monotonic())
    elapsed_s = max(0.0, duration - remaining_s)
    progress = 1.0 if duration <= 0 else min(1.0, elapsed_s / duration)
    st.progress(progress, text=f"{remaining_s:.0f} s remaining")


def render_valve_primary_action(valve_id: int, keys: dict[str, str], phase: str) -> None:
    if phase == "closed":
        clicked = st.button("Open valve", icon=":material/valve:", type="primary", key=f"valve_{valve_id}_open")
        if clicked:
            start_valve_command(keys, "sending_open_command", "dashboard_open_click")
    elif phase == "open":
        clicked = st.button("Close valve", icon=":material/close:", type="primary", key=f"valve_{valve_id}_close")
        if clicked:
            start_valve_command(keys, "sending_close_command", "dashboard_close_click")
    elif phase == "sending_open_command":
        st.button("Sending open command...", disabled=True, icon=":material/sync:", key=f"valve_{valve_id}_sending_open")
    elif phase == "sending_close_command":
        st.button(
            "Sending close command...",
            disabled=True,
            icon=":material/sync:",
            key=f"valve_{valve_id}_sending_close",
        )
    elif phase == "opening":
        st.button("Opening...", disabled=True, icon=":material/hourglass:", key=f"valve_{valve_id}_opening")
    elif phase == "closing":
        st.button("Closing...", disabled=True, icon=":material/hourglass:", key=f"valve_{valve_id}_closing")
    else:
        st.button("Valve unavailable", disabled=True, icon=":material/error:", key=f"valve_{valve_id}_unavailable")


def start_valve_command(keys: dict[str, str], phase: str, event: str) -> None:
    ui_clicked_at = datetime.now(UTC).isoformat()
    st.session_state[keys["phase"]] = phase
    st.session_state[keys["message"]] = None
    st.session_state[keys["error"]] = None
    st.session_state[keys["command_in_flight"]] = False
    st.session_state[keys["timing"]] = {
        "ui_clicked_at": ui_clicked_at,
        "request_started_at": None,
        "response_received_at": None,
        "request_elapsed_ms": None,
        "movement_estimated_until": None,
    }
    log_valve_timing(event, st.session_state[keys["timing"]])
    st.rerun()


def run_valve_command(
    client: ArgosNodeClient,
    *,
    valve_id: int,
    keys: dict[str, str],
    command: str,
    movement_duration_s: float,
) -> None:
    st.session_state[keys["command_in_flight"]] = True
    request_started_monotonic = monotonic_time.monotonic()
    request_started_at = datetime.now(UTC).isoformat()
    st.session_state[keys["timing"]]["request_started_at"] = request_started_at
    log_valve_timing("request_started", st.session_state[keys["timing"]])
    try:
        response = client.open_valve(valve_id) if command == "open" else client.close_valve(valve_id)
        response_received_at = datetime.now(UTC).isoformat()
        request_elapsed_ms = round((monotonic_time.monotonic() - request_started_monotonic) * 1000)
        st.session_state[keys["timing"]]["response_received_at"] = response_received_at
        st.session_state[keys["timing"]]["request_elapsed_ms"] = request_elapsed_ms
        log_valve_timing("response_received", st.session_state[keys["timing"]])
        if response is not None:
            st.session_state[keys["raw_response"]] = response

        start_estimated_movement(keys, command=command, movement_duration_s=movement_duration_s)
    except ArgosNodeError as exc:
        st.session_state[keys["phase"]] = "error"
        st.session_state[keys["message"]] = None
        st.session_state[keys["error"]] = f"{command.capitalize()} command failed: {exc}"
        log_valve_timing("command_failed", st.session_state[keys["timing"]])
    finally:
        st.session_state[keys["command_in_flight"]] = False
        st.rerun()


def start_estimated_movement(keys: dict[str, str], *, command: str, movement_duration_s: float) -> None:
    movement_start_monotonic = monotonic_time.monotonic()
    estimated_complete_at = datetime.now(UTC) + timedelta(seconds=movement_duration_s)
    st.session_state[keys["movement_started_monotonic"]] = movement_start_monotonic
    st.session_state[keys["movement_complete_monotonic"]] = movement_start_monotonic + movement_duration_s
    st.session_state[keys["movement_complete_at"]] = estimated_complete_at.isoformat()
    st.session_state[keys["timing"]]["movement_estimated_until"] = estimated_complete_at.isoformat()
    st.session_state[keys["phase"]] = "opening" if command == "open" else "closing"
    st.session_state[keys["message"]] = None
    st.session_state[keys["error"]] = None
    log_valve_timing("movement_estimate_started", st.session_state[keys["timing"]])


def render_valve_message(message: str | None, error: str | None) -> None:
    if error:
        st.error(error)
    elif message:
        st.success(message)


def log_valve_timing(event: str, timing: dict[str, Any]) -> None:
    logger.info("valve timing %s: %s", event, timing)


def render_quality(client: ArgosApiClient) -> None:
    if not client.admin_token:
        st.info("Enter the admin token in the sidebar to inspect operational data.")
        return

    try:
        gaps = client.get_data_gaps()
        events = client.get_events(limit=20)
        unknown_fields = client.get_unknown_fields()
        raw_reports = client.get_raw_reports(limit=10)
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    gap_df = dataframe_from_records(gaps, "gap_start")
    event_df = dataframe_from_records(events, "created_at")
    unknown_df = pd.DataFrame.from_records(unknown_fields)
    raw_df = build_raw_report_table(raw_reports)
    raw_payload_preview = latest_payload_preview(raw_reports)

    with st.container(horizontal=True):
        st.metric("Open gaps", len(gap_df), border=True)
        st.metric("Recent events", len(event_df), border=True)
        st.metric("Unknown fields", len(unknown_df), border=True)
        st.metric("Raw reports", len(raw_df), border=True)

    with st.container(border=True):
        st.subheader("Data gaps")
        st.dataframe(gap_df, hide_index=True)

    with st.container(border=True):
        st.subheader("Recent ingestion events")
        st.dataframe(event_df, hide_index=True)

    with st.container(border=True):
        st.subheader("Unknown fields")
        st.dataframe(unknown_df, hide_index=True)

    with st.container(border=True):
        st.subheader("Recent raw reports")
        if raw_payload_preview is not None:
            with st.expander("Latest redacted payload"):
                st.json(raw_payload_preview)
        st.dataframe(raw_df, hide_index=True)


def add_csv_download(frame: pd.DataFrame, label: str, file_name: str) -> None:
    if frame.empty:
        return
    st.download_button(
        label,
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
        icon=":material/download:",
    )


def format_number(value: Any, unit: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        suffix = f" {unit}" if unit else ""
        return f"{value:.2f}{suffix}"
    return str(value)


def format_datetime(value: Any) -> str:
    if not value:
        return "-"
    return str(value).replace("T", " ").replace("Z", " UTC")


def format_float(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        return f"{value:.3f}"
    return str(value)


def format_percent(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        return f"{value * 100:.0f}%"
    return str(value)


def format_percent_100(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        return f"{value:.0f}%"
    return str(value)


def format_aemet_import_result(result: dict[str, Any]) -> str:
    return (
        f"AEMET {result.get('status', '-')}: "
        f"{result.get('records_received', 0)} recibidos, "
        f"{result.get('inserted', 0)} insertados, "
        f"{result.get('updated', 0)} actualizados, "
        f"{result.get('skipped', 0)} omitidos, "
        f"{len(result.get('errors', []))} errores."
    )


def format_satellite_ingestion_result(result: dict[str, Any]) -> str:
    processing_units = result.get("processing_units")
    units_label = f", {processing_units:.3f} PU" if isinstance(processing_units, int | float) else ""
    return (
        f"Satélite {result.get('status', '-')}: "
        f"{result.get('found_count', 0)} encontradas, "
        f"{result.get('processed_count', 0)} procesadas, "
        f"{result.get('skipped_count', 0)} omitidas, "
        f"{result.get('failed_count', 0)} fallidas"
        f"{units_label}."
    )


def result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "status": result.status,
        "records_received": result.records_received,
        "inserted": result.inserted,
        "updated": result.updated,
        "skipped": result.skipped,
        "errors": result.errors,
    }


def format_valve_state(state: dict[str, Any] | None) -> str:
    if not state:
        return "Unknown"

    for key in ("open", "is_open", "opened", "relay_active", "relay_on", "relay_enabled", "active", "energized"):
        value = state.get(key)
        if isinstance(value, bool):
            return "Open" if value else "Closed"

    for key in ("state", "status", "position"):
        value = state.get(key)
        if value is not None:
            return format_valve_state_value(value)

    return "Available"


def valve_phase_from_response(state: dict[str, Any] | None) -> str:
    state_label = format_valve_state(state)
    if state_label == "Closed":
        return "closed"
    if state_label == "Open":
        return "open"
    return "unknown"


def valve_phase_label(phase: str) -> str:
    labels = {
        "closed": "Closed",
        "sending_open_command": "Sending open command",
        "opening": "Opening",
        "open": "Open",
        "sending_close_command": "Sending close command",
        "closing": "Closing",
        "error": "Error",
        "unknown": "Unknown",
    }
    return labels.get(phase, phase)


def format_valve_state_value(value: Any) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"open", "opened", "true", "1", "on"}:
        return "Open"
    if normalized in {"closed", "close", "false", "0", "off"}:
        return "Closed"
    return str(value)


def valve_action_from_state(state: dict[str, Any] | None) -> str | None:
    phase = valve_phase_from_response(state)
    if phase == "closed":
        return "open"
    if phase == "open":
        return "close"
    return None


def short_identifier(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    if len(text) <= 12:
        return text
    return f"{text[:8]}...{text[-4:]}"


if __name__ == "__main__":
    main()
