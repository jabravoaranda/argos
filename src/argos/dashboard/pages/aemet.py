from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import streamlit as st

from argos.config.settings import get_settings
from argos.dashboard.api_client import ArgosApiClient, ArgosApiError
from argos.dashboard.dataframes import dataframe_from_records
from argos.dashboard.formatting import format_datetime
from argos.dashboard.ui import add_csv_download
from argos.database.session import get_sessionmaker
from argos.integrations.aemet.client import AemetClient, AemetConfigError
from argos.services.aemet_import import AemetImportRangeError, AemetImportService


DEFAULT_AEMET_STATION = "6127X"
AEMET_BACKFILL_DEFAULT_START = date(1900, 1, 1)

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


def render_aemet(client: ArgosApiClient, *, start_date: str, end_date: str) -> None:
    st.subheader("AEMET")
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


def format_aemet_import_result(result: dict[str, Any]) -> str:
    return (
        f"AEMET {result.get('status', '-')}: "
        f"{result.get('records_received', 0)} recibidos, "
        f"{result.get('inserted', 0)} insertados, "
        f"{result.get('updated', 0)} actualizados, "
        f"{result.get('skipped', 0)} omitidos, "
        f"{len(result.get('errors', []))} errores."
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
