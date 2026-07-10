from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import streamlit as st

from argos.dashboard.api_client import ArgosApiClient, ArgosApiError
from argos.dashboard.filters import filter_observations_by_source, observation_source_counts
from argos.dashboard.period_profiles import build_hourly_profile, build_rain_accumulation
from argos.dashboard.raw_reports import build_raw_report_table, latest_payload_preview
from argos.dashboard.statistics import build_descriptive_statistics
from argos.dashboard.summaries import build_annual_summary, build_monthly_summary, build_seasonal_summary
from argos.dashboard.trends import build_trend_frame


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


def main() -> None:
    st.title("ARGOS dashboard")
    st.caption("Agricultural Remote Gateway for Observation and Sensing")

    client, start_iso, end_iso, selected_variables, selected_sources = sidebar()

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

    home_tab, observations_tab, summaries_tab, trends_tab, quality_tab = st.tabs(
        ["Home", "Observations", "Summaries", "Trends", "Quality"]
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

    with quality_tab:
        render_quality(client)


def sidebar() -> tuple[ArgosApiClient, str, str, list[str], list[str]]:
    with st.sidebar:
        st.header("Connection")
        base_url = st.text_input("ARGOS API URL", value="http://127.0.0.1:8080")
        admin_token = st.text_input("Admin token", value="", type="password")

        st.header("Time range")
        today = date.today()
        default_start = today - timedelta(days=1)
        selected_dates = st.date_input("Date range", value=(default_start, today))
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

        if st.button("Refresh data", icon=":material/refresh:"):
            st.cache_data.clear()
            st.rerun()

    return (
        ArgosApiClient(base_url=base_url, admin_token=admin_token or None),
        start_iso,
        end_iso,
        selected_variables,
        list(selected_sources or []),
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


def short_identifier(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    if len(text) <= 12:
        return text
    return f"{text[:8]}...{text[-4:]}"


if __name__ == "__main__":
    main()
