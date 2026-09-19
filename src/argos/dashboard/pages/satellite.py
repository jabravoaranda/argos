from __future__ import annotations

from datetime import UTC, date, datetime, time
from html import escape
from typing import Any

import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import streamlit as st

from argos.dashboard.api_client import ArgosApiClient, ArgosApiError
from argos.dashboard.formatting import (
    format_compact_date_range,
    format_compact_local_datetime,
    format_datetime,
    format_percent,
    format_percent_100,
)
from argos.dashboard.ui import add_csv_download


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


@st.cache_data(ttl=60)
def cached_satellite_status(base_url: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_satellite_status()


@st.cache_data(ttl=60)
def cached_satellite_latest(base_url: str, aoi_slug: str | None = None) -> dict[str, Any] | None:
    return ArgosApiClient(base_url=base_url).get_satellite_latest(aoi_slug=aoi_slug)


@st.cache_data(ttl=60)
def cached_satellite_zones(base_url: str) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_satellite_zones()


@st.cache_data(ttl=60)
def cached_satellite_bounds(base_url: str, quality_status: str | None, aoi_slug: str | None) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_satellite_bounds(quality_status=quality_status, aoi_slug=aoi_slug)


@st.cache_data(ttl=60)
def cached_satellite_export_rows(
    base_url: str,
    start: str | None,
    end: str | None,
    quality_status: str | None,
    aoi_slug: str | None,
) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url, timeout_seconds=180).get_satellite_export_json(
        start=start,
        end=end,
        quality_status=quality_status,
        aoi_slug=aoi_slug,
    )


@st.cache_data(ttl=60)
def cached_satellite_timeseries(
    base_url: str,
    metric: str,
    start: str,
    end: str,
    quality_status: str | None,
    aoi_slug: str | None,
) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url, timeout_seconds=60).get_satellite_timeseries(
        metric=metric,
        start=start,
        end=end,
        quality_status=quality_status,
        aoi_slug=aoi_slug,
    )


@st.cache_data(ttl=60)
def cached_satellite_chart_rows(
    base_url: str,
    metrics: tuple[str, ...],
    start: str,
    end: str,
    quality_status: str | None,
    aoi_slug: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in metrics:
        rows.extend(
            ArgosApiClient(base_url=base_url, timeout_seconds=60).get_satellite_export_json(
                start=start,
                end=end,
                quality_status=quality_status,
                aoi_slug=aoi_slug,
                metric=metric,
            )
        )
    return rows


@st.cache_data(ttl=60)
def cached_satellite_latest_per_aoi(base_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for zone in ArgosApiClient(base_url=base_url).get_satellite_zones():
        slug = zone.get("slug")
        if not slug:
            continue
        latest = ArgosApiClient(base_url=base_url).get_satellite_latest(aoi_slug=str(slug))
        if latest is None:
            continue
        rows.append(
            {
                "aoi_slug": slug,
                "zone_name": zone.get("name") or slug,
                "acquisition_time": latest.get("acquisition_time"),
                "quality_status": latest.get("quality_status"),
                "valid_pixel_fraction": latest.get("valid_pixel_fraction"),
                "cloud_cover_metadata": latest.get("cloud_cover_metadata"),
            }
        )
    return rows

def satellite_available_range(*, global_start: str, global_end: str, bounds: dict[str, Any]) -> tuple[str, str]:
    first = bounds.get("first_date")
    last = bounds.get("last_date")
    if not first or not last:
        return global_start, global_end
    return str(first), str(last)


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


def satellite_acquisition_count(frame: pd.DataFrame) -> int:
    if frame.empty or "acquisition_time" not in frame:
        return 0
    group_columns = ["acquisition_time"]
    if "aoi_slug" in frame:
        group_columns.append("aoi_slug")
    return int(frame[group_columns].drop_duplicates().shape[0])


def satellite_aoi_options(*, status: dict[str, Any], zones: list[dict[str, Any]]) -> list[dict[str, str]]:
    options: dict[str, str] = {}
    for zone in zones:
        slug = zone.get("slug")
        name = zone.get("name")
        if slug and name and zone.get("enabled", True):
            options[str(slug)] = str(name)
    for aoi in status.get("aois") or []:
        slug = aoi.get("slug") if isinstance(aoi, dict) else None
        name = aoi.get("name") if isinstance(aoi, dict) else None
        if slug and name:
            options.setdefault(str(slug), str(name))
    return [{"slug": slug, "name": name} for slug, name in options.items()]


def render_satellite(client: ArgosApiClient, *, start_iso: str, end_iso: str) -> None:
    try:
        status = cached_satellite_status(client.base_url)
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
            st.info("Geometría no definida. Configure ARGOS_SATELLITE_AOIS_JSON con los AOIs GeoJSON WGS84.")
        if not status.get("credentials_available"):
            st.info("Credenciales no disponibles. Configure COPERNICUS_CLIENT_ID y COPERNICUS_CLIENT_SECRET.")
        return

    latest_update_label = format_compact_local_datetime(status.get("latest_update_time"))
    latest_update_detail = format_datetime(status.get("latest_update_time"))

    st.html(
        f"""
        <div class="argos-satellite-header">
            <h2>Observación satelital</h2>
            <span title="{escape(latest_update_detail)}">Actualizado {escape(latest_update_label)}</span>
        </div>
        """
    )

    metrics = [metric for metric in SATELLITE_LABELS]
    aoi_options = satellite_aoi_options(status=status, zones=zones)
    selected_aoi_value: str = "__all__"
    with st.container(key="satellite_controls", horizontal=True, vertical_alignment="bottom"):
        if aoi_options:
            aoi_select_options = ["__all__", *[option["slug"] for option in aoi_options]]
            selected_aoi_option: str = st.selectbox(
                "AOI",
                options=aoi_select_options,
                format_func=lambda slug: "Todas"
                if slug == "__all__"
                else next(option["name"] for option in aoi_options if option["slug"] == slug),
                key="satellite_aoi_filter",
                width=230,
            )
            selected_aoi_value = selected_aoi_option
        selected_metrics = st.multiselect(
            "Índices satelitales",
            options=metrics,
            default=metrics,
            format_func=lambda value: SATELLITE_LABELS.get(value, value.upper()),
        )
        quality_filter: str = st.selectbox(
            "Calidad satelital",
            ["all", "valid", "partial", "invalid"],
            format_func=lambda value: SATELLITE_QUALITY_LABELS.get(value, value),
            key="satellite_quality_filter",
            width=230,
        )

    selected_aoi_slug = None if selected_aoi_value == "__all__" else selected_aoi_value
    quality_status = None if quality_filter == "all" else quality_filter
    try:
        latest = cached_satellite_latest(client.base_url, selected_aoi_slug)
        bounds = cached_satellite_bounds(client.base_url, quality_status, selected_aoi_slug)
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    query_start, query_end = satellite_available_range(
        global_start=start_iso[:10],
        global_end=end_iso[:10],
        bounds=bounds,
    )
    range_start_iso, range_end_iso = satellite_day_bounds(query_start, query_end)
    selected_metric_tuple = tuple(selected_metrics)
    try:
        chart_rows = cached_satellite_chart_rows(
            client.base_url,
            selected_metric_tuple,
            range_start_iso,
            range_end_iso,
            quality_status,
            selected_aoi_slug,
        )
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    chart_frame = satellite_frame_from_rows(chart_rows)
    acquisition_count = satellite_acquisition_count(chart_frame)
    zone_name = (
        "Todas"
        if selected_aoi_slug is None
        else next((option["name"] for option in aoi_options if option["slug"] == selected_aoi_slug), "Finca")
    )
    st.html(
        f"""
        <div class="argos-satellite-meta">
            <b>{escape(zone_name)}</b> · <b>Cobertura:</b> {escape(format_compact_date_range(query_start, query_end))} ·
            {acquisition_count} adquisiciones · {len(chart_frame)} métricas · actualizado {escape(latest_update_label)}
        </div>
        """
    )

    if chart_frame.empty:
        st.info("No hay observaciones satelitales guardadas para el rango seleccionado.")
        return

    render_satellite_charts(chart_frame, selected_metrics)

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
            if selected_aoi_slug is None:
                latest_rows = cached_satellite_latest_per_aoi(client.base_url)
                latest_frame = satellite_frame_from_rows(latest_rows)
                if not latest_frame.empty:
                    latest_frame["quality_status"] = latest_frame["quality_status"].map(
                        lambda value: SATELLITE_QUALITY_LABELS.get(str(value), value)
                    )
                    st.dataframe(
                        latest_frame[
                            [
                                column
                                for column in [
                                    "zone_name",
                                    "acquisition_time",
                                    "quality_status",
                                    "valid_pixel_fraction",
                                    "cloud_cover_metadata",
                                ]
                                if column in latest_frame
                            ]
                        ],
                        hide_index=True,
                    )
            else:
                st.dataframe(pd.DataFrame.from_records(details), hide_index=True)

    render_satellite_series_table(
        client=client,
        start=range_start_iso,
        end=range_end_iso,
        quality_status=quality_status,
        aoi_slug=selected_aoi_slug,
    )


def render_satellite_update_popover(client: ArgosApiClient, *, aoi_slug: str | None = None) -> None:
    with st.popover("Descargar de Copernicus", icon=":material/satellite_alt:", width="content"):
        force = st.checkbox("Forzar reproceso", value=False, key="satellite_force_update")
        dry_run = st.checkbox("Dry-run", value=False, key="satellite_dry_run_update")
        if st.button("Actualizar reciente", icon=":material/sync:", type="primary", key="satellite_update_button"):
            run_satellite_update_from_dashboard(client=client, aoi_slug=aoi_slug, force=force, dry_run=dry_run)

        st.caption("Histórico")
        history_start = st.date_input("Inicio histórico", value=date(2021, 1, 1), key="satellite_history_start")
        history_end = st.date_input("Fin histórico", value=date.today(), key="satellite_history_end")
        history_dry_run = st.checkbox("Dry-run histórico", value=True, key="satellite_history_dry_run")
        if st.button("Descargar histórico", icon=":material/download:", type="secondary", key="satellite_backfill_button"):
            run_satellite_backfill_from_dashboard(
                client=client,
                aoi_slug=aoi_slug,
                start=history_start.isoformat(),
                end=history_end.isoformat(),
                force=force,
                dry_run=history_dry_run,
            )


def render_satellite_series_table(
    *,
    client: ArgosApiClient,
    start: str,
    end: str,
    quality_status: str | None,
    aoi_slug: str | None,
) -> None:
    try:
        rows = cached_satellite_export_rows(
            client.base_url,
            start,
            end,
            quality_status,
            aoi_slug,
        )
    except ArgosApiError as exc:
        st.warning(f"No se pudo cargar la tabla satelital completa: {exc}", icon=":material/warning:")
        return

    frame = satellite_frame_from_rows(rows)
    with st.container(border=True):
        st.subheader("Serie satelital")
        visible_columns = [
            column
            for column in [
                "acquisition_time",
                "aoi_slug",
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


def render_satellite_charts(frame: pd.DataFrame, selected: list[str]) -> None:
    if "metric_code" not in frame or "mean" not in frame:
        return
    available_selected = [metric for metric in selected if metric in set(frame["metric_code"])]
    if available_selected:
        plot_df = frame[frame["metric_code"].isin(available_selected)].copy()
        plot_df["Índice"] = plot_df["metric_code"].map(lambda value: SATELLITE_LABELS.get(value, value.upper()))
        has_multiple_aois = "aoi_slug" in plot_df and plot_df["aoi_slug"].dropna().nunique() > 1
        if has_multiple_aois:
            plot_df["Parcela"] = plot_df.get("zone_name", plot_df["aoi_slug"]).fillna(plot_df["aoi_slug"])
            plot_df["Serie"] = plot_df["Parcela"].astype(str) + " · " + plot_df["Índice"].astype(str)
        else:
            plot_df["Serie"] = plot_df["Índice"]
        hover_columns = [
            column
            for column in [
                "zone_name",
                "aoi_slug",
                "median",
                "percentile_25",
                "percentile_75",
                "valid_pixel_fraction",
                "cloud_cover_metadata",
                "quality_status",
            ]
            if column in plot_df
        ]
        figure = px.line(
            plot_df,
            x="acquisition_time",
            y="mean",
            color="Serie",
            line_group="Serie",
            markers=True,
            hover_data=hover_columns,
        )
        figure.update_layout(xaxis_title="Fecha", yaxis_title="Media", legend_title_text="", height=360, margin=dict(t=18))
        st.plotly_chart(figure, width="stretch")

    quality_columns = {"acquisition_time", "valid_pixel_fraction", "quality_status"}
    if quality_columns.issubset(frame.columns):
        quality_group_columns = ["acquisition_time"]
        if "aoi_slug" in frame:
            quality_group_columns.append("aoi_slug")
        quality_df = (
            frame[[*quality_group_columns, "valid_pixel_fraction", "quality_status"]]
            .drop_duplicates(subset=quality_group_columns)
            .dropna(subset=["valid_pixel_fraction"])
        )
    else:
        quality_df = pd.DataFrame()
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
            height=330,
            margin=dict(t=18),
        )
        st.plotly_chart(quality_figure, width="stretch")


def run_satellite_update_from_dashboard(
    *,
    client: ArgosApiClient,
    aoi_slug: str | None,
    force: bool,
    dry_run: bool,
) -> None:
    try:
        with st.spinner("Actualizando observación satelital..."):
            api_client = ArgosApiClient(
                base_url=client.base_url,
                admin_token=client.admin_token,
                timeout_seconds=600,
            )
            result = api_client.update_satellite(aoi_slug=aoi_slug, force=force, dry_run=dry_run)
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    st.cache_data.clear()
    st.success(format_satellite_ingestion_result(result))


def run_satellite_backfill_from_dashboard(
    *,
    client: ArgosApiClient,
    aoi_slug: str | None,
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
                aoi_slug=aoi_slug,
                force=force,
                dry_run=dry_run,
            )
    except (ArgosApiError, ValueError) as exc:
        st.error(str(exc))
        return
    st.cache_data.clear()
    st.success(format_satellite_ingestion_result(result))

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
