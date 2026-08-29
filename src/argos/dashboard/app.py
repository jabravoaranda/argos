from __future__ import annotations

import base64
import csv
import io
import logging
import math
import time as monotonic_time
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html import escape
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]
from plotly.subplots import make_subplots  # type: ignore[import-untyped]
import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from argos.config.irrigation import (
    ArgosIrrigationConfigError,
    IrrigationSectorId,
    IrrigationSectorValveMapping,
    get_main_irrigation_ev,
    irrigation_sector_mappings,
)
from argos.config.settings import get_settings
from argos.dashboard.api_client import ArgosApiClient, ArgosApiError
from argos.dashboard.argos_node_client import ArgosNodeClient, ArgosNodeError
from argos.dashboard.filters import filter_observations_by_source, observation_source_counts
from argos.dashboard.raw_reports import build_raw_report_table, latest_payload_preview
from argos.dashboard.statistics import build_descriptive_statistics
from argos.dashboard.summaries import build_annual_summary, build_monthly_summary, build_seasonal_summary
from argos.dashboard.trends import build_trend_frame
from argos.database.session import get_sessionmaker
from argos.domain.field_events import FIELD_EVENT_TYPE_LABELS, FIELD_ZONE_LABELS
from argos.domain.plants import PLANT_SPECIES_LABELS, PLANT_STATUS_LABELS
from argos.integrations.ecowitt_cloud import format_cloud_mac
from argos.integrations.aemet.client import AemetClient, AemetConfigError
from argos.models import ArgosIrrigationSectorMinuteAttribution, ArgosNodeFlowmeterMinute
from argos.repositories.weather import WeatherRepository
from argos.services.aemet_import import AemetImportRangeError, AemetImportService
from argos.services.argos_node_flowmeter import ArgosNodeStatusError, parse_flowmeter_status


logger = logging.getLogger(__name__)

st.set_page_config(page_title="ARGOS dashboard", page_icon=":material/monitoring:", layout="wide")


DEFAULT_VARIABLES = [
    "outdoor_temperature_c",
    "outdoor_humidity_pct",
    "absolute_pressure_hpa",
    "relative_pressure_hpa",
    "wind_speed_ms",
    "wind_direction_deg",
    "wind_gust_ms",
    "rain_rate_mm_h",
    "solar_radiation_wm2",
    "uv_index",
    "battery_voltage",
    "ws90_capacitor_voltage",
]

DEFAULT_VALVE_OPENING_DURATION_S = 7.0
DEFAULT_VALVE_CLOSING_DURATION_S = 7.0


@dataclass(frozen=True, slots=True)
class ValveControl:
    technical_id: str
    functional_name: str
    valve_id: int
    relay_id: int
    sector_id: IrrigationSectorId | None = None
    irrigation: bool = True
    enabled_for_control: bool = True

    @property
    def control_key(self) -> str:
        return f"sector_{self.sector_id}" if self.sector_id is not None else f"valve_{self.valve_id}"


@dataclass(frozen=True, slots=True)
class CloseAllValveResult:
    valve: ValveControl
    response: dict[str, Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class CloseAllValvesResult:
    results: tuple[CloseAllValveResult, ...]

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)

    @property
    def succeeded(self) -> tuple[CloseAllValveResult, ...]:
        return tuple(result for result in self.results if result.ok)

    @property
    def failed(self) -> tuple[CloseAllValveResult, ...]:
        return tuple(result for result in self.results if not result.ok)


FLOWMETER_CHART_WINDOW_HOURS = 1
FLOWMETER_HISTORY_REFRESH_SECONDS = 30
FLOWMETER_LIVE_REFRESH_SECONDS = 5
FLOWMETER_CAPTURE_STALE_AFTER_MINUTES = 2
DEFAULT_AEMET_STATION = "6127X"
AEMET_BACKFILL_DEFAULT_START = date(1900, 1, 1)


LABELS = {
    "observed_at_utc": "Tiempo local",
    "outdoor_temperature_c": "Outdoor temperature (deg C)",
    "outdoor_humidity_pct": "Outdoor humidity (%)",
    "absolute_pressure_hpa": "Absolute pressure (hPa)",
    "relative_pressure_hpa": "Relative pressure (hPa)",
    "wind_speed_ms": "Wind speed (m/s)",
    "wind_direction_deg": "Wind direction (deg)",
    "wind_direction_avg10m_deg": "Wind direction 10 min avg (deg)",
    "wind_gust_ms": "Wind gust (m/s)",
    "rain_rate_mm_h": "Rain rate (mm/h)",
    "rain_day_mm": "Daily rain (mm)",
    "rain_last_24h_mm": "Rain last 24 h (mm)",
    "solar_radiation_wm2": "Solar radiation (W/m2)",
    "uv_index": "UV index",
    "battery_voltage": "WS90 battery (V)",
    "ws90_capacitor_voltage": "WS90 capacitor (V)",
}

OBSERVATION_UNITS = {
    "outdoor_temperature_c": "deg C",
    "outdoor_humidity_pct": "% HR",
    "absolute_pressure_hpa": "hPa",
    "relative_pressure_hpa": "hPa",
    "wind_speed_ms": "m/s",
    "wind_gust_ms": "m/s",
    "wind_direction_deg": "deg",
    "wind_direction_avg10m_deg": "deg",
    "rain_rate_mm_h": "mm/h",
    "rain_event_mm": "mm",
    "rain_hour_mm": "mm",
    "rain_last_24h_mm": "mm",
    "rain_day_mm": "mm",
    "rain_week_mm": "mm",
    "rain_month_mm": "mm",
    "rain_year_mm": "mm",
    "piezo_rain_mm": "mm",
    "solar_radiation_wm2": "W/m2",
    "uv_index": "UV",
    "battery_voltage": "V",
    "ws90_capacitor_voltage": "V",
}

OBSERVATION_COLORS = ["#2563eb", "#0f766e", "#f97316", "#7c3aed", "#ef4444", "#0891b2", "#64748b"]

OBSERVATION_PERIODS = [
    ("Day", timedelta(days=1)),
    ("Week", timedelta(days=7)),
    ("Month", timedelta(days=30)),
    ("Year", timedelta(days=365)),
]

OBSERVATION_PERIOD_OPTIONS = {
    "24 h": timedelta(days=1),
    "7 días": timedelta(days=7),
    "30 días": timedelta(days=30),
    "1 año": timedelta(days=365),
}

HOME_DUAL_AXIS_CHART_HEIGHT = 405
DUAL_AXIS_CHART_HEIGHT = 520
SINGLE_AXIS_CHART_HEIGHT = 360
WIND_BARB_LANE_Y = 0.5

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

WEATHER_CARD_VARIABLES = [
    ("Temperatura", "outdoor_temperature_c", "deg C", "TEMP"),
    ("Humedad", "outdoor_humidity_pct", "%", "HUM"),
    ("Presión", "relative_pressure_hpa", "hPa", "PRES"),
    ("Viento", "wind_speed_ms", "m/s", "WIND"),
    ("Dirección", "wind_direction_deg", "deg", "DIR"),
    ("Racha", "wind_gust_ms", "m/s", "GUST"),
    ("Lluvia 24 h", "rain_last_24h_mm", "mm", "RAIN"),
    ("Lluvia actual", "rain_rate_mm_h", "mm/h", "RATE"),
    ("UV", "uv_index", "", "UV"),
    ("Radiación solar", "solar_radiation_wm2", "W/m2", "SUN"),
    ("Batería WS90", "battery_voltage", "V", "BAT"),
    ("Capacitor WS90", "ws90_capacitor_voltage", "V", "CAP"),
]

MAIN_PAGES = [
    "Inicio",
    "Observaciones",
    "Resúmenes",
    "Análisis",
    "Diario de campo",
    "Plantación",
    "Actualizar datos",
    "AEMET",
    "Satélite",
    "Válvulas",
    "Calidad",
]

PAGE_GROUPS = {
    "GENERAL": ("Inicio",),
    "MONITORIZACIÓN": ("Observaciones", "Resúmenes", "Análisis", "Diario de campo", "Plantación"),
    "OPERACIÓN": ("Válvulas", "Actualizar datos"),
    "DATOS EXTERNOS": ("AEMET", "Satélite"),
    "ADMINISTRACIÓN": ("Calidad",),
}

MAIN_PAGE_ICONS = {
    "Inicio": ":material/home:",
    "Observaciones": ":material/monitoring:",
    "Resúmenes": ":material/summarize:",
    "Análisis": ":material/analytics:",
    "Diario de campo": ":material/edit_note:",
    "Plantación": ":material/grid_view:",
    "Actualizar datos": ":material/download:",
    "AEMET": ":material/cloud:",
    "Satélite": ":material/satellite_alt:",
    "Válvulas": ":material/water_drop:",
    "Calidad": ":material/fact_check:",
}


def irrigation_valve_controls() -> tuple[ValveControl, ...]:
    main_ev = get_main_irrigation_ev()
    return (
        ValveControl(technical_id=f"EV{main_ev}", functional_name="Principal", valve_id=main_ev, relay_id=main_ev),
        *tuple(_valve_control_from_sector_mapping(mapping) for mapping in irrigation_sector_mappings()),
    )


def _valve_control_from_sector_mapping(mapping: IrrigationSectorValveMapping) -> ValveControl:
    return ValveControl(
        technical_id=mapping.technical_id,
        functional_name=mapping.sector_name,
        valve_id=mapping.ev_id,
        relay_id=mapping.ev_id,
        sector_id=mapping.sector_id,
    )

PAGE_HEADER_MARKS = {
    "Inicio": "IN",
    "Observaciones": "WX",
    "Resúmenes": "RS",
    "Análisis": "AN",
    "Diario de campo": "DC",
    "Plantación": "12C",
    "Actualizar datos": "UP",
    "AEMET": "AE",
    "Satélite": "SAT",
    "Válvulas": "H2O",
    "Calidad": "QA",
}

PAGE_ARCHETYPES = {
    "Inicio": "Dashboard / resumen",
    "Observaciones": "Monitorización",
    "Resúmenes": "Dashboard / resumen",
    "Análisis": "Análisis",
    "Diario de campo": "Cronología / conocimiento",
    "Plantación": "Gemelo digital",
    "Actualizar datos": "Configuración / administración",
    "AEMET": "Monitorización",
    "Satélite": "Análisis",
    "Válvulas": "Operación / control",
    "Calidad": "Configuración / administración",
}

PAGE_DESCRIPTIONS = {
    "Inicio": "Estado general y meteorología reciente",
    "Observaciones": "Series meteorológicas por ventana temporal",
    "Resúmenes": "Agregados diarios, semanales y estacionales",
    "Análisis": "Comparación, correlación y distribución de variables",
    "Diario de campo": "Eventos, actuaciones y observaciones de finca",
    "Plantación": "Inventario individual y matriz espacial de árboles",
    "Actualizar datos": "Operaciones manuales de importación y sincronización",
    "AEMET": "Histórico externo de estación meteorológica",
    "Satélite": "Índices de vegetación y calidad por zona",
    "Válvulas": "Control de riego, caudal y acumulados",
    "Calidad": "Trazabilidad, gaps y datos operacionales",
}

SPANISH_MONTH_ABBR = {
    1: "ene",
    2: "feb",
    3: "mar",
    4: "abr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "ago",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dic",
}


def main() -> None:
    apply_compact_dashboard_styles()

    (
        client,
        node_client,
        selected_page,
        valve_opening_duration_s,
        valve_closing_duration_s,
    ) = sidebar()
    now = datetime.now(UTC)
    recent_start_iso = format_utc_iso(now - timedelta(days=1))
    recent_end_iso = format_utc_iso(now)
    summary_start_iso = format_utc_iso(now - timedelta(days=365))
    summary_end_iso = recent_end_iso

    try:
        health = cached_health(client.base_url)
        station = cached_station(client.base_url)
        hardware = cached_station_hardware(client.base_url)
        latest = cached_latest(client.base_url)
        status = cached_status(client.base_url)
        observations = cached_observations(client.base_url, recent_start_iso, recent_end_iso)
        daily = cached_daily(client.base_url, summary_start_iso, summary_end_iso)
        weekly = cached_weekly(client.base_url, summary_start_iso, summary_end_iso)
    except ArgosApiError as exc:
        st.error(str(exc))
        st.stop()

    observations_df = dataframe_from_records(observations, "observed_at_utc")
    daily_df = dataframe_from_records(daily, "period_start")
    weekly_df = dataframe_from_records(weekly, "period_start")

    render_global_shell_header(selected_page, health=health, latest=latest, status=status)

    if selected_page == "Inicio":
        render_home_header()
        render_home(
            health=health,
            station=station,
            hardware=hardware,
            latest=latest,
            status=status,
            observations_df=observations_df,
        )
    elif selected_page == "Observaciones":
        render_observations(
            client.base_url,
        )
    elif selected_page == "Resúmenes":
        render_summaries(daily_df, weekly_df)
    elif selected_page == "Análisis":
        render_analysis(client.base_url)
    elif selected_page == "Diario de campo":
        render_field_diary(client)
    elif selected_page == "Plantación":
        render_plantation(client)
    elif selected_page == "Actualizar datos":
        render_data_update(client)
    elif selected_page == "AEMET":
        render_aemet(client, start_date=summary_start_iso[:10], end_date=summary_end_iso[:10])
    elif selected_page == "Satélite":
        render_satellite(client, start_iso=summary_start_iso, end_iso=summary_end_iso)
    elif selected_page == "Válvulas":
        render_valves(
            node_client,
            start_iso=recent_start_iso,
            end_iso=recent_end_iso,
            valve_opening_duration_s=valve_opening_duration_s,
            valve_closing_duration_s=valve_closing_duration_s,
        )
    elif selected_page == "Calidad":
        render_quality(client)


def sidebar() -> tuple[ArgosApiClient, ArgosNodeClient, str, float, float]:
    settings = get_settings()
    with st.sidebar:
        render_sidebar_brand()
        selected_page = render_sidebar_navigation()
        st.html('<div class="argos-sidebar-section-label">SISTEMA</div>')
        with st.expander("Conexión", expanded=False, icon=":material/settings_ethernet:"):
            base_url = st.text_input("ARGOS API URL", value="http://127.0.0.1:8080")
            node_url = st.text_input("argos-node URL", value=settings.argos_node_url or "http://192.168.1.42")
            admin_token = st.text_input(
                "ARGOS admin token",
                value="",
                type="password",
                help="Value of ARGOS_ADMIN_TOKEN in .env.",
            )

        with st.expander("Válvulas", expanded=False, icon=":material/valve:"):
            valve_opening_duration_s = st.number_input(
                "Apertura (s)",
                min_value=0.0,
                value=DEFAULT_VALVE_OPENING_DURATION_S,
                step=0.5,
            )
            valve_closing_duration_s = st.number_input(
                "Cierre (s)",
                min_value=0.0,
                value=DEFAULT_VALVE_CLOSING_DURATION_S,
                step=0.5,
            )

        if st.button("Recargar vista", icon=":material/refresh:"):
            st.cache_data.clear()
            st.rerun()

    return (
        ArgosApiClient(base_url=base_url, admin_token=admin_token or None),
        ArgosNodeClient(base_url=normalize_http_base_url(node_url)),
        selected_page,
        float(valve_opening_duration_s),
        float(valve_closing_duration_s),
    )


def render_sidebar_brand() -> None:
    st.html(
        """
        <div class="argos-sidebar-brand">
            <strong>ARGOS</strong>
            <span>panel operativo</span>
        </div>
        """
    )


def render_sidebar_navigation() -> str:
    selected_page = st.session_state.get("argos_selected_page", MAIN_PAGES[0])
    if selected_page == "Tendencias":
        selected_page = "Análisis"
        st.session_state["argos_selected_page"] = selected_page
    if selected_page not in MAIN_PAGES:
        selected_page = MAIN_PAGES[0]
        st.session_state["argos_selected_page"] = selected_page

    for group, pages in PAGE_GROUPS.items():
        st.html(f'<div class="argos-sidebar-section-label">{escape(group)}</div>')
        for page in pages:
            active = page == selected_page
            if st.button(
                page,
                key=f"argos_nav_{element_key('page', page)}",
                type="primary" if active else "tertiary",
                icon=MAIN_PAGE_ICONS.get(page),
                width="stretch",
            ):
                st.session_state["argos_selected_page"] = page
                selected_page = page
                st.rerun()
    st.html('<div class="argos-sidebar-version">ARGOS v2.3.0</div>')
    return selected_page


def normalize_http_base_url(value: str) -> str:
    stripped = value.strip().rstrip("/")
    if not stripped:
        return stripped
    if "://" in stripped:
        return stripped
    return f"http://{stripped}"


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

@st.cache_data(ttl=60)
def cached_field_event_catalog(base_url: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_field_event_catalog()


@st.cache_data(ttl=30)
def cached_field_events(
    base_url: str,
    start: str | None,
    end: str | None,
    event_type: str | None,
    zone_slug: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_field_events(
        start=start,
        end=end,
        event_type=event_type,
        zone_slug=zone_slug,
        search=search,
        limit=1000,
    )


@st.cache_data(ttl=30)
def cached_plant_catalog(base_url: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_plant_catalog()


@st.cache_data(ttl=30)
def cached_plant_matrix(base_url: str, parcel_slug: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_plant_matrix(parcel_slug=parcel_slug)


@st.cache_data(ttl=30)
def cached_plants(
    base_url: str,
    parcel_slug: str,
    status: str | None,
    species: str | None,
    irrigation_sector_id: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_plants(
        parcel_slug=parcel_slug,
        status=status,
        species=species,
        irrigation_sector_id=irrigation_sector_id,
        search=search,
    )


@st.cache_data(ttl=30)
def cached_plant_history(base_url: str, plant_id: int) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_plant_history(plant_id)


@st.cache_data(ttl=120)
def cached_analytics_variables(base_url: str) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_analytics_variables()


@st.cache_data(ttl=60)
def cached_analytics_correlation(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url, timeout_seconds=120).analytics_correlation(payload)


@st.cache_data(ttl=60)
def cached_analytics_correlation_matrix(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url, timeout_seconds=120).analytics_correlation_matrix(payload)


@st.cache_data(ttl=60)
def cached_analytics_distribution(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url, timeout_seconds=120).analytics_distribution(payload)


@st.cache_data(ttl=60)
def cached_analytics_trend(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url, timeout_seconds=120).analytics_trend(payload)


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


@st.cache_data(ttl=15)
def cached_flowmeter_minutes(node_url: str, start: str, end: str) -> list[dict[str, Any]]:
    start_dt = parse_datetime(start)
    end_dt = parse_datetime(end)
    if start_dt is None or end_dt is None:
        return []
    normalized_node_url = normalize_http_base_url(node_url)
    statement = (
        select(ArgosNodeFlowmeterMinute)
        .where(
            ArgosNodeFlowmeterMinute.node_url == normalized_node_url,
            ArgosNodeFlowmeterMinute.window_start_utc >= start_dt,
            ArgosNodeFlowmeterMinute.window_start_utc <= end_dt,
        )
        .order_by(ArgosNodeFlowmeterMinute.window_start_utc)
    )
    try:
        with get_sessionmaker()() as session:
            rows = session.scalars(statement).all()
    except OperationalError as exc:
        if "argos_node_flowmeter_minutes" not in str(exc):
            raise
        logger.warning("flowmeter minute table is not available yet; run alembic upgrade head")
        return []
    return [
        {
            "window_start_utc": row.window_start_utc,
            "window_end_utc": row.window_end_utc,
            "pulse_delta": row.pulse_delta,
            "boot_total_l_start": row.boot_total_l_start,
            "boot_total_l_end": row.boot_total_l_end,
            "total_l_start": row.total_l_start,
            "total_l_end": row.total_l_end,
            "hydrological_year_l_start": row.hydrological_year_l_start,
            "hydrological_year_l_end": row.hydrological_year_l_end,
            "session_active_start": row.session_active_start,
            "session_active_end": row.session_active_end,
            "session_l_start": row.session_l_start,
            "session_l_end": row.session_l_end,
            "last_session_l_start": row.last_session_l_start,
            "last_session_l_end": row.last_session_l_end,
            "volume_l": row.volume_l,
            "unassigned_volume_l": row.unassigned_volume_l,
            "avg_flow_l_min": row.avg_flow_l_min,
            "max_flow_l_min": row.max_flow_l_min,
            "samples_count": row.samples_count,
            "relay1_state_start": row.relay1_state_start,
            "relay1_state_end": row.relay1_state_end,
            "relay1_open_samples_count": row.relay1_open_samples_count,
            "relay1_open_fraction": row.relay1_open_fraction,
        }
        for row in rows
    ]


@st.cache_data(ttl=15)
def cached_irrigation_sector_totals(node_url: str, start: str, end: str) -> dict[str, float]:
    start_dt = parse_datetime(start)
    end_dt = parse_datetime(end)
    if start_dt is None or end_dt is None:
        return {}
    normalized_node_url = normalize_http_base_url(node_url)
    statement = (
        select(ArgosIrrigationSectorMinuteAttribution)
        .where(
            ArgosIrrigationSectorMinuteAttribution.node_url == normalized_node_url,
            ArgosIrrigationSectorMinuteAttribution.window_start_utc >= start_dt,
            ArgosIrrigationSectorMinuteAttribution.window_start_utc <= end_dt,
        )
        .order_by(ArgosIrrigationSectorMinuteAttribution.window_start_utc)
    )
    try:
        with get_sessionmaker()() as session:
            rows = session.scalars(statement).all()
    except OperationalError as exc:
        if "argos_irrigation_sector_minute_attributions" not in str(exc):
            raise
        logger.warning("irrigation sector attribution table is not available yet; run alembic upgrade head")
        return {}

    totals: dict[str, float] = {}
    for row in rows:
        totals[row.sector_id] = totals.get(row.sector_id, 0.0) + row.volume_l
    return totals


def dataframe_from_records(records: list[dict[str, Any]], date_column: str) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(records)
    if not frame.empty and date_column in frame:
        frame[date_column] = pd.to_datetime(frame[date_column])
    return frame


def render_home_header() -> None:
    return


def render_global_shell_header(
    page: str,
    *,
    health: dict[str, Any],
    latest: dict[str, Any] | None,
    status: dict[str, Any],
) -> None:
    status_ok = str(health.get("status", "")).lower() in {"ok", "healthy", "ready"}
    status_label = "Sistema operativo" if status_ok else "Sistema con incidencias"
    status_tone = "ok" if status_ok else "warn"
    latest_time = format_compact_local_datetime(latest.get("observed_at_utc")) if latest else "-"
    updated_at = datetime.now().strftime("%H:%M:%S")
    temperature = format_number(latest.get("outdoor_temperature_c") if latest else None, "deg C")
    gateway = status.get("status") or status.get("state") or status.get("gateway_status") or "-"

    st.html(
        f"""
        <div class="argos-top-shell">
            <div class="argos-top-brand">
                <span class="argos-top-icon">{escape(PAGE_HEADER_MARKS.get(page, "AR"))}</span>
                <div>
                    <h1>{escape(page)}</h1>
                    <p>{escape(PAGE_DESCRIPTIONS.get(page, PAGE_ARCHETYPES.get(page, "")))}</p>
                </div>
            </div>
            <div class="argos-top-meta">
                {status_badge_html(status_label, status_tone)}
                {shell_pill_html("Arquetipo", PAGE_ARCHETYPES.get(page, "-"))}
                {shell_pill_html("Meteo", temperature)}
                {shell_pill_html("Último dato", latest_time)}
                {shell_pill_html("Gateway", str(gateway))}
                {shell_pill_html("Actualizado", updated_at)}
            </div>
        </div>
        """
    )


def section_header_html(title: str, subtitle: str | None = None) -> str:
    subtitle_html = f"<span>{escape(subtitle)}</span>" if subtitle else ""
    return f'<div class="argos-section-header"><strong>{escape(title)}</strong>{subtitle_html}</div>'


def status_badge_html(label: str, tone: str = "info") -> str:
    return f'<span class="argos-badge {escape(tone)}">{escape(label)}</span>'


def shell_pill_html(label: str, value: str) -> str:
    return (
        '<span class="argos-shell-pill">'
        f"<small>{escape(label)}</small>"
        f"<b>{escape(value)}</b>"
        "</span>"
    )


def valve_card_status_tone(phase: str) -> str:
    if phase == "not_operational":
        return "muted"
    if phase in {"open", "opening", "sending_open_command"}:
        return "ok"
    if phase in {"closed", "closing", "sending_close_command"}:
        return "muted"
    if phase == "error":
        return "danger"
    return "warn"


def phase_is_busy(phase: str) -> bool:
    return phase in {"sending_open_command", "sending_close_command", "opening", "closing"}


def valve_availability_label(valve: ValveControl) -> str:
    return "Operativa" if valve.enabled_for_control else "Pendiente"


def valve_card_state_label(phase: str) -> str:
    labels = {
        "open": "Estimada abierta",
        "closed": "Estimada cerrada",
        "sending_open_command": "Enviando abrir",
        "opening": "Abriendo",
        "sending_close_command": "Enviando cerrar",
        "closing": "Cerrando",
        "error": "Error comunicación",
        "unknown": "Desconocida",
        "not_operational": "Pendiente",
    }
    return labels.get(phase, phase)


def apply_compact_dashboard_styles() -> None:
    st.markdown(
        """
        <style>
            :root {
                --argos-font-body: 13px;
                --argos-font-meta: 11px;
                --argos-font-sidebar: 12.5px;
                --argos-font-sidebar-label: 10.5px;
                --argos-font-card-title: 13.5px;
                --argos-font-section-title: 15.5px;
                --argos-font-page-title: 19px;
                --argos-font-kpi: 20px;
                --argos-font-chip: 10.5px;
                --argos-font-button: 12.5px;
                --argos-main-top-offset: 56px;
                --argos-line-body: 1.24;
                --argos-line-title: 1.14;
                --argos-line-meta: 1.16;
            }

            html,
            body,
            .stApp,
            [data-testid="stAppViewContainer"] {
                font-size: var(--argos-font-body) !important;
                line-height: var(--argos-line-body) !important;
            }

            header[data-testid="stHeader"] {
                height: 0 !important;
            }

            section[data-testid="stSidebar"] {
                width: 192px !important;
                min-width: 192px !important;
                max-width: 192px !important;
            }

            section[data-testid="stSidebar"] > div {
                width: 192px !important;
                min-width: 192px !important;
                max-width: 192px !important;
                padding: 8px 9px !important;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
                width: 192px !important;
                min-width: 192px !important;
                max-width: 192px !important;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
                padding: 7px 6px !important;
            }

            .block-container {
                max-width: 100%;
                padding: var(--argos-main-top-offset) 8px 10px !important;
            }

            [data-testid="stMainBlockContainer"],
            [data-testid="stAppViewBlockContainer"] {
                max-width: 100%;
                padding-left: 8px !important;
                padding-right: 8px !important;
                padding-top: var(--argos-main-top-offset) !important;
                padding-bottom: 10px !important;
            }

            [data-testid="stVerticalBlockBorderWrapper"] {
                padding: 0 !important;
            }

            [data-testid="stVerticalBlockBorderWrapper"] > div {
                padding: 10px 11px !important;
            }

            div[data-testid="stDataFrame"] {
                font-size: 12px !important;
                line-height: 1.22 !important;
            }

            div[data-testid="stButton"] > button {
                align-items: center !important;
                border-radius: 6px !important;
                display: inline-flex !important;
                font-size: var(--argos-font-button) !important;
                justify-content: center !important;
                line-height: 1.16 !important;
                min-height: 34px !important;
                overflow: visible !important;
                padding: 5px 10px !important;
                white-space: nowrap !important;
                word-break: keep-all !important;
            }

            div[data-testid="stButton"] > button span {
                font-size: inherit !important;
                line-height: 1.16 !important;
                overflow: visible !important;
                white-space: nowrap !important;
                word-break: keep-all !important;
            }

            h1 {
                font-size: var(--argos-font-page-title) !important;
                line-height: var(--argos-line-title) !important;
                margin-bottom: 3px !important;
            }

            h2 {
                font-size: var(--argos-font-section-title) !important;
                line-height: var(--argos-line-title) !important;
            }

            h3 {
                font-size: var(--argos-font-card-title) !important;
                line-height: var(--argos-line-title) !important;
            }

            div[data-testid="stMetric"] {
                padding: 9px 11px !important;
            }

            div[data-testid="stMetricLabel"] {
                font-size: var(--argos-font-meta) !important;
                line-height: var(--argos-line-meta) !important;
            }

            div[data-testid="stMetricValue"] {
                font-size: var(--argos-font-kpi) !important;
                line-height: 1.1 !important;
            }

            .argos-app-header {
                align-items: baseline;
                display: flex;
                gap: 9px;
                margin: 0 0 6px;
                min-height: 22px;
            }

            .argos-app-header strong {
                color: rgb(38, 39, 48);
                font-size: var(--argos-font-section-title);
                letter-spacing: 0;
                line-height: var(--argos-line-title);
            }

            .argos-app-header span {
                color: rgba(49, 51, 63, 0.62);
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            div[data-testid="stCaptionContainer"] {
                font-size: var(--argos-font-meta) !important;
                line-height: var(--argos-line-meta) !important;
                margin-bottom: 2px;
            }

            div[data-testid="stMarkdownContainer"],
            div[data-testid="stText"],
            label,
            p {
                font-size: var(--argos-font-body);
                line-height: var(--argos-line-body);
            }

            div[data-testid="stTabs"] [data-baseweb="tab-list"] {
                gap: 4px;
                margin-top: 0;
            }

            div[data-testid="stTabs"] [data-baseweb="tab"] {
                font-size: 12.5px !important;
                height: 32px;
                line-height: 1.15;
                padding: 0 10px;
                white-space: nowrap;
            }

            div[data-testid="stSelectbox"] div[data-baseweb="select"],
            div[data-testid="stMultiSelect"] div[data-baseweb="select"] {
                min-height: 34px !important;
            }

            div[data-testid="stSelectbox"] [data-baseweb="select"] *,
            div[data-testid="stMultiSelect"] [data-baseweb="select"] *,
            div[data-testid="stSegmentedControl"] *,
            div[data-testid="stExpander"] * {
                font-size: 12.5px !important;
                line-height: 1.18 !important;
            }

            div[data-testid="stSegmentedControl"] button {
                min-height: 34px !important;
                padding: 5px 12px !important;
                white-space: nowrap !important;
            }

            div[data-testid="stExpander"] details > summary {
                min-height: 34px !important;
                padding: 7px 10px !important;
            }

            div[data-testid="stVerticalBlock"] {
                gap: 4px;
            }

            div[data-testid="stHeading"] {
                margin-bottom: 0;
            }

            section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
                gap: 4px;
            }

            section[data-testid="stSidebar"] h2,
            section[data-testid="stSidebar"] h3 {
                font-size: 12px !important;
                line-height: 1.15 !important;
                margin: 3px 0 2px !important;
            }

            section[data-testid="stSidebar"] label {
                font-size: 12px;
                line-height: 1.16;
            }

            .argos-sidebar-brand {
                border-bottom: 1px solid rgba(49, 51, 63, 0.16);
                margin: 0 0 7px;
                padding: 2px 0 8px;
            }

            .argos-sidebar-brand strong {
                color: #15803d;
                display: block;
                font-size: 20px;
                font-weight: 700;
                line-height: 1.12;
                overflow-wrap: anywhere;
            }

            .argos-sidebar-brand span {
                color: rgba(49, 51, 63, 0.58);
                display: block;
                font-size: 10.5px;
                line-height: 1.15;
                margin-top: 2px;
                text-transform: uppercase;
            }

            section[data-testid="stSidebar"] div.stButton {
                margin-bottom: 3px;
            }

            section[data-testid="stSidebar"] div.stButton > button {
                align-items: center;
                border-radius: 8px;
                box-shadow: none;
                cursor: pointer;
                display: flex;
                font-size: var(--argos-font-sidebar) !important;
                font-weight: 500;
                gap: 8px;
                height: 36px !important;
                justify-content: flex-start;
                line-height: 1.16;
                min-height: 36px !important;
                padding: 0 10px !important;
                text-align: left;
                transition: background-color 150ms ease, color 150ms ease, border-color 150ms ease;
                width: 100%;
            }

            section[data-testid="stSidebar"] div.stButton > button[data-testid="stBaseButton-tertiary"] {
                background: transparent;
                border-color: transparent;
                color: rgb(38, 39, 48);
            }

            section[data-testid="stSidebar"] div.stButton > button[data-testid="stBaseButton-tertiary"]:hover {
                background: rgba(49, 51, 63, 0.08);
                border-color: transparent;
                color: rgb(38, 39, 48);
            }

            section[data-testid="stSidebar"] div.stButton > button[data-testid="stBaseButton-primary"] {
                background: rgba(22, 163, 74, 0.12);
                border-color: rgba(22, 163, 74, 0.18);
                color: #15803d;
            }

            section[data-testid="stSidebar"] div.stButton > button[data-testid="stBaseButton-primary"] span {
                color: #15803d;
            }

            section[data-testid="stSidebar"] div.stButton > button[data-testid="stBaseButton-primary"]:hover {
                background: rgba(22, 163, 74, 0.16);
                border-color: rgba(22, 163, 74, 0.22);
                color: #15803d;
            }

            .argos-sidebar-version {
                border-top: 1px solid rgba(49, 51, 63, 0.12);
                color: rgba(49, 51, 63, 0.52);
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
                margin-top: 8px;
                padding-top: 7px;
            }

            .argos-top-shell {
                align-items: center;
                border: 1px solid rgba(148, 163, 184, 0.22);
                border-radius: 8px;
                display: flex;
                gap: 8px;
                justify-content: space-between;
                margin: 0 0 5px;
                min-height: 40px;
                padding: 5px 9px;
            }

            .argos-top-brand {
                align-items: center;
                display: flex;
                gap: 8px;
                min-width: 210px;
            }

            .argos-top-icon {
                color: #2563eb;
                display: inline-flex;
                font-size: 18px;
                line-height: 1;
            }

            .argos-top-shell h1 {
                font-size: var(--argos-font-page-title) !important;
                line-height: var(--argos-line-title) !important;
                margin: 0 !important;
            }

            .argos-top-shell p {
                color: rgba(49, 51, 63, 0.62);
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
                margin: 2px 0 0;
            }

            .argos-top-meta {
                align-items: center;
                display: flex;
                flex-wrap: wrap;
                gap: 4px;
                justify-content: flex-end;
            }

            .argos-badge {
                align-items: center;
                border-radius: 999px;
                display: inline-flex;
                font-size: var(--argos-font-chip);
                font-weight: 700;
                line-height: 1;
                min-height: 22px;
                padding: 4px 7px;
                white-space: nowrap;
            }

            .argos-badge.ok {
                background: rgba(22, 163, 74, 0.12);
                color: #15803d;
            }

            .argos-badge.info {
                background: rgba(37, 99, 235, 0.1);
                color: #2563eb;
            }

            .argos-badge.warn {
                background: rgba(217, 119, 6, 0.13);
                color: #b45309;
            }

            .argos-badge.danger {
                background: rgba(239, 68, 68, 0.12);
                color: #dc2626;
            }

            .argos-badge.muted {
                background: rgba(100, 116, 139, 0.12);
                color: #475569;
            }

            .argos-shell-pill {
                align-items: center;
                border: 1px solid rgba(148, 163, 184, 0.22);
                border-radius: 7px;
                display: inline-flex;
                gap: 4px;
                min-height: 22px;
                padding: 4px 7px;
                white-space: nowrap;
            }

            .argos-shell-pill small {
                color: rgba(49, 51, 63, 0.52);
                font-size: var(--argos-font-chip);
                line-height: 1;
            }

            .argos-shell-pill b {
                color: rgba(38, 39, 48, 0.86);
                font-size: 11.5px;
                line-height: 1;
            }

            .argos-section-header {
                align-items: baseline;
                display: flex;
                gap: 7px;
                margin: 1px 0 4px;
            }

            .argos-section-header strong {
                color: rgb(38, 39, 48);
                font-size: var(--argos-font-section-title);
                font-weight: 700;
                line-height: var(--argos-line-title);
            }

            .argos-section-header span {
                color: rgba(49, 51, 63, 0.58);
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
            }

            .st-key-argos_irrigation_page {
                margin-top: -6px;
            }

            .st-key-argos_irrigation_page div[data-testid="stVerticalBlock"] {
                gap: 0.45rem;
            }

            .argos-irrigation-header {
                align-items: baseline;
                display: flex;
                gap: 10px;
                min-height: 32px;
            }

            .argos-irrigation-header h1 {
                color: rgb(38, 39, 48);
                font-size: var(--argos-font-page-title);
                font-weight: 750;
                line-height: 1.05;
                margin: 0;
            }

            .argos-irrigation-header span {
                color: rgba(49, 51, 63, 0.58);
                font-size: 11.5px;
                line-height: var(--argos-line-meta);
            }

            .st-key-argos_irrigation_page .stButton button {
                min-height: 31px;
                padding: 3px 8px;
                white-space: nowrap;
            }

            .st-key-argos_irrigation_page .stButton button p,
            .st-key-argos_irrigation_page .stButton button span {
                font-size: var(--argos-font-button) !important;
                line-height: 1 !important;
                white-space: nowrap;
            }

            .st-key-argos_valve_card_8,
            .st-key-argos_valve_card_6,
            .st-key-argos_valve_card_7,
            .st-key-argos_valve_card_4,
            .st-key-argos_valve_card_5 {
                min-height: 118px;
                padding: 10px 11px !important;
            }

            .st-key-argos_valve_card_4,
            .st-key-argos_valve_card_5 {
                background: rgba(248, 250, 252, 0.58);
                border-color: rgba(148, 163, 184, 0.22) !important;
                opacity: 0.58;
            }

            .argos-valve-card-inner {
                display: grid;
                gap: 13px;
                min-height: 47px;
            }

            .argos-valve-card-inner h3 {
                color: rgb(38, 39, 48);
                font-size: 13.5px !important;
                font-weight: 650;
                line-height: var(--argos-line-title) !important;
                margin: 0 !important;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-valve-card-inner strong {
                color: rgb(38, 39, 48);
                display: block;
                font-size: 16px;
                font-weight: 550;
                line-height: 1.12;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-valve-empty {
                min-height: 118px;
            }

            .st-key-argos_valve_actions_8 div[data-testid="stHorizontalBlock"],
            .st-key-argos_valve_actions_6 div[data-testid="stHorizontalBlock"],
            .st-key-argos_valve_actions_7 div[data-testid="stHorizontalBlock"],
            .st-key-argos_valve_actions_4 div[data-testid="stHorizontalBlock"],
            .st-key-argos_valve_actions_5 div[data-testid="stHorizontalBlock"] {
                gap: 7px;
            }

            .argos-session-log {
                border: 1px solid rgba(148, 163, 184, 0.22);
                border-radius: 8px;
                display: grid;
                gap: 0;
                padding: 0;
            }

            .argos-session-log-row {
                align-items: center;
                display: grid;
                gap: 8px;
                grid-template-columns: 0.9fr 0.9fr 0.9fr 2fr;
                border-bottom: 1px solid rgba(148, 163, 184, 0.16);
                min-height: 24px;
                padding: 0 8px;
            }

            .argos-session-log-row:last-child {
                border-bottom: 0;
            }

            .argos-session-log-row.header span {
                color: rgba(49, 51, 63, 0.52);
                font-size: var(--argos-font-chip);
                font-weight: 700;
                text-transform: uppercase;
            }

            .argos-session-log-row span {
                color: rgba(49, 51, 63, 0.72);
                font-size: 11.5px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-plantation-grid {
                border: 1px solid rgba(148, 163, 184, 0.24);
                border-radius: 8px;
                display: grid;
                gap: 1px;
                grid-template-columns: 28px repeat(12, minmax(42px, 1fr));
                overflow: hidden;
                width: 100%;
            }

            .argos-plantation-cell,
            .argos-plantation-label {
                align-items: center;
                box-sizing: border-box;
                display: grid;
                min-height: 44px;
                min-width: 0;
                padding: 4px;
                text-align: center;
            }

            .argos-plantation-label {
                background: rgba(15, 118, 110, 0.08);
                color: rgba(15, 53, 35, 0.86);
                font-size: 12px;
                font-weight: 750;
            }

            .argos-plantation-cell {
                background: rgba(248, 250, 252, 0.82);
                border: 0;
                color: rgba(49, 51, 63, 0.72);
                font-size: 10.5px;
                line-height: 1.08;
            }

            .argos-plantation-cell.empty {
                background: rgba(248, 250, 252, 0.42);
                color: rgba(100, 116, 139, 0.42);
            }

            .argos-plantation-cell.infrastructure {
                background: rgba(217, 119, 6, 0.10);
                color: #92400e;
            }

            .argos-plantation-cell.active {
                background: rgba(22, 163, 74, 0.12);
                color: #14532d;
            }

            .argos-plantation-cell.incident {
                background: rgba(217, 119, 6, 0.16);
                color: #92400e;
            }

            .argos-plantation-cell.removed,
            .argos-plantation-cell.replaced {
                background: rgba(100, 116, 139, 0.14);
                color: #475569;
            }

            .argos-plantation-cell.selected {
                box-shadow: inset 0 0 0 2px #2563eb;
            }

            .argos-plantation-cell b,
            .argos-plantation-cell span {
                display: block;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-plantation-cell b {
                font-size: 12px;
                line-height: 1.05;
            }

            .argos-plantation-legend {
                align-items: center;
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                margin: 5px 0;
            }

            .argos-plantation-legend span {
                border: 1px solid rgba(148, 163, 184, 0.24);
                border-radius: 999px;
                color: rgba(49, 51, 63, 0.72);
                font-size: 11px;
                line-height: 1;
                padding: 5px 7px;
            }

            section[data-testid="stSidebar"] div.stButton > button[data-testid="stBaseButton-primary"]:hover {
                background: rgba(22, 163, 74, 0.16);
                border-color: rgba(22, 163, 74, 0.22);
                color: #15803d;
            }

            section[data-testid="stSidebar"] div.stButton > button:focus-visible {
                outline: 2px solid rgba(22, 163, 74, 0.35);
                outline-offset: 2px;
            }

            section[data-testid="stSidebar"] div.stButton > button span {
                color: inherit;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-sidebar-section-label {
                color: rgba(49, 51, 63, 0.58);
                font-size: var(--argos-font-sidebar-label);
                font-weight: 650;
                letter-spacing: 0;
                line-height: 1.15;
                margin: 8px 0 4px;
                text-transform: uppercase;
            }

            .argos-compact-row {
                align-items: center;
                display: flex;
                gap: 10px;
                margin: 4px 0;
            }

            .argos-compact-metric {
                border: 1px solid rgba(49, 51, 63, 0.18);
                border-radius: 8px;
                box-sizing: border-box;
                display: inline-block;
                max-width: 180px;
                min-width: 140px;
                padding: 7px 9px;
                width: 180px;
            }

            .argos-compact-metric span {
                color: rgba(49, 51, 63, 0.68);
                display: block;
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
                margin-bottom: 3px;
            }

            .argos-compact-metric strong {
                color: rgb(38, 39, 48);
                display: block;
                font-size: 18px;
                font-weight: 500;
                line-height: 1.1;
            }

            .argos-flowmeter-grid {
                display: flex;
                flex-direction: column;
                gap: 4px;
                margin: 0;
            }

            .argos-flowmeter-grid .argos-compact-metric {
                max-width: none;
                width: 100%;
                padding: 6px 8px;
            }

            .argos-flowmeter-grid .argos-compact-metric span {
                font-size: var(--argos-font-meta);
            }

            .argos-flowmeter-grid .argos-compact-metric strong {
                font-size: 16px;
            }

            .argos-realtime-flowmeter-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 5px;
                margin: 0;
            }

            .argos-flowmeter-panel {
                border-radius: 7px;
                display: flex;
                flex-direction: column;
                gap: 4px;
                min-width: 0;
            }

            .argos-flowmeter-panel {
                padding: 2px 0 4px;
            }

            .argos-flowmeter-section-title {
                color: rgb(38, 39, 48);
                font-size: var(--argos-font-card-title);
                font-weight: 600;
                line-height: var(--argos-line-title);
                margin: 0;
            }

            .argos-realtime-flowmeter-grid .argos-compact-metric {
                max-width: none;
                min-width: 0;
                padding: 5px 7px;
                width: 100%;
            }

            .argos-realtime-flowmeter-grid .argos-compact-metric span {
                font-size: var(--argos-font-meta);
            }

            .argos-realtime-flowmeter-grid .argos-compact-metric strong {
                font-size: 16px;
            }

            .argos-flowmeter-panel .argos-compact-metric {
                padding: 6px 8px;
            }

            .argos-flowmeter-panel .argos-compact-metric span {
                font-size: var(--argos-font-meta);
            }

            .argos-flowmeter-panel .argos-compact-metric strong {
                font-size: 16px;
                font-weight: 600;
            }

            .argos-summary-grid {
                display: grid;
                gap: 5px;
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .argos-summary-grid .argos-compact-metric {
                max-width: none;
                min-width: 0;
                padding: 6px 8px;
                width: 100%;
            }

            .argos-summary-grid .argos-compact-metric span {
                font-size: var(--argos-font-meta);
            }

            .argos-summary-grid .argos-compact-metric strong {
                font-size: 15px;
            }

            div[data-testid="stPlotlyChart"] {
                margin-top: -0.1rem;
            }

            @media (max-width: 900px) {
                .argos-session-log-row {
                    grid-template-columns: 0.8fr 0.85fr 0.75fr 1.6fr;
                }
            }

            .argos-observations-header {
                align-items: baseline;
                display: flex;
                gap: 8px;
                min-height: 30px;
            }

            .argos-observations-header strong {
                color: rgb(38, 39, 48);
                font-size: var(--argos-font-section-title);
                font-weight: 750;
                line-height: var(--argos-line-title);
            }

            .argos-observations-header span {
                color: rgba(49, 51, 63, 0.58);
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
            }

            .argos-observations-kpis {
                display: grid;
                gap: 8px;
                grid-template-columns: repeat(7, minmax(0, 1fr));
                margin: 4px 0 8px;
            }

            .argos-observation-kpi {
                align-items: center;
                border: 1px solid rgba(148, 163, 184, 0.26);
                border-radius: 8px;
                display: grid;
                gap: 5px;
                grid-template-columns: minmax(0, 1fr);
                min-height: 66px;
                padding: 8px 9px;
            }

            .argos-observation-kpi b {
                color: rgb(38, 39, 48);
                display: block;
                font-size: 17px;
                line-height: 1.1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-observation-kpi p {
                color: rgba(49, 51, 63, 0.64);
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
                margin: 2px 0 0;
            }

            .argos-observation-kpi small {
                color: rgba(49, 51, 63, 0.54);
                display: block;
                font-size: var(--argos-font-chip);
                line-height: 1.15;
                margin-top: 2px;
            }

            .argos-observations-quality {
                align-items: center;
                border: 1px solid rgba(148, 163, 184, 0.24);
                border-radius: 8px;
                display: flex;
                gap: 8px;
                justify-content: space-between;
                margin-top: 6px;
                padding: 7px 9px;
            }

            .argos-observations-quality > div {
                align-items: center;
                display: flex;
                flex-wrap: wrap;
                gap: 5px;
            }

            .argos-observations-quality > span {
                color: #2563eb;
                font-size: 12px;
                font-weight: 650;
                white-space: nowrap;
            }

            @media (max-width: 1599px) {
                .argos-observations-kpis {
                    gap: 6px;
                }

                .argos-observation-kpi {
                    grid-template-columns: minmax(0, 1fr);
                    min-height: 62px;
                    padding: 7px 8px;
                }

                .argos-observation-kpi b {
                    font-size: 15px;
                }

                .argos-observation-kpi p {
                    font-size: 10.5px;
                }
            }

            @media (max-width: 1199px) {
                .argos-observations-kpis {
                    grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
                }
            }

            @media (max-width: 680px) {
                .argos-realtime-flowmeter-grid {
                    grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
                }
            }

            .argos-field-event-table {
                display: grid;
                gap: 5px;
                margin-top: 8px;
            }

            .argos-field-event-row {
                align-items: start;
                border: 1px solid rgba(49, 51, 63, 0.14);
                border-radius: 8px;
                display: grid;
                gap: 8px;
                grid-template-columns: 1.05fr 1fr 1.35fr 1fr 0.9fr 0.75fr 1.45fr;
                min-height: 34px;
                padding: 7px 9px;
            }

            .argos-field-event-row.header {
                background: rgba(248, 250, 252, 0.9);
                color: rgba(49, 51, 63, 0.68);
                font-size: var(--argos-font-meta);
                font-weight: 600;
                text-transform: uppercase;
            }

            .argos-field-event-row span {
                min-width: 0;
                overflow-wrap: anywhere;
            }

            .argos-status-band {
                display: grid;
                grid-template-columns: 1fr;
                gap: 6px;
                margin: 0;
            }

            .argos-status-item {
                border: 1px solid rgba(49, 51, 63, 0.18);
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.78);
                min-width: 0;
                box-sizing: border-box;
            }

            .argos-status-item {
                min-height: 46px;
                padding: 8px 10px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                gap: 2px;
            }

            .argos-label {
                color: rgba(49, 51, 63, 0.68);
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
            }

            .argos-status-item strong {
                color: rgb(38, 39, 48);
                font-size: 13.5px;
                line-height: 1.18;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-status-item small {
                color: rgba(49, 51, 63, 0.58);
                font-size: var(--argos-font-chip);
                line-height: 1.15;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-chip {
                align-items: center;
                border-radius: 999px;
                display: inline-flex;
                font-size: var(--argos-font-chip);
                font-weight: 700;
                gap: 5px;
                line-height: 1;
                padding: 5px 8px;
                width: fit-content;
            }

            .argos-chip.ok {
                background: rgba(16, 124, 16, 0.12);
                color: rgb(16, 124, 16);
            }

            .argos-chip.warn {
                background: rgba(181, 116, 0, 0.14);
                color: rgb(138, 86, 0);
            }

            .argos-chip.danger {
                background: rgba(196, 43, 28, 0.12);
                color: rgb(164, 38, 27);
            }

            .argos-count-strip {
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                margin: -3px 0 5px;
            }

            .argos-count-strip span {
                border: 1px solid rgba(49, 51, 63, 0.14);
                border-radius: 999px;
                color: rgba(49, 51, 63, 0.72);
                font-size: var(--argos-font-chip);
                line-height: 1.1;
                padding: 5px 8px;
            }

            .argos-weather-table {
                border: 1px solid rgba(49, 51, 63, 0.18);
                border-collapse: separate;
                border-radius: 7px;
                border-spacing: 0;
                margin-top: 6px;
                overflow: hidden;
                table-layout: fixed;
                width: 100%;
            }

            .argos-weather-table td {
                border-bottom: 1px solid rgba(49, 51, 63, 0.12);
                border-right: 1px solid rgba(49, 51, 63, 0.12);
                padding: 6px 9px;
                vertical-align: top;
            }

            .argos-weather-table tr:last-child td {
                border-bottom: 0;
            }

            .argos-weather-table td:last-child {
                border-right: 0;
            }

            .argos-weather-table span {
                color: rgba(49, 51, 63, 0.68);
                display: block;
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
                margin-bottom: 2px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .argos-weather-table strong {
                color: rgb(38, 39, 48);
                display: block;
                font-size: 16px;
                font-weight: 650;
                line-height: 1.12;
                overflow-wrap: anywhere;
            }

            @media (max-width: 900px) {
                .block-container {
                    padding: 8px 8px 16px;
                }

                .argos-status-band {
                    grid-template-columns: 1fr;
                }

                .argos-weather-table {
                    table-layout: auto;
                }

                .argos-weather-table td {
                    padding: 6px 8px;
                }

                .argos-weather-table strong {
                    font-size: 14.5px;
                }
            }

            .argos-satellite-header {
                align-items: center;
                display: flex;
                gap: 10px;
                justify-content: space-between;
                margin: 4px 0 6px;
            }

            .argos-satellite-header h2 {
                font-size: var(--argos-font-page-title);
                line-height: var(--argos-line-title);
                margin: 0;
            }

            .argos-satellite-header span {
                color: rgba(49, 51, 63, 0.62);
                font-size: var(--argos-font-meta);
                line-height: var(--argos-line-meta);
                white-space: nowrap;
            }

            .argos-satellite-meta {
                color: rgba(49, 51, 63, 0.68);
                font-size: var(--argos-font-body);
                line-height: var(--argos-line-body);
                margin: -2px 0 5px;
            }

            .argos-satellite-meta b {
                color: rgba(49, 51, 63, 0.88);
                font-weight: 700;
            }

            .argos-satellite-controls {
                margin-top: 2px;
            }

            .argos-satellite-controls [data-testid="stMultiSelect"] div[data-baseweb="select"],
            .argos-satellite-controls [data-testid="stSelectbox"] div[data-baseweb="select"] {
                min-height: 34px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_home(
    *,
    health: dict[str, Any],
    station: dict[str, Any] | None,
    hardware: list[dict[str, Any]],
    latest: dict[str, Any] | None,
    status: dict[str, Any],
    observations_df: pd.DataFrame,
) -> None:
    if latest is None:
        render_station_status_summary(health=health, station=station, status=status)
        st.info("No weather observations received yet.")
        return

    if not observations_df.empty:
        status_column, chart_column = st.columns([1, 5], vertical_alignment="top")
        with status_column:
            render_station_status_summary(health=health, station=station, status=status)
        with chart_column:
            with st.container(border=True):
                st.subheader("Recent temperature and relative humidity")
                st.plotly_chart(build_recent_weather_figure(observations_df), width="stretch")
    else:
        render_station_status_summary(health=health, station=station, status=status)

    source_counts = observation_source_counts(observations_df)
    if source_counts:
        render_source_count_strip(source_counts)

    render_weather_metric_table(latest)
    render_hardware_detail(hardware)


def render_station_status_summary(
    *,
    health: dict[str, Any],
    station: dict[str, Any] | None,
    status: dict[str, Any],
) -> None:
    station_slug = station.get("slug", "-") if station else "-"
    station_uuid = station.get("uuid") if station else None
    api_status = str(health.get("status", "unknown"))
    gateway_online = bool(status.get("online"))
    gateway_label = "Online" if gateway_online else "Offline"
    api_chip_class = "ok" if api_status.lower() == "ok" else "warn"
    gateway_chip_class = "ok" if gateway_online else "danger"
    last_seen_label = format_local_datetime(status.get("last_seen_at"))
    last_seen_utc = format_datetime(status.get("last_seen_at"))

    st.html(
        f"""
        <section class="argos-status-band">
            <div class="argos-status-item argos-station">
                <span class="argos-label">Estación</span>
                <strong title="{escape(str(station_uuid or '-'))}">{escape(str(station_slug))}</strong>
                <small title="{escape(str(station_uuid or '-'))}">UUID {escape(short_identifier(station_uuid))}</small>
            </div>
            <div class="argos-status-item">
                <span class="argos-label">API</span>
                <span class="argos-chip {api_chip_class}"><span aria-hidden="true">{"&#10003;" if api_chip_class == "ok" else "!"}</span> {escape(api_status)}</span>
            </div>
            <div class="argos-status-item">
                <span class="argos-label">Gateway</span>
                <span class="argos-chip {gateway_chip_class}"><span aria-hidden="true">{"&#10003;" if gateway_online else "!"}</span> {gateway_label}</span>
            </div>
            <div class="argos-status-item">
                <span class="argos-label">Última comunicación</span>
                <strong title="{escape(last_seen_utc)}">{escape(last_seen_label)}</strong>
            </div>
        </section>
        """,
    )

    if station is None:
        st.caption("Station identity is not available yet.")

def render_hardware_detail(hardware: list[dict[str, Any]]) -> None:
    if not hardware:
        return

    with st.expander("Detalle de hardware", expanded=False, icon=":material/memory:"):
        hardware_df = pd.DataFrame.from_records(hardware)
        visible_columns = [
            column for column in ["id", "mac_address", "station_type", "last_seen_at", "enabled"] if column in hardware_df
        ]
        if visible_columns:
            st.dataframe(hardware_df[visible_columns], hide_index=True)


def build_recent_weather_figure(frame: pd.DataFrame, *, wind_frequency: str = "1h") -> go.Figure:
    frame = with_local_observed_time(frame)
    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=[0.77, 0.16, 0.07],
        specs=[[{"secondary_y": True}], [{}], [{}]],
    )
    if "outdoor_temperature_c" in frame:
        temperature_frame = frame[["observed_at_utc", "outdoor_temperature_c"]].dropna()
        if not temperature_frame.empty:
            figure.add_trace(
                go.Scatter(
                    x=temperature_frame["observed_at_utc"],
                    y=temperature_frame["outdoor_temperature_c"],
                    mode="lines",
                    name="Temperatura",
                    line={"color": "#ff2d2d", "width": 2.4},
                ),
                row=1,
                col=1,
                secondary_y=False,
            )
    if "outdoor_humidity_pct" in frame:
        humidity_frame = frame[["observed_at_utc", "outdoor_humidity_pct"]].dropna()
        if not humidity_frame.empty:
            figure.add_trace(
                go.Scatter(
                    x=humidity_frame["observed_at_utc"],
                    y=humidity_frame["outdoor_humidity_pct"],
                    mode="lines",
                    name="Humedad relativa",
                    line={"color": "#7f1d1d", "dash": "dot", "width": 1.4},
                ),
                row=1,
                col=1,
                secondary_y=True,
            )
    add_recent_rain_bars(figure, frame)
    add_recent_wind_arrows(figure, frame, frequency=wind_frequency)
    figure.update_layout(
        height=HOME_DUAL_AXIS_CHART_HEIGHT,
        margin={"t": 56, "r": 44, "b": 28, "l": 42},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.14,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 10},
            "bgcolor": "rgba(255,255,255,0.88)",
        },
        plot_bgcolor="#ffffff",
        xaxis={
            "showgrid": True,
            "gridcolor": "rgba(49, 51, 63, 0.11)",
            "linecolor": "rgba(49, 51, 63, 0.24)",
            "showline": True,
            "ticks": "outside",
        },
        xaxis2={
            "showgrid": True,
            "gridcolor": "rgba(49, 51, 63, 0.11)",
            "linecolor": "rgba(49, 51, 63, 0.24)",
            "showline": True,
            "ticks": "outside",
        },
        xaxis3={
            "showgrid": True,
            "gridcolor": "rgba(49, 51, 63, 0.11)",
            "linecolor": "rgba(49, 51, 63, 0.24)",
            "showline": True,
            "ticks": "outside",
            "title": local_time_axis_title(),
        },
        yaxis={
            "title": "deg C",
            "range": [0, 45],
            "showgrid": True,
            "gridcolor": "rgba(49, 51, 63, 0.13)",
            "linecolor": "rgba(49, 51, 63, 0.24)",
            "showline": True,
            "dtick": 5,
            "ticks": "outside",
        },
        yaxis2=synced_secondary_yaxis("% HR", value_range=[0, 100]),
        yaxis3={
            "title": "mm/h",
            "showgrid": True,
            "gridcolor": "rgba(70, 130, 180, 0.16)",
            "linecolor": "rgba(49, 51, 63, 0.24)",
            "showline": True,
            "rangemode": "tozero",
            "zeroline": False,
            "ticks": "outside",
        },
        yaxis4={
            "visible": False,
            "range": [0, 1],
            "fixedrange": True,
        },
    )
    add_weather_day_markers(figure, frame)
    return figure


def add_recent_rain_bars(figure: go.Figure, frame: pd.DataFrame) -> None:
    if "rain_rate_mm_h" not in frame:
        return
    rain_frame = frame[["observed_at_utc", "rain_rate_mm_h"]].copy()
    rain_frame["rain_rate_mm_h"] = pd.to_numeric(rain_frame["rain_rate_mm_h"], errors="coerce")
    rain_frame = rain_frame.dropna()
    if rain_frame.empty:
        return
    figure.add_trace(
        go.Bar(
            x=rain_frame["observed_at_utc"],
            y=rain_frame["rain_rate_mm_h"],
            name="Precipitación",
            marker={"color": "#4682b4"},
            opacity=0.82,
        ),
        row=2,
        col=1,
    )


def add_recent_wind_arrows(figure: go.Figure, frame: pd.DataFrame, *, frequency: str) -> None:
    required_columns = ["observed_at_utc", "wind_direction_deg", "wind_speed_ms"]
    if not set(required_columns).issubset(frame.columns):
        return
    wind = frame[required_columns].copy()
    wind["observed_at_utc"] = pd.to_datetime(wind["observed_at_utc"], format="ISO8601", errors="coerce")
    wind["wind_direction_deg"] = pd.to_numeric(wind["wind_direction_deg"], errors="coerce")
    wind["wind_speed_ms"] = pd.to_numeric(wind["wind_speed_ms"], errors="coerce")
    wind = wind.dropna()
    if wind.empty:
        return
    grouped = aggregate_wind_vectors(wind, frequency)
    if grouped.empty:
        return
    figure.add_trace(
        go.Scatter(
            x=grouped["observed_at_utc"],
            y=[WIND_BARB_LANE_Y for _value in grouped["direction_deg"]],
            mode="text",
            text=[wind_direction_arrow(value) for value in grouped["direction_deg"]],
            name="Viento",
            showlegend=False,
            textfont={"color": "#111827", "size": 21},
            cliponaxis=False,
            hovertemplate=(
                "Viento medio "
                + frequency
                + ": %{customdata[1]:.1f} m/s<br>Dirección: %{customdata[0]:.0f}°<extra></extra>"
            ),
            customdata=grouped[["direction_deg", "speed_ms"]],
        ),
        row=3,
        col=1,
    )


def circular_mean_degrees(values: pd.Series) -> float | None:
    radians = pd.to_numeric(values, errors="coerce").dropna().map(math.radians)
    if radians.empty:
        return None
    u_mean = radians.map(math.sin).mean()
    v_mean = radians.map(math.cos).mean()
    return meteorological_direction_from_uv(-u_mean, -v_mean)


def aggregate_wind_vectors(wind: pd.DataFrame, frequency: str) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    indexed_wind = wind.set_index("observed_at_utc").copy()
    indexed_wind["u_ms"], indexed_wind["v_ms"] = wind_components_ms(
        indexed_wind["wind_speed_ms"],
        indexed_wind["wind_direction_deg"],
    )
    for window_start, group in indexed_wind.resample(frequency):
        mean_direction = meteorological_direction_from_uv(group["u_ms"].mean(), group["v_ms"].mean())
        if mean_direction is not None:
            records.append(
                {
                    "observed_at_utc": window_start,
                    "direction_deg": mean_direction,
                    "speed_ms": math.hypot(group["u_ms"].mean(), group["v_ms"].mean()),
                }
            )
    return pd.DataFrame.from_records(records)


def wind_components_ms(speed_ms: pd.Series, direction_deg: pd.Series) -> tuple[pd.Series, pd.Series]:
    speed = pd.to_numeric(speed_ms, errors="coerce").clip(lower=0)
    radians = pd.to_numeric(direction_deg, errors="coerce").map(math.radians)
    u_ms = -speed * radians.map(math.sin)
    v_ms = -speed * radians.map(math.cos)
    return u_ms, v_ms


def meteorological_direction_from_uv(u_ms: float, v_ms: float) -> float | None:
    if pd.isna(u_ms) or pd.isna(v_ms) or math.hypot(u_ms, v_ms) < 1e-9:
        return None
    return math.degrees(math.atan2(-u_ms, -v_ms)) % 360


def wind_direction_arrow(degrees: float) -> str:
    arrows = ["↓", "↙", "←", "↖", "↑", "↗", "→", "↘"]
    return arrows[int(((degrees % 360) + 22.5) // 45) % len(arrows)]


def add_weather_day_markers(figure: go.Figure, frame: pd.DataFrame) -> None:
    if "observed_at_utc" not in frame:
        return
    times = pd.to_datetime(frame["observed_at_utc"], format="ISO8601", errors="coerce").dropna()
    if times.empty:
        return

    start = times.min().floor("D")
    end = times.max().ceil("D")
    day_starts = pd.date_range(start=start, end=end, freq="1D", tz=times.dt.tz)
    for day_start in day_starts:
        if times.min() < day_start < times.max():
            figure.add_vline(
                x=day_start,
                line_width=1,
                line_color="rgba(49, 51, 63, 0.18)",
            )
        label_at = day_start + pd.Timedelta(hours=12)
        if times.min() <= label_at <= times.max():
            figure.add_annotation(
                x=label_at,
                y=1.035,
                xref="x",
                yref="paper",
                text=format_weather_day_label(day_start),
                showarrow=False,
                font={"size": 10, "color": "rgba(49, 51, 63, 0.68)"},
            )


def format_weather_day_label(value: pd.Timestamp) -> str:
    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][value.weekday()]
    month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][value.month - 1]
    return f"{weekday} {month} {value.day}"


def synced_secondary_yaxis(title: str, *, value_range: list[float] | None = None) -> dict[str, Any]:
    axis: dict[str, Any] = {
        "title": title,
        "overlaying": "y",
        "side": "right",
        "showgrid": False,
        "tickmode": "sync",
    }
    if value_range is not None:
        axis["range"] = value_range
    return axis


def render_source_count_strip(source_counts: dict[str, int]) -> None:
    st.html(
        f"""
        <div class="argos-count-strip">
            <span><b>{source_counts.get("DIRECT", 0)}</b> directas</span>
            <span><b>{source_counts.get("BACKFILLED", 0)}</b> backfill</span>
            <span><b>{source_counts.get("UNKNOWN", 0)}</b> sin fuente</span>
        </div>
        """,
    )


def render_weather_metric_table(latest: dict[str, Any]) -> None:
    st.html(weather_metric_table_html(latest))


def weather_metric_table_html(latest: dict[str, Any]) -> str:
    cells = []
    for label, key, unit, _icon in WEATHER_CARD_VARIABLES:
        value = format_weather_card_value(latest.get(key), key=key, unit=unit)
        cells.append(
            f"""
            <td title="{escape(LABELS.get(key, key))}">
                <span>{escape(label)}</span>
                <strong>{escape(value)}</strong>
            </td>
            """
        )

    while len(cells) % 4:
        cells.append("<td></td>")

    rows = ["<tr>" + "".join(cells[index : index + 4]) + "</tr>" for index in range(0, len(cells), 4)]
    return f'<table class="argos-weather-table"><tbody>{"".join(rows)}</tbody></table>'


def format_weather_card_value(value: Any, *, key: str, unit: str) -> str:
    if key in {"wind_direction_deg", "wind_direction_avg10m_deg"}:
        return format_wind_direction(value)
    return format_number(value, unit)


def render_observations(base_url: str) -> None:
    selected_period = st.session_state.get("observations_period", "24 h")
    if selected_period not in OBSERVATION_PERIOD_OPTIONS:
        selected_period = "24 h"
        st.session_state["observations_period"] = selected_period

    header_left, header_right = st.columns([2.2, 3.2], vertical_alignment="center")
    with header_left:
        st.html(
            """
            <div class="argos-observations-header">
                <strong>Observaciones</strong>
                <span>Meteorología de la finca</span>
            </div>
            """
        )
    with header_right:
        source_col, period_col, refresh_col = st.columns([0.95, 2.25, 0.8], vertical_alignment="center")
        with source_col:
            st.selectbox(
                "Fuente",
                ["Ecowitt"],
                key="observations_source",
                label_visibility="collapsed",
            )
        with period_col:
            selected_period = st.segmented_control(
                "Periodo",
                options=list(OBSERVATION_PERIOD_OPTIONS),
                default=selected_period,
                key="observations_period",
                label_visibility="collapsed",
            )
        with refresh_col:
            if st.button("Actualizar", icon=":material/refresh:", key="refresh_observations", width="stretch"):
                st.cache_data.clear()
                st.rerun()

    duration = OBSERVATION_PERIOD_OPTIONS[str(selected_period)]
    now = datetime.now(UTC)
    start, end = observation_period_range(now, duration)
    records = cached_observations(base_url, format_utc_iso(start), format_utc_iso(end))
    observations_df = dataframe_from_records(records, "observed_at_utc")
    observations_df = filter_observations_by_source(observations_df, ["DIRECT", "BACKFILLED"])
    render_observation_monitoring_view(
        observations_df,
        start=start,
        end=end,
        key_prefix=f"observations_{element_key('period', str(selected_period))}",
    )


def render_observation_monitoring_view(
    observations_df: pd.DataFrame,
    *,
    start: datetime,
    end: datetime,
    key_prefix: str,
) -> None:
    if observations_df.empty:
        st.info("No hay observaciones en el periodo seleccionado.")
        return

    latest = latest_observation_row(observations_df)
    st.html(observation_kpi_row_html(latest))

    xaxis_range = observation_local_xaxis_range(start, end)
    chart_specs = [
        ("Temperatura y humedad", build_observation_temperature_humidity_figure),
        ("Viento", build_observation_wind_figure),
        ("Radiación solar + UV", build_observation_radiation_uv_figure),
        ("Lluvia + presión", build_observation_rain_pressure_figure),
    ]
    first_row = st.columns(2, gap="small", vertical_alignment="top")
    second_row = st.columns(2, gap="small", vertical_alignment="top")
    for column, (title, builder) in zip([*first_row, *second_row], chart_specs, strict=True):
        with column:
            render_observation_chart_card(
                title,
                builder(observations_df, xaxis_range=xaxis_range),
                key=element_key(key_prefix, title),
            )

    st.html(observation_quality_bar_html(observations_df, start=start, end=end))
    with st.expander("Detalle / Estado de instrumentación", expanded=False, icon=":material/info:"):
        render_source_count_strip(observation_source_counts(observations_df))
        instrument_columns = [
            column
            for column in [
                "observed_at_utc",
                "source",
                "battery_voltage",
                "ws90_capacitor_voltage",
                "wind_direction_deg",
                "wind_direction_avg10m_deg",
            ]
            if column in observations_df
        ]
        if instrument_columns:
            st.dataframe(observations_df[instrument_columns].tail(200), hide_index=True)
        else:
            st.caption("No hay columnas instrumentales adicionales disponibles para este periodo.")
        st.dataframe(observations_df.tail(500), hide_index=True)
        add_csv_download(
            observations_df,
            "Descargar observaciones CSV",
            "argos_observations.csv",
            key=element_key(key_prefix, "download"),
        )


def render_observation_chart_card(title: str, figure: go.Figure | None, *, key: str) -> None:
    with st.container(border=True, gap="small"):
        st.html(section_header_html(title))
        if figure is None:
            st.caption("Sin datos suficientes para esta gráfica.")
            return
        st.plotly_chart(figure, width="stretch", key=key)


def latest_observation_row(frame: pd.DataFrame) -> pd.Series:
    if "observed_at_utc" in frame:
        ordered = frame.sort_values("observed_at_utc")
        return ordered.iloc[-1]
    return frame.iloc[-1]


def observation_kpi_row_html(latest: pd.Series) -> str:
    wind_direction = latest.get("wind_direction_deg", latest.get("wind_direction_avg10m_deg"))
    wind_label = f"Viento {wind_compass_label(wind_direction)}".strip()
    wind_value = f"{format_number(latest.get('wind_speed_ms'), 'm/s')} {wind_direction_arrow_from_value(wind_direction)}".strip()
    return f"""
    <div class="argos-observations-kpis">
        {observation_kpi_html("Temperatura", format_number(latest.get("outdoor_temperature_c"), "°C"), "thermostat")}
        {observation_kpi_html("Humedad", format_number(latest.get("outdoor_humidity_pct"), "%"), "humidity_percentage")}
        {observation_kpi_html("Presión", format_number(latest.get("relative_pressure_hpa", latest.get("absolute_pressure_hpa")), "hPa"), "speed")}
        {observation_kpi_html(wind_label, wind_value, "air")}
        {observation_kpi_html("Racha", format_number(latest.get("wind_gust_ms"), "m/s"), "airwave")}
        {observation_kpi_html("Lluvia 24 h", format_number(latest.get("rain_last_24h_mm"), "mm"), "rainy", secondary=f"Actual {format_number(latest.get('rain_rate_mm_h'), 'mm/h')}")}
        {observation_kpi_html("Radiación", format_number(latest.get("solar_radiation_wm2"), "W/m²"), "wb_sunny", secondary=f"UV {format_number(latest.get('uv_index'), '')}")}
    </div>
    """


def observation_kpi_html(label: str, value: str, icon: str, *, secondary: str | None = None) -> str:
    secondary_html = f"<small>{escape(secondary)}</small>" if secondary else ""
    return f"""
    <div class="argos-observation-kpi">
        <div>
            <b>{escape(value)}</b>
            <p>{escape(label)}</p>
            {secondary_html}
        </div>
    </div>
    """


def wind_direction_arrow_from_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        return wind_direction_arrow(float(value))
    except (TypeError, ValueError):
        return ""


def wind_compass_label(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, int | float):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return ""
    normalized = value % 360
    compass_points = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    return compass_points[int((normalized + 11.25) // 22.5) % len(compass_points)]


def observation_local_xaxis_range(start: datetime, end: datetime) -> list[datetime]:
    timezone = ZoneInfo(get_settings().local_timezone)
    return [
        start.astimezone(timezone).replace(tzinfo=None),
        end.astimezone(timezone).replace(tzinfo=None),
    ]


def build_observation_temperature_humidity_figure(frame: pd.DataFrame, *, xaxis_range: list[datetime]) -> go.Figure | None:
    return build_observation_compact_figure(
        frame,
        [
            ObservationSeries("outdoor_temperature_c", "Temperatura", "deg C", "#dc2626"),
            ObservationSeries("outdoor_humidity_pct", "Humedad relativa", "% HR", "#2563eb", secondary_y=True),
        ],
        primary_title="Temperatura, deg C",
        secondary_title="Humedad, %",
        xaxis_range=xaxis_range,
    )


def build_observation_wind_figure(frame: pd.DataFrame, *, xaxis_range: list[datetime]) -> go.Figure | None:
    figure = build_observation_compact_figure(
        frame,
        [
            ObservationSeries("wind_speed_ms", "Velocidad", "m/s", "#2563eb"),
            ObservationSeries("wind_gust_ms", "Racha", "m/s", "#dc2626"),
        ],
        primary_title="Viento, m/s",
        xaxis_range=xaxis_range,
    )
    if figure is None:
        return None
    direction_column = "wind_direction_deg" if "wind_direction_deg" in frame else "wind_direction_avg10m_deg"
    if direction_column in frame and "observed_at_utc" in frame:
        direction_frame = frame[["observed_at_utc", direction_column]].copy()
        direction_frame[direction_column] = pd.to_numeric(direction_frame[direction_column], errors="coerce")
        direction_frame = direction_frame.dropna()
        if not direction_frame.empty:
            sampled = direction_frame.iloc[:: max(1, len(direction_frame) // 20)]
            figure.add_trace(
                go.Scatter(
                    x=local_time_values(sampled["observed_at_utc"]),
                    y=[0 for _ in range(len(sampled))],
                    mode="text",
                    text=[wind_direction_arrow(value) for value in sampled[direction_column]],
                    textfont={"size": 14, "color": "#111827"},
                    name="Dirección",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
    return figure


def build_observation_radiation_uv_figure(frame: pd.DataFrame, *, xaxis_range: list[datetime]) -> go.Figure | None:
    return build_observation_compact_figure(
        frame,
        [
            ObservationSeries("solar_radiation_wm2", "Radiación solar", "W/m2", "#f59e0b"),
            ObservationSeries("uv_index", "UV", "UV", "#7c3aed", secondary_y=True),
        ],
        primary_title="Radiación, W/m2",
        secondary_title="UV",
        xaxis_range=xaxis_range,
    )


def build_observation_rain_pressure_figure(frame: pd.DataFrame, *, xaxis_range: list[datetime]) -> go.Figure | None:
    plot_frame = with_local_observed_time(frame)
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    has_trace = False
    if "rain_rate_mm_h" in plot_frame:
        rain_frame = numeric_observation_frame(plot_frame, "rain_rate_mm_h")
        if not rain_frame.empty:
            figure.add_trace(
                go.Bar(
                    x=rain_frame["observed_at_utc"],
                    y=rain_frame["rain_rate_mm_h"],
                    name="Lluvia",
                    marker={"color": "#2563eb"},
                    opacity=0.72,
                ),
                secondary_y=False,
            )
            has_trace = True
    pressure_column = "relative_pressure_hpa" if "relative_pressure_hpa" in plot_frame else "absolute_pressure_hpa"
    if pressure_column in plot_frame:
        pressure_frame = numeric_observation_frame(plot_frame, pressure_column)
        if not pressure_frame.empty:
            figure.add_trace(
                go.Scatter(
                    x=pressure_frame["observed_at_utc"],
                    y=pressure_frame[pressure_column],
                    mode="lines",
                    name="Presión",
                    line={"color": "#0f766e", "width": 2},
                ),
                secondary_y=True,
            )
            has_trace = True
    if not has_trace:
        return None
    apply_observation_compact_layout(
        figure,
        primary_title="Lluvia, mm/h",
        secondary_title="Presión, hPa",
        xaxis_range=xaxis_range,
        show_secondary=True,
    )
    return figure


def build_observation_compact_figure(
    frame: pd.DataFrame,
    series: list[ObservationSeries],
    *,
    primary_title: str,
    xaxis_range: list[datetime],
    secondary_title: str | None = None,
) -> go.Figure | None:
    plot_frame = with_local_observed_time(frame)
    figure = make_subplots(specs=[[{"secondary_y": secondary_title is not None}]])
    has_trace = False
    for item in series:
        if item.column not in plot_frame:
            continue
        series_frame = numeric_observation_frame(plot_frame, item.column)
        if series_frame.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=series_frame["observed_at_utc"],
                y=series_frame[item.column],
                mode="lines",
                name=item.label,
                line={"color": item.color, "width": 2},
            ),
            secondary_y=item.secondary_y,
        )
        has_trace = True
    if not has_trace:
        return None
    apply_observation_compact_layout(
        figure,
        primary_title=primary_title,
        secondary_title=secondary_title,
        xaxis_range=xaxis_range,
        show_secondary=secondary_title is not None,
    )
    return figure


def numeric_observation_frame(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    series_frame = frame[["observed_at_utc", column]].copy()
    series_frame[column] = pd.to_numeric(series_frame[column], errors="coerce")
    return series_frame.dropna()


def apply_observation_compact_layout(
    figure: go.Figure,
    *,
    primary_title: str,
    xaxis_range: list[datetime],
    secondary_title: str | None = None,
    show_secondary: bool = False,
) -> None:
    figure.update_layout(
        height=235,
        margin={"t": 12, "r": 44 if show_secondary else 18, "b": 28, "l": 42},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 10},
            "bgcolor": "rgba(255,255,255,0.86)",
        },
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        xaxis={"range": xaxis_range, "title": local_time_axis_title()},
        yaxis={"title": primary_title, "rangemode": "tozero", "gridcolor": "rgba(148, 163, 184, 0.24)"},
    )
    figure.update_xaxes(tickfont={"size": 10}, title_font={"size": 10})
    figure.update_yaxes(tickfont={"size": 10}, title_font={"size": 10})
    if show_secondary:
        figure.update_yaxes(
            title_text=secondary_title,
            showgrid=False,
            tickfont={"size": 10},
            title_font={"size": 10},
            secondary_y=True,
        )


def observation_quality_bar_html(frame: pd.DataFrame, *, start: datetime, end: datetime) -> str:
    sample_count = len(frame)
    latest = latest_observation_row(frame)
    latest_sample = format_compact_local_datetime(latest.get("observed_at_utc"))
    coverage, gaps = observation_period_quality(frame, start=start, end=end)
    coverage_html = shell_pill_html("Cobertura", f"{coverage:.1f}%") if coverage is not None else ""
    gaps_html = shell_pill_html("Huecos", str(gaps)) if gaps is not None else ""
    return f"""
    <div class="argos-observations-quality">
        <div>
            {shell_pill_html("Fuente", "Ecowitt")}
            {shell_pill_html("Última muestra", latest_sample)}
            {coverage_html}
            {shell_pill_html("Muestras", str(sample_count))}
            {gaps_html}
        </div>
        <span>Detalle ›</span>
    </div>
    """


def observation_period_quality(
    frame: pd.DataFrame,
    *,
    start: datetime,
    end: datetime,
) -> tuple[float | None, int | None]:
    if frame.empty or "observed_at_utc" not in frame:
        return None, None
    timestamps = pd.to_datetime(frame["observed_at_utc"], format="ISO8601", errors="coerce", utc=True).dropna().sort_values()
    if len(timestamps) < 2:
        return None, None
    deltas = timestamps.diff().dropna()
    median_delta = deltas.median()
    if pd.isna(median_delta) or median_delta <= pd.Timedelta(0):
        return None, None
    expected = max(1, int(math.floor((end - start) / median_delta)) + 1)
    coverage = min(100.0, len(timestamps.drop_duplicates()) / expected * 100)
    gaps = int((deltas > median_delta * 1.5).sum())
    return coverage, gaps


def render_observation_period(
    observations_df: pd.DataFrame,
    selected_variables: list[str],
    label: str,
    *,
    key_prefix: str,
    show_recent_meteogram: bool = False,
    meteogram_wind_frequency: str = "1h",
) -> None:
    st.caption(label)
    if observations_df.empty:
        st.info("No observations in the selected range.")
        return

    if show_recent_meteogram:
        with st.container(border=True):
            st.subheader("Meteograma")
            st.plotly_chart(
                build_recent_weather_figure(observations_df, wind_frequency=meteogram_wind_frequency),
                width="stretch",
                key=element_key(key_prefix, "recent_meteogram"),
            )

    available_variables = [variable for variable in selected_variables if variable in observations_df.columns]
    grouped_figures = build_observation_group_figures(observations_df, available_variables)
    if not grouped_figures:
        st.warning("Select at least one available variable.")
    for title, figure in grouped_figures:
        with st.container(border=True):
            st.subheader(title)
            st.plotly_chart(figure, width="stretch", key=element_key(key_prefix, title))

    with st.container(border=True):
        st.subheader("Observation table")
        st.dataframe(observations_df, hide_index=True)
        add_csv_download(
            observations_df,
            "Download observations CSV",
            "argos_observations.csv",
            key=element_key(key_prefix, "download"),
        )


def observation_period_range(now: datetime, duration: timedelta) -> tuple[datetime, datetime]:
    end = now.astimezone(UTC)
    return end - duration, end


def observation_period_uses_recent_meteogram(label: str) -> bool:
    return label in {"Day", "Week"}


def observation_period_meteogram_wind_frequency(label: str) -> str:
    return "3h" if label == "Week" else "1h"


def format_utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def with_local_observed_time(frame: pd.DataFrame) -> pd.DataFrame:
    if "observed_at_utc" not in frame:
        return frame
    local_frame = frame.copy()
    local_frame["observed_at_utc"] = local_time_values(local_frame["observed_at_utc"])
    return local_frame


def local_time_values(values: pd.Series) -> pd.Series:
    timezone = ZoneInfo(get_settings().local_timezone)
    return pd.to_datetime(values, format="ISO8601", errors="coerce", utc=True).dt.tz_convert(timezone).dt.tz_localize(None)


def local_time_axis_title() -> str:
    return f"Tiempo local ({get_settings().local_timezone})"


def format_period_duration(duration: timedelta) -> str:
    days = duration.days
    if days == 1:
        return "24 horas"
    if days == 7:
        return "7 días"
    if days == 30:
        return "30 días"
    if days == 365:
        return "365 días"
    return str(duration)


def element_key(prefix: str, value: str) -> str:
    safe_value = "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_")
    return f"{prefix}_{safe_value}"


def build_observation_group_figures(frame: pd.DataFrame, selected_variables: list[str]) -> list[tuple[str, go.Figure]]:
    groups = [
        (
            "Temperatura y humedad relativa",
            [
                ObservationSeries("outdoor_temperature_c", "Temperatura", "deg C", "#2563eb"),
                ObservationSeries("outdoor_humidity_pct", "Humedad relativa", "% HR", "#0f766e", secondary_y=True),
            ],
        ),
        (
            "Precipitación",
            [
                ObservationSeries("rain_rate_mm_h", "Intensidad", "mm/h", "#2563eb", mode="lines"),
                ObservationSeries("rain_hour_mm", "Hora", "mm", "#0f766e"),
                ObservationSeries("rain_last_24h_mm", "24 h", "mm", "#7c3aed"),
                ObservationSeries("rain_day_mm", "Día", "mm", "#f97316"),
            ],
        ),
        (
            "Presiones",
            [
                ObservationSeries("absolute_pressure_hpa", "Absoluta", "hPa", "#2563eb"),
                ObservationSeries("relative_pressure_hpa", "Relativa", "hPa", "#0f766e"),
            ],
        ),
        (
            "Viento",
            [
                ObservationSeries("wind_speed_ms", "Media", "m/s", "#2563eb"),
                ObservationSeries("wind_gust_ms", "Racha", "m/s", "#ef4444"),
            ],
        ),
        (
            "Dirección de viento",
            [
                ObservationSeries("wind_direction_deg", "Dirección", "deg", "#2563eb", mode="markers"),
                ObservationSeries("wind_direction_avg10m_deg", "Media 10 min", "deg", "#0f766e", mode="markers"),
            ],
        ),
        (
            "Irradiancia y UV",
            [
                ObservationSeries("solar_radiation_wm2", "Irradiancia", "W/m2", "#f97316"),
                ObservationSeries("uv_index", "UV", "UV", "#7c3aed", secondary_y=True),
            ],
        ),
    ]
    figures = [
        (title, figure)
        for title, series in groups
        if (figure := build_observation_group_figure(frame, selected_variables, title, series)) is not None
    ]
    grouped_columns = {item.column for _title, series in groups for item in series}
    figures.extend(build_remaining_observation_figures(frame, selected_variables, grouped_columns))
    return figures


def build_remaining_observation_figures(
    frame: pd.DataFrame,
    selected_variables: list[str],
    grouped_columns: set[str],
) -> list[tuple[str, go.Figure]]:
    remaining_by_unit: dict[str, list[ObservationSeries]] = {}
    for index, column in enumerate(selected_variables):
        if column in grouped_columns or column not in frame or column == "observed_at_utc":
            continue
        numeric_values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if numeric_values.empty:
            continue
        unit = OBSERVATION_UNITS.get(column, "Valor")
        remaining_by_unit.setdefault(unit, []).append(
            ObservationSeries(
                column,
                LABELS.get(column, column),
                unit,
                OBSERVATION_COLORS[index % len(OBSERVATION_COLORS)],
            )
        )

    figures: list[tuple[str, go.Figure]] = []
    for unit, series in remaining_by_unit.items():
        title = "Otras variables medidas" if unit == "Valor" else f"Otras variables medidas ({unit})"
        figure = build_observation_group_figure(frame, selected_variables, title, series)
        if figure is not None:
            figures.append((title, figure))
    return figures


@dataclass(frozen=True)
class ObservationSeries:
    column: str
    label: str
    unit: str
    color: str
    mode: str = "lines+markers"
    secondary_y: bool = False


def build_observation_group_figure(
    frame: pd.DataFrame,
    selected_variables: list[str],
    title: str,
    series: list[ObservationSeries],
) -> go.Figure | None:
    frame = with_local_observed_time(frame)
    selected = set(selected_variables)
    figure = go.Figure()
    plotted_series = [item for item in series if item.column in selected and item.column in frame]
    for item in plotted_series:
        series_frame = frame[["observed_at_utc", item.column]].copy()
        series_frame[item.column] = pd.to_numeric(series_frame[item.column], errors="coerce")
        series_frame = series_frame.dropna()
        if series_frame.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=series_frame["observed_at_utc"],
                y=series_frame[item.column],
                mode=item.mode,
                name=item.label,
                line={"color": item.color, "width": 2},
                marker={"color": item.color, "size": 5},
                yaxis="y2" if item.secondary_y else None,
            )
        )
    if not figure.data:
        return None

    primary_unit = next((item.unit for item in plotted_series if not item.secondary_y), "Valor")
    secondary_unit = next((item.unit for item in plotted_series if item.secondary_y), None)
    layout: dict[str, Any] = {
        "height": DUAL_AXIS_CHART_HEIGHT if secondary_unit else SINGLE_AXIS_CHART_HEIGHT,
        "margin": {"t": 8, "r": 48 if secondary_unit else 22, "b": 28, "l": 42},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        "xaxis_title": local_time_axis_title(),
        "yaxis": {"title": primary_unit, "showgrid": True, "nticks": 7},
    }
    if secondary_unit:
        layout["yaxis2"] = synced_secondary_yaxis(secondary_unit)
    if title == "Dirección de viento":
        layout["yaxis"] = {
            "title": "deg",
            "range": [0, 360],
            "tickmode": "array",
            "tickvals": [0, 90, 180, 270, 360],
            "ticktext": ["N", "E", "S", "W", "N"],
        }
    if title == "Temperatura y humedad relativa":
        layout["yaxis2"] = synced_secondary_yaxis("% HR", value_range=[0, 100])
    figure.update_layout(**layout)
    return figure


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


def render_analysis(base_url: str) -> None:
    try:
        variables = cached_analytics_variables(base_url)
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    if not variables:
        st.info("No hay variables analíticas disponibles.")
        return

    st.title("Análisis")
    st.caption("Herramienta transversal para comparar variables reales de ARGOS sin modificar los datos originales.")
    filters = render_analysis_common_filters()
    correlation_tab, distributions_tab, trends_tab = st.tabs(["Correlaciones", "Distribuciones", "Tendencias y referencias"])
    with correlation_tab:
        render_analysis_correlations(base_url, variables, filters)
    with distributions_tab:
        render_analysis_distributions(base_url, variables, filters)
    with trends_tab:
        render_analysis_trends(base_url, variables, filters)


def render_analysis_common_filters() -> dict[str, Any]:
    st.session_state.setdefault("analysis_filters", default_analysis_filters())
    current = dict(st.session_state["analysis_filters"])
    with st.form("analysis_common_filters"):
        with st.container(border=True, gap="small"):
            quick_col, start_col, end_col, freq_col, zone_col, quality_col, action_col = st.columns([1, 1, 1, 0.9, 1, 0.9, 0.9])
            with quick_col:
                quick = st.selectbox("Periodo", ["Últimos 7 días", "Últimos 30 días", "Últimos 90 días", "Año actual", "Último año", "Todo el periodo", "Personalizado"], index=1)
            default_start, default_end = analysis_quick_dates(quick, current)
            with start_col:
                start_date = st.date_input("Inicio", value=default_start, key="analysis_start_date")
            with end_col:
                end_date = st.date_input("Fin", value=default_end, key="analysis_end_date")
            with freq_col:
                frequency = st.selectbox("Frecuencia", ["original", "hourly", "daily", "weekly", "monthly"], index=["original", "hourly", "daily", "weekly", "monthly"].index(current["frequency"]), format_func=analysis_frequency_label)
            with zone_col:
                zone_slug = st.selectbox("Zona/AOI", ["", "olivos_pequenos", "olivos_grandes", "casa", "arqueta", "otra"], index=0, format_func=lambda value: "Todas" if not value else FIELD_ZONE_LABELS.get(value, value))
            with quality_col:
                quality = st.selectbox("Calidad", ["", "valid", "partial", "invalid"], index=0, format_func=lambda value: "Todas" if not value else SATELLITE_QUALITY_LABELS.get(value, value))
            with action_col:
                st.write("")
                apply = st.form_submit_button("Aplicar", type="primary")
                reset = st.form_submit_button("Restablecer")
    if reset:
        st.session_state["analysis_filters"] = default_analysis_filters()
        st.rerun()
    if apply:
        st.session_state["analysis_filters"] = {
            "start": None if quick == "Todo el periodo" else local_datetime_to_utc_iso(start_date, time.min),
            "end": None if quick == "Todo el periodo" else local_datetime_to_utc_iso(end_date, time.max.replace(microsecond=0)),
            "frequency": frequency,
            "zone_slug": zone_slug or None,
            "quality_status": quality or None,
        }
    return dict(st.session_state["analysis_filters"])


def render_analysis_correlations(base_url: str, variables: list[dict[str, Any]], filters: dict[str, Any]) -> None:
    mode = st.segmented_control("Modo", ["Dos variables", "Matriz"], default="Dos variables", key="analysis_corr_mode")
    options = [variable["variable_id"] for variable in variables]
    if mode == "Matriz":
        with st.form("analysis_matrix_form"):
            selected = st.multiselect("Variables", options, default=options[: min(4, len(options))], max_selections=12, format_func=lambda value: analytics_variable_label(value, variables))
            method = st.selectbox("Método", ["pearson", "spearman"], key="analysis_matrix_method")
            submit = st.form_submit_button("Calcular matriz", type="primary")
        if submit:
            st.session_state["analysis_matrix_payload"] = {**filters, "variable_ids": selected, "method": method}
        if "analysis_matrix_payload" not in st.session_state:
            st.caption("Seleccione de 2 a 12 variables y pulse Calcular matriz.")
            return
        try:
            result = cached_analytics_correlation_matrix(base_url, st.session_state["analysis_matrix_payload"])
        except ArgosApiError as exc:
            st.error(str(exc))
            return
        render_correlation_matrix_result(result)
        return

    with st.form("analysis_correlation_form"):
        x_col, y_col, agg_col, lag_col, method_col, missing_col = st.columns([1.4, 1.4, 0.95, 0.8, 0.8, 1.1])
        with x_col:
            variable_x = st.selectbox("Variable X", options, format_func=lambda value: analytics_variable_label(value, variables), key="analysis_corr_x")
        with y_col:
            variable_y = st.selectbox("Variable Y", options, index=min(1, len(options) - 1), format_func=lambda value: analytics_variable_label(value, variables), key="analysis_corr_y")
        with agg_col:
            aggregation = st.selectbox("Agregación", analytics_common_aggregations(variable_x, variable_y, variables), key="analysis_corr_agg")
        with lag_col:
            lag = st.selectbox("Lag", ["0", "-1h", "+1h", "-3h", "+3h", "-6h", "+6h", "-1d", "+1d", "-3d", "+3d", "-7d", "+7d"], key="analysis_corr_lag")
        with method_col:
            method = st.selectbox("Método", ["pearson", "spearman"], key="analysis_corr_method")
        with missing_col:
            missing = st.selectbox("Ausentes", ["intersection", "linear_interpolation"], format_func=analysis_missing_label, key="analysis_corr_missing")
        show_regression = st.checkbox("Regresión lineal", value=True, key="analysis_corr_regression")
        swap = st.form_submit_button("Intercambiar X/Y")
        submit = st.form_submit_button("Analizar", type="primary")
    if swap:
        st.session_state["analysis_corr_x"], st.session_state["analysis_corr_y"] = variable_y, variable_x
        st.rerun()
    if submit:
        st.session_state["analysis_corr_payload"] = {**filters, "variable_x": variable_x, "variable_y": variable_y, "aggregation_x": aggregation, "aggregation_y": aggregation, "lag": lag, "method": method, "missing": missing}
        st.session_state["analysis_corr_regression_enabled"] = show_regression
    if "analysis_corr_payload" not in st.session_state:
        st.caption("Configure dos variables y pulse Analizar.")
        return
    try:
        result = cached_analytics_correlation(base_url, st.session_state["analysis_corr_payload"])
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    render_correlation_result(result, show_regression=st.session_state.get("analysis_corr_regression_enabled", True))


def render_analysis_distributions(base_url: str, variables: list[dict[str, Any]], filters: dict[str, Any]) -> None:
    options = [variable["variable_id"] for variable in variables]
    with st.form("analysis_distribution_form"):
        variable_col, agg_col, bins_col, density_col, compare_col = st.columns([1.7, 1, 0.8, 0.8, 1])
        with variable_col:
            variable_id = st.selectbox("Variable", options, format_func=lambda value: analytics_variable_label(value, variables), key="analysis_dist_variable")
        with agg_col:
            aggregation = st.selectbox("Agregación", analytics_variable_aggregations(variable_id, variables), key="analysis_dist_agg")
        with bins_col:
            bins = st.selectbox("Intervalos", ["auto", 10, 20, 30, 50], key="analysis_dist_bins")
        with density_col:
            density = st.checkbox("Densidad", key="analysis_dist_density")
        with compare_col:
            compare_enabled = st.checkbox("Comparar con", key="analysis_dist_compare")
        compare_variable = None
        if compare_enabled:
            compare_variable = st.selectbox("Variable/fuente comparable", options, index=options.index(variable_id), format_func=lambda value: analytics_variable_label(value, variables), key="analysis_dist_compare_variable")
        submit = st.form_submit_button("Analizar distribución", type="primary")
    if submit:
        st.session_state["analysis_dist_payload"] = {**filters, "variable_id": variable_id, "aggregation": aggregation, "bins": bins, "density": density}
        st.session_state["analysis_dist_compare_selected"] = compare_variable if compare_enabled else None
    if "analysis_dist_payload" not in st.session_state:
        st.caption("Seleccione una variable y pulse Analizar distribución.")
        return
    try:
        result = cached_analytics_distribution(base_url, st.session_state["analysis_dist_payload"])
        compare_result = None
        if st.session_state.get("analysis_dist_compare_selected"):
            compare_result = cached_analytics_distribution(base_url, {**st.session_state["analysis_dist_payload"], "variable_id": st.session_state["analysis_dist_compare_selected"]})
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    render_distribution_result(result, compare_result, density=bool(st.session_state["analysis_dist_payload"].get("density")))


def render_analysis_trends(base_url: str, variables: list[dict[str, Any]], filters: dict[str, Any]) -> None:
    options = [variable["variable_id"] for variable in variables]
    with st.form("analysis_trend_form"):
        variable_col, agg_col, ref_col, smooth_col, events_col = st.columns([1.7, 1, 1.2, 0.8, 0.9])
        with variable_col:
            variable_id = st.selectbox("Variable", options, format_func=lambda value: analytics_variable_label(value, variables), key="analysis_trend_variable")
        with agg_col:
            aggregation = st.selectbox("Agregación", analytics_variable_aggregations(variable_id, variables), key="analysis_trend_agg")
        with ref_col:
            reference = st.selectbox("Referencia", ["period_mean", "period_median", "moving_average", "linear_trend", "none"], format_func=analysis_reference_label, key="analysis_trend_reference")
        with smooth_col:
            moving_window = st.number_input("Ventana", min_value=2, max_value=365, value=7, key="analysis_trend_window")
        with events_col:
            include_events = st.checkbox("Eventos", value=False, key="analysis_trend_events")
        submit = st.form_submit_button("Analizar tendencia", type="primary")
    if submit:
        st.session_state["analysis_trend_payload"] = {**filters, "variable_id": variable_id, "aggregation": aggregation, "reference": reference, "moving_window": int(moving_window), "include_field_events": include_events}
    if "analysis_trend_payload" not in st.session_state:
        st.caption("Seleccione una variable y pulse Analizar tendencia.")
        return
    try:
        result = cached_analytics_trend(base_url, st.session_state["analysis_trend_payload"])
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    render_trend_analysis_result(result)


def render_trends(base_url: str) -> None:
    start_iso, end_iso, selected_variables, selected_sources = render_trend_filters()
    records = cached_observations(base_url, start_iso, end_iso)
    observations_df = dataframe_from_records(records, "observed_at_utc")
    observations_df = filter_observations_by_source(observations_df, selected_sources)

    if observations_df.empty:
        st.info("No observations in the selected range.")
        return

    numeric_variables = [
        variable
        for variable in selected_variables
        if variable in observations_df.columns and pd.api.types.is_numeric_dtype(observations_df[variable])
    ]
    if not numeric_variables:
        st.info("Select at least one numeric variable.")
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
    trend_plot_df = with_local_observed_time(trend_df)

    with st.container(horizontal=True):
        st.metric("Samples", summary.sample_count, border=True)
        st.metric("Mean", format_number(summary.mean, ""), border=True)
        st.metric("Slope / sample", format_number(summary.slope_per_sample, ""), border=True)
        st.metric("Slope / day", format_number(summary.slope_per_day, ""), border=True)
        st.metric("R2", format_number(summary.r_squared, ""), border=True)
        st.metric("Estimated change", format_number(summary.estimated_change, ""), border=True)

    plot_df = trend_plot_df.melt(
        id_vars=["observed_at_utc"],
        value_vars=["value", "rolling_mean", "trend_line"],
        var_name="Series",
        value_name="Value",
    ).dropna()
    plot_df["Series"] = plot_df["Series"].map(
        {"value": "Value", "rolling_mean": "Moving average", "trend_line": "Linear trend"}
    )
    figure = px.line(plot_df, x="observed_at_utc", y="Value", color="Series", markers=True)
    figure.update_layout(xaxis_title=local_time_axis_title(), yaxis_title=LABELS.get(variable, variable), legend_title_text="")
    st.plotly_chart(figure, width="stretch")

    anomaly = trend_plot_df[["observed_at_utc", "anomaly"]].dropna()
    if not anomaly.empty:
        anomaly_figure = px.bar(anomaly, x="observed_at_utc", y="anomaly")
        anomaly_figure.update_layout(xaxis_title=local_time_axis_title(), yaxis_title="Anomaly from selected period mean")
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


def render_trend_filters() -> tuple[str, str, list[str], list[str]]:
    today = date.today()
    default_start = today - timedelta(days=30)
    with st.container(border=True):
        st.subheader("Filtros")
        selected_dates = st.date_input(
            "Rango temporal",
            value=(default_start, today),
            min_value=date(2000, 1, 1),
            max_value=today,
            key="trends_date_range",
        )
        if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
            start_date, end_date = selected_dates
        else:
            start_date = end_date = today

        variable_options = list(LABELS)
        default_variables = [variable for variable in DEFAULT_VARIABLES if variable in variable_options]
        selected_variables = st.multiselect(
            "Variables",
            options=variable_options,
            default=default_variables,
            key="trends_variables",
        )
        selected_sources = st.pills(
            "Fuentes",
            options=["DIRECT", "BACKFILLED"],
            default=["DIRECT", "BACKFILLED"],
            selection_mode="multi",
            key="trends_sources",
        )

    start_iso = format_utc_iso(datetime.combine(start_date, time.min, tzinfo=UTC))
    end_iso = format_utc_iso(datetime.combine(end_date, time.max, tzinfo=UTC))
    return start_iso, end_iso, selected_variables, list(selected_sources or [])


def render_correlation_result(result: dict[str, Any], *, show_regression: bool) -> None:
    points = pd.DataFrame.from_records(result.get("points", []))
    if points.empty:
        st.warning("Datos insuficientes para calcular correlación.")
        render_analysis_warnings(result.get("warnings", []))
        return
    x_label = analytics_result_label(result["variable_x"])
    y_label = analytics_result_label(result["variable_y"])
    with st.container(horizontal=True):
        st.metric("Correlación", format_number(result.get("correlation"), ""), border=True)
        st.metric("Pares válidos", result.get("pairs_count", 0), border=True)
        st.metric("Pendiente", format_number(result.get("slope"), ""), border=True)
        st.metric("R2", format_number(result.get("r_squared"), ""), border=True)
    scatter = px.scatter(points, x="x", y="y", hover_data=["timestamp_local"], labels={"x": x_label, "y": y_label})
    if show_regression and result.get("slope") is not None and result.get("intercept") is not None:
        x_sorted = points["x"].sort_values()
        scatter.add_trace(
            go.Scatter(
                x=x_sorted,
                y=result["intercept"] + result["slope"] * x_sorted,
                mode="lines",
                name="Regresión lineal",
                line={"color": "#ef4444"},
            )
        )
    scatter.update_layout(height=360)
    st.plotly_chart(scatter, width="stretch")
    time_frame = points.melt(id_vars=["timestamp_local"], value_vars=["x", "y"], var_name="Variable", value_name="Valor")
    time_frame["Variable"] = time_frame["Variable"].map({"x": x_label, "y": y_label})
    series_figure = px.line(time_frame, x="timestamp_local", y="Valor", color="Variable")
    series_figure.update_layout(height=260, xaxis_title=local_time_axis_title())
    st.plotly_chart(series_figure, width="stretch")
    add_csv_download(points, "Descargar CSV", "argos_analisis_correlacion.csv", key="analysis_corr_csv")
    render_analysis_warnings(result.get("warnings", []))


def render_correlation_matrix_result(result: dict[str, Any]) -> None:
    labels = [analytics_result_label(variable) for variable in result.get("variables", [])]
    variable_ids = [variable["variable_id"] for variable in result.get("variables", [])]
    matrix = result.get("matrix", [])
    if not labels or not matrix:
        st.warning("Sin datos suficientes para la matriz.")
        return
    points = pd.DataFrame.from_records(
        [
            {"timestamp_local": point.get("timestamp_local"), **point.get("values", {})}
            for point in result.get("points", [])
        ]
    )
    pair_grid_rendered = not points.empty and bool(variable_ids)
    if pair_grid_rendered:
        figure = build_correlation_pair_grid(points, variable_ids, labels, matrix)
    else:
        figure = go.Figure(
            data=go.Heatmap(
                z=matrix,
                x=labels,
                y=labels,
                zmin=-1,
                zmax=1,
                colorscale="RdBu",
                reversescale=True,
                text=[[format_number(value, "") for value in row] for row in matrix],
                texttemplate="%{text}",
            )
        )
        figure.update_layout(height=520)
    st.plotly_chart(figure, width="content" if pair_grid_rendered else "stretch")
    pair_counts = pd.DataFrame(result.get("pair_counts", []), index=labels, columns=labels)
    with st.expander("Pares válidos por combinación"):
        st.dataframe(pair_counts)
    render_analysis_warnings(result.get("warnings", []))


def build_correlation_pair_grid(
    points: pd.DataFrame,
    variable_ids: list[str],
    labels: list[str],
    matrix: list[list[float | None]],
) -> go.Figure:
    size = len(variable_ids)
    figure = make_subplots(
        rows=size,
        cols=size,
        horizontal_spacing=0.004,
        vertical_spacing=0.004,
    )
    for row_index, y_variable in enumerate(variable_ids, start=1):
        for column_index, x_variable in enumerate(variable_ids, start=1):
            x_values = pd.to_numeric(points[x_variable], errors="coerce") if x_variable in points else pd.Series(dtype="float64")
            y_values = pd.to_numeric(points[y_variable], errors="coerce") if y_variable in points else pd.Series(dtype="float64")
            if row_index == column_index:
                figure.add_trace(
                    go.Histogram(
                        x=x_values.dropna(),
                        marker={"color": "#22d3ee", "line": {"color": "#111827", "width": 1}},
                        opacity=0.9,
                        showlegend=False,
                        nbinsx=12,
                        hovertemplate=f"{labels[row_index - 1]}<br>%{{x:.2f}}<br>n=%{{y}}<extra></extra>",
                    ),
                    row=row_index,
                    col=column_index,
                )
                add_pair_grid_annotation(
                    figure,
                    row_index,
                    column_index,
                    size,
                    f"<b>{shorten_chart_label(labels[row_index - 1])}</b>",
                    font_size=10,
                    x=0.05,
                    y=0.92,
                    xanchor="left",
                )
            elif row_index > column_index:
                pair_frame = pd.DataFrame({"x": x_values, "y": y_values}).dropna()
                figure.add_trace(
                    go.Scattergl(
                        x=pair_frame["x"],
                        y=pair_frame["y"],
                        mode="markers",
                        marker={"color": "#111827", "size": 5, "opacity": 0.78},
                        showlegend=False,
                        hovertemplate=f"{labels[column_index - 1]}=%{{x:.2f}}<br>{labels[row_index - 1]}=%{{y:.2f}}<extra></extra>",
                    ),
                    row=row_index,
                    col=column_index,
                )
                smooth_x, smooth_y = smoothed_pair_line(pair_frame)
                if len(smooth_x) >= 2:
                    figure.add_trace(
                        go.Scatter(
                            x=smooth_x,
                            y=smooth_y,
                            mode="lines",
                            line={"color": "#ef4444", "width": 2},
                            showlegend=False,
                            hoverinfo="skip",
                        ),
                        row=row_index,
                        col=column_index,
                    )
            else:
                figure.add_trace(
                    go.Scatter(
                        x=[0],
                        y=[0],
                        mode="markers",
                        marker={"opacity": 0},
                        showlegend=False,
                        hoverinfo="skip",
                    ),
                    row=row_index,
                    col=column_index,
                )
                value = matrix[row_index - 1][column_index - 1]
                add_pair_grid_annotation(
                    figure,
                    row_index,
                    column_index,
                    size,
                    format_number(value, ""),
                    font_size=22,
                )
    add_pair_grid_cell_borders(figure, size)
    for row_index in range(1, size + 1):
        for column_index in range(1, size + 1):
            axis = figure.get_subplot(row_index, column_index)
            if axis.xaxis is not None:
                axis.xaxis.update(
                    showgrid=False,
                    zeroline=False,
                    showline=True,
                    linecolor="#111827",
                    linewidth=1,
                    mirror=True,
                    title_text=shorten_chart_label(labels[column_index - 1]) if row_index == size else "",
                    tickfont={"size": 9},
                    title_font={"size": 10},
                    showticklabels=row_index in {1, size},
                )
            if axis.yaxis is not None:
                axis.yaxis.update(
                    showgrid=False,
                    zeroline=False,
                    showline=True,
                    linecolor="#111827",
                    linewidth=1,
                    mirror=True,
                    title_text=shorten_chart_label(labels[row_index - 1]) if column_index == 1 else "",
                    tickfont={"size": 9},
                    title_font={"size": 10},
                    showticklabels=column_index in {1, size},
                    side="right" if column_index == size else "left",
                )
    figure.update_layout(
        width=max(560, min(1180, 180 * size)),
        height=max(560, min(1180, 180 * size)),
        bargap=0.04,
        margin={"l": 86, "r": 28, "t": 24, "b": 82},
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    return figure


def add_pair_grid_cell_borders(figure: go.Figure, grid_size: int) -> None:
    for row in range(1, grid_size + 1):
        for column in range(1, grid_size + 1):
            axis = figure.get_subplot(row, column)
            if axis.xaxis is None or axis.yaxis is None:
                continue
            x_domain = axis.xaxis.domain
            y_domain = axis.yaxis.domain
            figure.add_shape(
                type="rect",
                xref="paper",
                yref="paper",
                x0=x_domain[0],
                x1=x_domain[1],
                y0=y_domain[0],
                y1=y_domain[1],
                fillcolor="rgba(255,255,255,0)",
                line={"color": "#111827", "width": 1},
                layer="below",
            )


def add_pair_grid_annotation(
    figure: go.Figure,
    row: int,
    column: int,
    grid_size: int,
    text: str,
    *,
    font_size: int,
    x: float = 0.5,
    y: float = 0.5,
    xanchor: str = "center",
) -> None:
    axis_index = (row - 1) * grid_size + column
    axis_suffix = "" if axis_index == 1 else str(axis_index)
    figure.add_annotation(
        x=x,
        y=y,
        xref=f"x{axis_suffix} domain",
        yref=f"y{axis_suffix} domain",
        text=text,
        showarrow=False,
        font={"size": font_size, "color": "#111827"},
        xanchor=xanchor,
    )


def smoothed_pair_line(pair_frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if len(pair_frame) < 3 or pair_frame["x"].nunique() < 2:
        return pd.Series(dtype="float64"), pd.Series(dtype="float64")
    ordered = pair_frame.sort_values("x")
    window = max(3, min(9, math.ceil(len(ordered) / 5)))
    smooth_y = ordered["y"].rolling(window=window, center=True, min_periods=1).mean()
    return ordered["x"], smooth_y


def shorten_chart_label(label: str, max_length: int = 28) -> str:
    return label if len(label) <= max_length else f"{label[: max_length - 1]}..."


def render_distribution_result(result: dict[str, Any], compare_result: dict[str, Any] | None, *, density: bool = False) -> None:
    values = pd.DataFrame.from_records(result.get("values", [])).dropna(subset=["value"])
    if values.empty:
        st.warning("Sin valores para la distribución.")
        render_analysis_warnings(result.get("warnings", []))
        return
    values["Serie"] = analytics_result_label(result["variable"])
    frames = [values]
    if compare_result is not None:
        compare_values = pd.DataFrame.from_records(compare_result.get("values", [])).dropna(subset=["value"])
        compare_values["Serie"] = analytics_result_label(compare_result["variable"])
        frames.append(compare_values)
    plot_frame = pd.concat(frames, ignore_index=True)
    hist = px.histogram(
        plot_frame,
        x="value",
        color="Serie",
        barmode="overlay",
        opacity=0.62,
        histnorm="probability density" if density else None,
        labels={"value": analytics_result_label(result["variable"])},
    )
    hist.update_yaxes(title_text="Densidad" if density else "count")
    hist.update_layout(height=360)
    box = px.box(plot_frame, x="Serie", y="value", color="Serie", labels={"value": analytics_result_label(result["variable"])})
    box.update_layout(height=360, showlegend=False)
    hist_column, box_column = st.columns([0.62, 0.38])
    with hist_column:
        st.plotly_chart(hist, width="stretch")
    with box_column:
        st.plotly_chart(box, width="stretch")
    render_distribution_summary(result, compare_result)
    add_csv_download(plot_frame, "Descargar CSV", "argos_analisis_distribucion.csv", key="analysis_dist_csv")
    render_analysis_warnings(result.get("warnings", []))


def render_distribution_summary(result: dict[str, Any], compare_result: dict[str, Any] | None) -> None:
    rows = [distribution_summary_row(result)]
    if compare_result is not None:
        rows.append(distribution_summary_row(compare_result))
    st.dataframe(pd.DataFrame(rows), hide_index=True)


def render_trend_analysis_result(result: dict[str, Any]) -> None:
    points = pd.DataFrame.from_records(result.get("points", []))
    if points.empty:
        st.warning("Sin datos para la tendencia.")
        render_analysis_warnings(result.get("warnings", []))
        return
    label = analytics_result_label(result["variable"])
    plot_frame = points.melt(id_vars=["timestamp_local"], value_vars=["value", "reference", "anomaly"], var_name="Serie", value_name="Valor").dropna()
    plot_frame["Serie"] = plot_frame["Serie"].map({"value": label, "reference": "Referencia", "anomaly": "Anomalía"})
    figure = px.line(plot_frame, x="timestamp_local", y="Valor", color="Serie")
    for event in result.get("field_events", []):
        figure.add_vline(x=event["occurred_at_local"], line_dash="dot", line_color="#ef4444")
    figure.update_layout(height=390, xaxis_title=local_time_axis_title())
    st.plotly_chart(figure, width="stretch")
    with st.container(horizontal=True):
        st.metric("Observaciones", result.get("observations_count", 0), border=True)
        st.metric("Cobertura", format_percent(result.get("coverage")), border=True)
        st.metric("Pendiente", f"{format_number(result.get('slope_per_year'), '')} {result['variable'].get('unit', '')}/año", border=True)
        st.metric("Cambio total", format_number(result.get("total_change"), result["variable"].get("unit", "")), border=True)
        st.metric("Anomalía media", format_number(result.get("anomaly_mean"), result["variable"].get("unit", "")), border=True)
    add_csv_download(points, "Descargar CSV", "argos_analisis_tendencia.csv", key="analysis_trend_csv")
    if result.get("field_events"):
        with st.expander("Eventos del Diario de campo"):
            st.dataframe(pd.DataFrame.from_records(result["field_events"]), hide_index=True)
    render_analysis_warnings(result.get("warnings", []))


def render_analysis_warnings(warnings: list[str]) -> None:
    if warnings:
        with st.expander("Detalles del análisis"):
            for warning in warnings:
                st.warning(warning)


def default_analysis_filters() -> dict[str, Any]:
    today = datetime.now(ZoneInfo(get_settings().local_timezone)).date()
    return {
        "start": local_datetime_to_utc_iso(today - timedelta(days=30), time.min),
        "end": local_datetime_to_utc_iso(today, time.max.replace(microsecond=0)),
        "frequency": "daily",
        "zone_slug": None,
        "quality_status": None,
    }


def analysis_quick_dates(label: str, current: dict[str, Any]) -> tuple[date, date]:
    today = datetime.now(ZoneInfo(get_settings().local_timezone)).date()
    if label == "Últimos 7 días":
        return today - timedelta(days=7), today
    if label == "Últimos 30 días":
        return today - timedelta(days=30), today
    if label == "Últimos 90 días":
        return today - timedelta(days=90), today
    if label == "Año actual":
        return date(today.year, 1, 1), today
    if label == "Último año":
        return today - timedelta(days=365), today
    if label == "Todo el periodo":
        return today - timedelta(days=365), today
    start = parse_datetime(current.get("start"))
    end = parse_datetime(current.get("end"))
    return (start.date() if start else today - timedelta(days=30), end.date() if end else today)


def analytics_variable_label(variable_id: str, variables: list[dict[str, Any]]) -> str:
    variable = next((item for item in variables if item["variable_id"] == variable_id), None)
    if variable is None:
        return variable_id
    unit = f" [{variable['unit']}]" if variable.get("unit") else ""
    return f"{variable['source'].upper()} · {variable['label']}{unit}"


def analytics_result_label(variable: dict[str, Any]) -> str:
    unit = f" [{variable['unit']}]" if variable.get("unit") else ""
    return f"{variable['label']}{unit}"


def analytics_variable_aggregations(variable_id: str, variables: list[dict[str, Any]]) -> list[str]:
    variable = next((item for item in variables if item["variable_id"] == variable_id), None)
    return list(variable.get("valid_aggregations", ["mean"])) if variable else ["mean"]


def analytics_common_aggregations(variable_x: str, variable_y: str, variables: list[dict[str, Any]]) -> list[str]:
    common = [
        item
        for item in analytics_variable_aggregations(variable_x, variables)
        if item in analytics_variable_aggregations(variable_y, variables)
    ]
    return common or analytics_variable_aggregations(variable_x, variables)


def distribution_summary_row(result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("summary", {})
    return {
        "Variable": analytics_result_label(result["variable"]),
        "n": summary.get("count"),
        "Cobertura": format_percent(summary.get("coverage")),
        "Media": format_number(summary.get("mean"), result["variable"].get("unit", "")),
        "Mediana": format_number(summary.get("median"), result["variable"].get("unit", "")),
        "Min": format_number(summary.get("minimum"), result["variable"].get("unit", "")),
        "Max": format_number(summary.get("maximum"), result["variable"].get("unit", "")),
        "Std": format_number(summary.get("std"), result["variable"].get("unit", "")),
        "P5": format_number(summary.get("p05"), result["variable"].get("unit", "")),
        "P95": format_number(summary.get("p95"), result["variable"].get("unit", "")),
    }


def analysis_frequency_label(value: str) -> str:
    return {"original": "Dato original", "hourly": "Horaria", "daily": "Diaria", "weekly": "Semanal", "monthly": "Mensual"}.get(value, value)


def analysis_missing_label(value: str) -> str:
    return {"intersection": "Intersección temporal", "linear_interpolation": "Interpolación lineal"}.get(value, value)


def analysis_reference_label(value: str) -> str:
    return {
        "none": "Sin referencia",
        "period_mean": "Media del periodo",
        "period_median": "Mediana del periodo",
        "moving_average": "Media móvil",
        "linear_trend": "Tendencia lineal",
    }.get(value, value)


def render_plantation(client: ArgosApiClient) -> None:
    try:
        catalog = cached_plant_catalog(client.base_url)
        matrix = cached_plant_matrix(client.base_url, "tomillar")
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    status_labels = {item["slug"]: item["label"] for item in catalog.get("statuses", [])} or PLANT_STATUS_LABELS
    species_labels = {item["slug"]: item["label"] for item in catalog.get("species", [])} or PLANT_SPECIES_LABELS
    sectors = {item["slug"]: item["label"] for item in catalog.get("irrigation_sectors", [])}
    st.title("Plantación")

    selected_status, selected_species, selected_sector, search = render_plantation_filters(
        status_labels=status_labels,
        species_labels=species_labels,
        sectors=sectors,
    )
    try:
        plants = cached_plants(client.base_url, "tomillar", selected_status, selected_species, selected_sector, search)
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    selected_from_url = st.query_params.get("plant")
    if selected_from_url and "plantation_selected_public_code" not in st.session_state:
        matching = next((plant for plant in plants if plant.get("public_code") == selected_from_url), None)
        if matching:
            st.session_state["plantation_selected_plant_id"] = matching["id"]
            st.session_state["plantation_selected_public_code"] = matching["public_code"]

    summary_col, refresh_col = st.columns([1, 0.18], vertical_alignment="center")
    with summary_col:
        occupied = sum(1 for cell in matrix.get("cells", []) if cell.get("cell_type") == "plant")
        infrastructure = sum(1 for cell in matrix.get("cells", []) if cell.get("cell_type") == "infrastructure")
        st.caption(f"{len(plants)} árboles en el filtro. {occupied} celdas vegetales y {infrastructure} elementos no vegetales en la matriz.")
    with refresh_col:
        if st.button("Actualizar", icon=":material/refresh:", key="plantation_refresh", width="stretch"):
            cached_plant_matrix.clear()
            cached_plants.clear()
            cached_plant_history.clear()
            st.rerun()

    grid_col, detail_col = st.columns([6.8, 3.2], vertical_alignment="top")
    visible_ids = {int(plant["id"]) for plant in plants}
    selected_id = st.session_state.get("plantation_selected_plant_id")
    with grid_col:
        render_plantation_legend(status_labels)
        render_plantation_matrix(matrix, visible_plant_ids=visible_ids, selected_plant_id=selected_id)
    with detail_col:
        selected = selected_plant_from_matrix(matrix, selected_id)
        render_plant_detail(client, selected, status_labels=status_labels, species_labels=species_labels)


def render_plantation_filters(
    *,
    status_labels: dict[str, str],
    species_labels: dict[str, str],
    sectors: dict[str, str],
) -> tuple[str | None, str | None, str | None, str | None]:
    with st.container(border=True, gap="small"):
        status_col, species_col, sector_col, search_col = st.columns([1, 1.15, 0.9, 1.25])
        with status_col:
            status = st.selectbox(
                "Estado",
                options=["Todos", *status_labels],
                key="plantation_status",
                format_func=lambda value: "Todos" if value == "Todos" else status_labels.get(value, value),
            )
        with species_col:
            species = st.selectbox(
                "Especie",
                options=["Todas", *species_labels],
                key="plantation_species",
                format_func=lambda value: "Todas" if value == "Todas" else species_labels.get(value, value),
            )
        with sector_col:
            sector = st.selectbox(
                "Sector",
                options=["Todos", *sectors],
                key="plantation_sector",
                format_func=lambda value: "Todos" if value == "Todos" else sectors.get(value, value),
            )
        with search_col:
            search = st.text_input("Buscar código", key="plantation_search")
    return (
        None if status == "Todos" else status,
        None if species == "Todas" else species,
        None if sector == "Todos" else sector,
        search.strip().upper() or None,
    )


def render_plantation_legend(status_labels: dict[str, str]) -> None:
    labels = " ".join(f"<span>{escape(label)}</span>" for label in status_labels.values())
    st.html(f'<div class="argos-plantation-legend">{labels}<span>Vacía</span><span>Infraestructura</span><span># desplazado</span></div>')


def render_plantation_matrix(matrix: dict[str, Any], *, visible_plant_ids: set[int], selected_plant_id: int | None) -> None:
    cells_by_position = {(cell["row"], cell["column"]): cell for cell in matrix.get("cells", [])}
    column_labels = matrix.get("column_labels", [])
    header_cols = st.columns([0.34, *([1] * 12)], gap="small")
    header_cols[0].html("&nbsp;")
    for index, label in enumerate(column_labels[:12], start=1):
        header_cols[index].html(f'<div class="argos-plantation-label">{escape(label)}</div>')
    for row_index, row_label in enumerate(matrix.get("row_labels", [])[:12], start=1):
        row_cols = st.columns([0.34, *([1] * 12)], gap="small")
        row_cols[0].html(f'<div class="argos-plantation-label">{escape(row_label)}</div>')
        for column_index in range(1, 13):
            cell = cells_by_position.get((row_index, column_index), {})
            plant = cell.get("plant")
            label = plantation_cell_label(cell)
            disabled = plant is None or int(plant["id"]) not in visible_plant_ids
            button_type: Literal["primary", "secondary"] = "primary" if plant and plant.get("id") == selected_plant_id else "secondary"
            with row_cols[column_index]:
                if st.button(
                    label,
                    key=f"plant_cell_{row_index}_{column_index}",
                    disabled=disabled,
                    type=button_type,
                    width="stretch",
                ) and plant:
                    st.session_state["plantation_selected_plant_id"] = plant["id"]
                    st.session_state["plantation_selected_public_code"] = plant["public_code"]
                    st.query_params["plant"] = plant["public_code"]
                    st.rerun()


def plantation_cell_label(cell: dict[str, Any]) -> str:
    plant = cell.get("plant")
    if plant:
        public_code = plant.get("public_code") or cell.get("position_code", "")
        marker = cell.get("displacement_marker") or ""
        return str(public_code) if marker in str(public_code) else f"{public_code}{marker}"
    if cell.get("cell_type") == "infrastructure":
        return str(cell.get("visible_code") or cell.get("position_code") or "")
    return f"{cell.get('position_code', '')}\n-"


def selected_plant_from_matrix(matrix: dict[str, Any], selected_plant_id: int | None) -> dict[str, Any] | None:
    if selected_plant_id is None:
        return None
    for cell in matrix.get("cells", []):
        plant = cell.get("plant")
        if plant and plant.get("id") == selected_plant_id:
            return plant
    return None


def render_plant_detail(
    client: ArgosApiClient,
    plant: dict[str, Any] | None,
    *,
    status_labels: dict[str, str],
    species_labels: dict[str, str],
) -> None:
    if plant is None:
        st.info("Selecciona un árbol ocupado de la matriz para abrir su ficha.")
        return
    with st.container(border=True, gap="small"):
        st.subheader(f"Árbol {plant['public_code']}")
        st.caption(f"{plant['matrix_position_code']} · {plant.get('parcel_name') or plant.get('parcel_slug')}")
        ficha_tab, historial_tab = st.tabs(["Ficha", "Historial"])
        with ficha_tab:
            st.html(
                '<div class="argos-summary-grid">'
                f'{compact_metric_html("Especie", species_labels.get(plant["species"], plant["species"]))}'
                f'{compact_metric_html("Estado", status_labels.get(plant["status"], plant["status"]))}'
                f'{compact_metric_html("Sector", plant.get("irrigation_sector_id") or "Sin dato")}'
                f'{compact_metric_html("Línea", plant.get("irrigation_line_slug") or "Sin dato")}'
                "</div>"
            )
            if plant.get("variety") or plant.get("rootstock") or plant.get("planted_on"):
                st.write(
                    " · ".join(
                        value
                        for value in (
                            f"Variedad: {plant.get('variety')}" if plant.get("variety") else "",
                            f"Patrón: {plant.get('rootstock')}" if plant.get("rootstock") else "",
                            f"Plantación: {plant.get('planted_on')}" if plant.get("planted_on") else "",
                        )
                        if value
                    )
                )
            if plant.get("notes"):
                st.caption(plant["notes"])
            st.caption("Los riegos sectoriales son asociados por sector; no son mediciones individuales del árbol.")
            with st.popover("Nueva observación", icon=":material/add:"):
                render_plant_observation_form(client, plant)
        with historial_tab:
            render_plant_history(client, plant)


def render_plant_observation_form(client: ArgosApiClient, plant: dict[str, Any]) -> None:
    with st.form(f"plant_observation_{plant['id']}"):
        title = st.text_input("Título", value=f"Observación {plant['public_code']}")
        description = st.text_area("Descripción", height=90)
        uploaded_photo = st.file_uploader(
            "Foto desde móvil o archivo",
            type=["jpg", "jpeg", "png", "webp"],
            key=f"plant_observation_upload_{plant['id']}",
        )
        st.caption("En móvil, este botón permite elegir galería o cámara. La cámara integrada requiere HTTPS.")
        camera_photo = st.camera_input("Cámara integrada", key=f"plant_observation_camera_{plant['id']}")
        selected_photo = camera_photo or uploaded_photo
        if selected_photo is not None:
            st.success(f"Foto lista para registrar: {selected_photo.name} ({format_file_size(selected_photo.size)})")
        submitted = st.form_submit_button("Registrar", type="primary")
    if not submitted:
        return
    if not client.admin_token:
        st.error("Hace falta ARGOS admin token para crear eventos.")
        return
    payload = {
        "occurred_at": datetime.now(UTC).isoformat(),
        "event_type": "observation",
        "title": title.strip(),
        "description": description.strip() or None,
        "zone_slug": None,
        "tree_reference": plant["public_code"],
        "target_type": "plant",
        "target_value": plant["public_code"],
        "plant_unit_ids": [plant["id"]],
        "source": "manual",
    }
    photo_payload = uploaded_photo_payload(selected_photo)
    if photo_payload is not None:
        payload["photo"] = photo_payload
    try:
        client.create_field_event(payload)
        cached_field_events.clear()
        cached_plant_history.clear()
        st.rerun()
    except ArgosApiError as exc:
        st.error(str(exc))


def render_plant_history(client: ArgosApiClient, plant: dict[str, Any]) -> None:
    try:
        history = cached_plant_history(client.base_url, int(plant["id"]))
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    if not history:
        st.caption("Sin eventos asociados.")
        return
    for event in history[:12]:
        st.write(f"{format_compact_local_datetime(event.get('occurred_at'))} · {event.get('title')}")
        if event.get("description"):
            st.caption(event["description"])
        if event.get("photo_url"):
            st.image(f"{client.base_url.rstrip('/')}{event['photo_url']}", width=220)


def uploaded_photo_payload(uploaded_file: Any | None) -> dict[str, Any] | None:
    if uploaded_file is None:
        return None
    content = uploaded_file.getvalue()
    return {
        "filename": uploaded_file.name,
        "content_type": uploaded_file.type or "application/octet-stream",
        "data_base64": base64.b64encode(content).decode("ascii"),
    }


def format_file_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "tamaño desconocido"
    if size_bytes < 1024 * 1024:
        return f"{max(size_bytes / 1024, 0.1):.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def render_field_diary(client: ArgosApiClient) -> None:
    catalog = cached_field_event_catalog(client.base_url)
    event_type_labels = {item["slug"]: item["label"] for item in catalog.get("event_types", [])} or FIELD_EVENT_TYPE_LABELS
    zone_labels = {item["slug"]: item["label"] for item in catalog.get("zones", [])} or FIELD_ZONE_LABELS

    left, right = st.columns([1, 0.22], vertical_alignment="center")
    with left:
        st.title("Diario de campo")
    with right:
        with st.popover("Registrar evento", icon=":material/add:"):
            render_field_event_form(
                client,
                event_type_labels=event_type_labels,
                zone_labels=zone_labels,
                mode="create",
                event=None,
            )

    start_iso, end_iso, selected_type, selected_zone, search = render_field_event_filters(
        event_type_labels=event_type_labels,
        zone_labels=zone_labels,
    )
    try:
        rows = cached_field_events(client.base_url, start_iso, end_iso, selected_type, selected_zone, search)
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    count_col, export_col = st.columns([1, 0.18], vertical_alignment="center")
    with count_col:
        st.caption(f"{len(rows)} eventos en el filtro activo.")
    with export_col:
        if rows:
            st.download_button(
                "Exportar CSV",
                data=field_events_csv(rows, event_type_labels=event_type_labels, zone_labels=zone_labels),
                file_name="argos_diario_campo.csv",
                mime="text/csv",
                icon=":material/download:",
                key="field_events_export_csv",
                width="stretch",
            )

    render_field_event_delete_confirmation(client)
    edit_id = st.session_state.get("field_event_edit_id")
    if edit_id is not None:
        event = next((row for row in rows if row.get("id") == edit_id), None)
        if event is not None:
            with st.container(border=True, gap="small"):
                st.subheader("Editar evento")
                render_field_event_form(
                    client,
                    event_type_labels=event_type_labels,
                    zone_labels=zone_labels,
                    mode="edit",
                    event=event,
                )

    render_field_event_table(rows, event_type_labels=event_type_labels, zone_labels=zone_labels)


def render_field_event_filters(
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
) -> tuple[str, str, str | None, str | None, str | None]:
    today = datetime.now(ZoneInfo(get_settings().local_timezone)).date()
    st.session_state.setdefault("field_events_start_date", today - timedelta(days=90))
    st.session_state.setdefault("field_events_end_date", today)
    st.session_state.setdefault("field_events_type", "Todos")
    st.session_state.setdefault("field_events_zone", "Todas")
    st.session_state.setdefault("field_events_search", "")

    with st.container(border=True, gap="small"):
        date_col, type_col, zone_col, search_col, reset_col = st.columns([1, 1.05, 1.05, 1.25, 0.55])
        with date_col:
            start_date = st.date_input("Desde", key="field_events_start_date")
            end_date = st.date_input("Hasta", key="field_events_end_date")
        with type_col:
            type_options = ["Todos", *event_type_labels]
            event_type = st.selectbox(
                "Tipo",
                options=type_options,
                key="field_events_type",
                format_func=lambda value: "Todos" if value == "Todos" else event_type_labels.get(value, value),
            )
        with zone_col:
            zone_options = ["Todas", *zone_labels]
            zone = st.selectbox(
                "Zona",
                options=zone_options,
                key="field_events_zone",
                format_func=lambda value: "Todas" if value == "Todas" else zone_labels.get(value, value),
            )
        with search_col:
            search = st.text_input("Buscar", key="field_events_search")
        with reset_col:
            st.write("")
            st.write("")
            if st.button("Limpiar", icon=":material/close:", key="field_events_clear_filters"):
                st.session_state["field_events_start_date"] = today - timedelta(days=90)
                st.session_state["field_events_end_date"] = today
                st.session_state["field_events_type"] = "Todos"
                st.session_state["field_events_zone"] = "Todas"
                st.session_state["field_events_search"] = ""
                st.rerun()

    return (
        field_event_start_iso(start_date),
        field_event_end_iso(end_date),
        None if event_type == "Todos" else event_type,
        None if zone == "Todas" else zone,
        search.strip() or None,
    )


def render_field_event_table(
    rows: list[dict[str, Any]],
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
) -> None:
    if not rows:
        st.info("Sin eventos para los filtros activos.")
        return

    st.html(
        """
        <div class="argos-field-event-table">
            <div class="argos-field-event-row header">
                <span>Fecha y hora</span><span>Tipo</span><span>Título</span><span>Zona</span>
                <span>Árbol/fila</span><span>Cantidad</span><span>Descripción</span>
            </div>
        </div>
        """
    )
    for row in rows:
        content_col, action_col = st.columns([10, 1.2], vertical_alignment="center")
        with content_col:
            st.html(field_event_row_html(row, event_type_labels=event_type_labels, zone_labels=zone_labels))
        with action_col:
            if st.button("Editar", key=f"field_event_edit_{row['id']}", icon=":material/edit:", width="stretch"):
                st.session_state["field_event_edit_id"] = row["id"]
                st.rerun()
            if st.button("Eliminar", key=f"field_event_delete_{row['id']}", icon=":material/delete:", width="stretch"):
                st.session_state["field_event_delete_id"] = row["id"]
                st.rerun()


def render_field_event_form(
    client: ArgosApiClient,
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
    mode: str,
    event: dict[str, Any] | None,
) -> None:
    prefix = f"field_event_{mode}_{event.get('id') if event else 'new'}"
    occurred_at = parse_datetime(event.get("occurred_at")) if event else datetime.now(UTC)
    local_occurred = (occurred_at or datetime.now(UTC)).astimezone(ZoneInfo(get_settings().local_timezone))
    type_options = list(event_type_labels)
    zone_options = ["", *zone_labels]
    with st.form(prefix):
        date_col, time_col, type_col = st.columns([1, 0.8, 1.2])
        with date_col:
            event_date = st.date_input("Fecha", value=local_occurred.date(), key=f"{prefix}_date")
        with time_col:
            event_time = st.time_input("Hora", value=local_occurred.time().replace(microsecond=0), key=f"{prefix}_time")
        with type_col:
            event_type = st.selectbox(
                "Tipo",
                options=type_options,
                index=max(0, type_options.index(event.get("event_type"))) if event and event.get("event_type") in type_options else 0,
                format_func=lambda value: event_type_labels.get(value, value),
                key=f"{prefix}_type",
            )
        title = st.text_input("Título", value=event.get("title", "") if event else "", key=f"{prefix}_title")
        description = st.text_area(
            "Descripción",
            value=event.get("description") or "" if event else "",
            height=90,
            key=f"{prefix}_description",
        )
        zone_col, tree_col, quantity_col, unit_col = st.columns([1.1, 1.1, 0.8, 0.8])
        with zone_col:
            zone_slug = st.selectbox(
                "Zona",
                options=zone_options,
                index=zone_options.index(event.get("zone_slug")) if event and event.get("zone_slug") in zone_options else 0,
                format_func=lambda value: "—" if not value else zone_labels.get(value, value),
                key=f"{prefix}_zone",
            )
        with tree_col:
            tree_reference = st.text_input("Árbol/fila", value=event.get("tree_reference") or "" if event else "", key=f"{prefix}_tree")
        with quantity_col:
            quantity_text = st.text_input(
                "Cantidad",
                value=format_field_event_quantity(event.get("quantity")) if event else "",
                key=f"{prefix}_quantity",
            )
        with unit_col:
            unit = st.text_input("Unidad", value=event.get("unit") or "" if event else "", key=f"{prefix}_unit")
        submitted = st.form_submit_button(
            "Guardar" if mode == "edit" else "Registrar",
            type="primary",
            disabled=not bool(client.admin_token),
        )
    if not client.admin_token:
        st.caption("Hace falta ARGOS admin token para crear o modificar eventos.")
    if not submitted:
        return
    try:
        payload = field_event_form_payload(
            event_date=event_date,
            event_time=event_time,
            event_type=event_type,
            title=title,
            description=description,
            zone_slug=zone_slug,
            tree_reference=tree_reference,
            quantity_text=quantity_text,
            unit=unit,
        )
        if mode == "edit" and event is not None:
            client.update_field_event(int(event["id"]), payload)
            st.session_state.pop("field_event_edit_id", None)
        else:
            client.create_field_event(payload)
        cached_field_events.clear()
        st.rerun()
    except (ArgosApiError, ValueError) as exc:
        st.error(str(exc))


def render_field_event_delete_confirmation(client: ArgosApiClient) -> None:
    event_id = st.session_state.get("field_event_delete_id")
    if event_id is None:
        return
    with st.container(border=True, gap="small"):
        st.warning(f"¿Eliminar el evento {event_id}? Esta acción no se puede deshacer.")
        yes_col, no_col = st.columns([0.2, 0.2])
        with yes_col:
            if st.button("Eliminar", type="primary", key="field_event_confirm_delete", disabled=not bool(client.admin_token)):
                try:
                    client.delete_field_event(int(event_id))
                    st.session_state.pop("field_event_delete_id", None)
                    cached_field_events.clear()
                    st.rerun()
                except ArgosApiError as exc:
                    st.error(str(exc))
        with no_col:
            if st.button("Cancelar", key="field_event_cancel_delete"):
                st.session_state.pop("field_event_delete_id", None)
                st.rerun()


def field_event_form_payload(
    *,
    event_date: date,
    event_time: time,
    event_type: str,
    title: str,
    description: str,
    zone_slug: str,
    tree_reference: str,
    quantity_text: str,
    unit: str,
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("El título es obligatorio.")
    quantity = parse_optional_float(quantity_text)
    unit = unit.strip()
    if unit and quantity is None:
        raise ValueError("La unidad requiere una cantidad.")
    return {
        "occurred_at": local_datetime_to_utc_iso(event_date, event_time),
        "event_type": event_type,
        "title": title.strip(),
        "description": description.strip() or None,
        "zone_slug": zone_slug or None,
        "tree_reference": tree_reference.strip() or None,
        "quantity": quantity,
        "unit": unit or None,
        "source": "manual",
    }


def field_event_row_html(
    row: dict[str, Any],
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
) -> str:
    quantity = field_event_quantity_label(row.get("quantity"), row.get("unit"))
    values = [
        format_compact_local_datetime(row.get("occurred_at")),
        event_type_labels.get(str(row.get("event_type")), str(row.get("event_type"))),
        row.get("title") or "—",
        zone_labels.get(str(row.get("zone_slug")), str(row.get("zone_slug"))) if row.get("zone_slug") else "—",
        row.get("tree_reference") or "—",
        quantity,
        row.get("description") or "—",
    ]
    cells = "".join(f"<span>{escape(str(value))}</span>" for value in values)
    return f'<div class="argos-field-event-row">{cells}</div>'


def field_events_csv(
    rows: list[dict[str, Any]],
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["Fecha y hora", "Tipo", "Título", "Zona", "Árbol/fila", "Cantidad", "Descripción", "Origen"],
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "Fecha y hora": format_compact_local_datetime(row.get("occurred_at")),
                "Tipo": event_type_labels.get(str(row.get("event_type")), str(row.get("event_type"))),
                "Título": row.get("title") or "",
                "Zona": zone_labels.get(str(row.get("zone_slug")), str(row.get("zone_slug"))) if row.get("zone_slug") else "",
                "Árbol/fila": row.get("tree_reference") or "",
                "Cantidad": field_event_quantity_label(row.get("quantity"), row.get("unit"), empty=""),
                "Descripción": row.get("description") or "",
                "Origen": row.get("source") or "",
            }
        )
    return output.getvalue().encode("utf-8-sig")


def field_event_quantity_label(quantity: Any, unit: Any, *, empty: str = "—") -> str:
    if quantity is None:
        return empty
    suffix = f" {unit}" if unit else ""
    return f"{float(quantity):g}{suffix}"


def format_field_event_quantity(quantity: Any) -> str:
    return "" if quantity is None else f"{float(quantity):g}"


def parse_optional_float(value: str) -> float | None:
    text = value.strip().replace(",", ".")
    if not text:
        return None
    return float(text)


def field_event_start_iso(value: date) -> str:
    return local_datetime_to_utc_iso(value, time.min)


def field_event_end_iso(value: date) -> str:
    return local_datetime_to_utc_iso(value, time.max.replace(microsecond=0))


def local_datetime_to_utc_iso(day: date, clock_time: time) -> str:
    timezone = ZoneInfo(get_settings().local_timezone)
    return format_utc_iso(datetime.combine(day, clock_time).replace(tzinfo=timezone))


def render_data_update(client: ArgosApiClient) -> None:
    st.subheader("Actualizar datos")
    st.caption("La actualización reciente se ejecuta automáticamente a diario. Use esta pestaña para rellenar históricos.")
    settings = get_settings()
    ecowitt_tab, aemet_tab, satellite_tab = st.tabs(["Ecowitt", "AEMET", "Satélite"])

    with ecowitt_tab:
        default_end = datetime.now(UTC).date()
        default_start = default_end - timedelta(days=1)
        with st.container(border=True):
            st.subheader("Ecowitt Cloud")
            with st.container(horizontal=True, vertical_alignment="bottom"):
                start_date = st.date_input("Inicio", value=default_start, key="ecowitt_backfill_start")
                end_date = st.date_input("Fin", value=default_end, key="ecowitt_backfill_end")
            gateway_identifier = default_ecowitt_gateway_identifier()
            render_configured_gateway_identifier(gateway_identifier)
            if st.button("Descargar histórico Ecowitt", icon=":material/download:", type="primary"):
                run_ecowitt_backfill_from_dashboard(
                    client=client,
                    gateway_identifier=gateway_identifier,
                    start=datetime.combine(start_date, time.min, tzinfo=UTC),
                    end=datetime.combine(end_date, time.max, tzinfo=UTC),
                )

    with aemet_tab:
        with st.container(border=True):
            st.subheader("AEMET")
            station_id = st.text_input("Indicativo", value=settings.aemet_station_id, max_chars=16, key="aemet_update_station")
            with st.container(horizontal=True, vertical_alignment="bottom"):
                lookback_days = st.number_input(
                    "Días a refrescar",
                    min_value=1,
                    max_value=366,
                    value=settings.aemet_sync_lookback_days,
                    step=1,
                    key="aemet_update_lookback",
                )
                if st.button("Actualizar reciente", icon=":material/sync:", type="secondary", key="aemet_update_recent"):
                    run_aemet_sync_from_dashboard(station_id=station_id, lookback_days=int(lookback_days))

            csv_path = st.text_input("CSV histórico local", value=settings.aemet_seed_csv_path or "", key="aemet_update_csv")
            if st.button("Importar CSV histórico", icon=":material/upload_file:", type="secondary", key="aemet_update_csv_button"):
                run_aemet_csv_import_from_dashboard(station_id=station_id, path=csv_path)

            with st.container(horizontal=True, vertical_alignment="bottom"):
                history_start = st.date_input("Inicio histórico", value=settings.aemet_backfill_start_date, key="aemet_update_start")
                history_end = st.date_input("Fin histórico", value=date.today(), key="aemet_update_end")
                block_days = st.number_input(
                    "Días por bloque",
                    min_value=1,
                    max_value=366,
                    value=settings.aemet_block_days,
                    step=1,
                    key="aemet_update_block",
                )
            if st.button("Descargar histórico AEMET", icon=":material/download:", type="primary", key="aemet_update_backfill"):
                run_aemet_backfill_from_dashboard(
                    station_id=station_id,
                    start=history_start.isoformat(),
                    end=history_end.isoformat(),
                    block_days=int(block_days),
                )

    with satellite_tab:
        with st.container(border=True):
            st.subheader("Satélite")
            try:
                satellite_status = cached_satellite_status(client.base_url)
                satellite_zones = cached_satellite_zones(client.base_url)
                satellite_aoi_choices = satellite_aoi_options(status=satellite_status, zones=satellite_zones)
            except ArgosApiError:
                satellite_aoi_choices = []
            selected_satellite_aoi = st.selectbox(
                "AOI",
                options=[None, *[option["slug"] for option in satellite_aoi_choices]],
                format_func=lambda slug: "Todos los AOI"
                if slug is None
                else next(option["name"] for option in satellite_aoi_choices if option["slug"] == slug),
                key="satellite_update_aoi",
            )
            force = st.checkbox("Reprocesar existentes", value=False, key="satellite_update_force")
            dry_run = st.checkbox("Dry-run", value=False, key="satellite_update_dry_run")
            if st.button("Actualizar reciente", icon=":material/sync:", type="secondary", key="satellite_update_recent"):
                run_satellite_update_from_dashboard(client=client, aoi_slug=selected_satellite_aoi, force=force, dry_run=dry_run)
            with st.container(horizontal=True, vertical_alignment="bottom"):
                start_date = st.date_input("Inicio histórico", value=date.today() - timedelta(days=730), key="satellite_update_start")
                end_date = st.date_input("Fin histórico", value=date.today(), key="satellite_update_end")
            if st.button("Descargar histórico satelital", icon=":material/download:", type="primary", key="satellite_update_backfill"):
                run_satellite_backfill_from_dashboard(
                    client=client,
                    aoi_slug=selected_satellite_aoi,
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                    force=force,
                    dry_run=dry_run,
                )


def default_ecowitt_gateway_identifier() -> str:
    settings = get_settings()
    if settings.ecowitt_cloud_mac:
        return format_cloud_mac(settings.ecowitt_cloud_mac)
    with get_sessionmaker()() as session:
        gateway = WeatherRepository(session).latest_gateway()
        if gateway is not None:
            return gateway.mac_address
    return ""


def render_configured_gateway_identifier(gateway_identifier: str) -> None:
    if gateway_identifier:
        st.caption(f"Gateway configurado: `{mask_identifier(gateway_identifier)}`")
    else:
        st.warning("No hay ECOWITT_CLOUD_MAC configurada en el .env.")


def mask_identifier(value: str) -> str:
    if len(value) <= 6:
        return value
    return f"{value[:2]}...{value[-4:]}"


def run_ecowitt_backfill_from_dashboard(
    *,
    client: ArgosApiClient,
    gateway_identifier: str,
    start: datetime,
    end: datetime,
) -> None:
    if not gateway_identifier:
        st.error("Indique el gateway para asociar los datos de Ecowitt Cloud.")
        return
    try:
        with st.spinner("Descargando histórico Ecowitt Cloud..."):
            settings = get_settings()
            api_client = ArgosApiClient(
                base_url=client.base_url,
                admin_token=client.admin_token,
                timeout_seconds=600,
            )
            imported = 0
            duplicates = 0
            warnings = 0
            chunk_start = start
            while chunk_start < end:
                chunk_end = min(chunk_start + timedelta(hours=settings.ecowitt_cloud_max_backfill_hours), end)
                result = api_client.backfill_ecowitt_cloud(
                    gateway_identifier=gateway_identifier,
                    start=format_utc_iso(chunk_start),
                    end=format_utc_iso(chunk_end),
                )
                imported += int(result.get("imported_count", 0))
                duplicates += int(result.get("duplicate_count", 0))
                warnings += int(result.get("warning_count", 0))
                chunk_start = chunk_end
    except (ArgosApiError, RuntimeError, ValueError) as exc:
        st.error(str(exc))
        return
    st.cache_data.clear()
    st.success(f"Ecowitt Cloud: {imported} importadas, {duplicates} duplicadas, {warnings} avisos.")


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
    selected_aoi_value = "__all__"
    with st.container(key="satellite_controls", horizontal=True, vertical_alignment="bottom"):
        if aoi_options:
            aoi_select_options = ["__all__", *[option["slug"] for option in aoi_options]]
            selected_aoi_slug = st.selectbox(
                "AOI",
                options=aoi_select_options,
                format_func=lambda slug: "Todas"
                if slug == "__all__"
                else next(option["name"] for option in aoi_options if option["slug"] == slug),
                key="satellite_aoi_filter",
                width=230,
            )
            selected_aoi_value = selected_aoi_slug
        selected_metrics = st.multiselect(
            "Índices satelitales",
            options=metrics,
            default=metrics,
            format_func=lambda value: SATELLITE_LABELS.get(value, value.upper()),
        )
        quality_filter = st.selectbox(
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


def render_valves(
    client: ArgosNodeClient,
    *,
    start_iso: str,
    end_iso: str,
    valve_opening_duration_s: float,
    valve_closing_duration_s: float,
) -> None:
    try:
        valve_controls = irrigation_valve_controls()
    except ArgosIrrigationConfigError as exc:
        st.error(str(exc), icon=":material/error:")
        return

    with st.container(key="argos_irrigation_page"):
        header_left, header_close, header_refresh = st.columns([7.4, 1.25, 1.25], vertical_alignment="center")
        with header_left:
            st.html(
                """
                <div class="argos-irrigation-header">
                    <h1>Irrigación</h1>
                    <span>Control y monitoreo en tiempo real</span>
                </div>
                """
            )
        with header_close:
            if st.button("Cerrar todo", icon=":material/close:", type="primary", key="close_all_valves", width="stretch"):
                run_close_all_valves(client)
        with header_refresh:
            if st.button("Actualizar", icon=":material/refresh:", key="refresh_irrigation", width="stretch"):
                st.cache_data.clear()
                st.rerun()
            st.caption(f"Actualizado {datetime.now():%H:%M:%S}")

        render_close_all_valves_result(st.session_state.get("close_all_valves_result"))

        primary_left, primary_right = st.columns([7.2, 2.8], vertical_alignment="top")
        with primary_left:
            valve_keys = render_irrigation_valve_grid(
                client,
                valve_controls=valve_controls,
                valve_opening_duration_s=valve_opening_duration_s,
                valve_closing_duration_s=valve_closing_duration_s,
            )
        with primary_right:
            render_live_flowmeter_status(client, show_admin_actions=False)

        render_irrigation_history_section(
            client.base_url,
            start_iso=start_iso,
            end_iso=end_iso,
            valve_keys=valve_keys,
            valve_controls=valve_controls,
        )

        render_recent_irrigation_events(valve_keys, valve_controls=valve_controls)

        with st.expander("Detalle técnico", expanded=False):
            st.dataframe(
                valve_technical_frame(valve_controls),
                hide_index=True,
                column_config={
                    "Nombre": st.column_config.TextColumn("Nombre"),
                    "EV": st.column_config.TextColumn("EV"),
                    "Relay": st.column_config.NumberColumn("Relay", format="%d"),
                    "Control": st.column_config.TextColumn("Control"),
                },
            )
            selected_valve = st.selectbox(
                "Electroválvula",
                options=valve_controls,
                format_func=valve_control_label,
                key="selected_valve_control",
                help="Selector auxiliar para inspeccionar la última respuesta cruda del nodo.",
            )
            render_raw_valve_response(valve_keys[selected_valve.control_key])
            render_flowmeter_admin_actions(client)


@st.fragment(run_every=FLOWMETER_HISTORY_REFRESH_SECONDS)
def render_irrigation_history_section(
    node_url: str,
    *,
    start_iso: str,
    end_iso: str,
    valve_keys: dict[str, dict[str, str]],
    valve_controls: tuple[ValveControl, ...],
) -> None:
    chart_start_iso, chart_end_iso = flowmeter_chart_window(start_iso, end_iso)
    flowmeter_rows = cached_flowmeter_minutes(node_url, chart_start_iso, chart_end_iso)
    flowmeter_frame = dataframe_from_records(flowmeter_rows, "window_start_utc")
    sector_totals_l = cached_irrigation_sector_totals(node_url, chart_start_iso, chart_end_iso)

    secondary_left, secondary_right = st.columns([7.2, 2.8], vertical_alignment="top")
    with secondary_left:
        render_irrigation_water_card(flowmeter_frame, start_iso=chart_start_iso, end_iso=chart_end_iso)
    with secondary_right:
        render_irrigation_summary_card(
            flowmeter_frame,
            valve_keys,
            valve_controls=valve_controls,
            sector_totals_l=sector_totals_l,
        )
    warning = irrigation_history_capture_warning(flowmeter_frame, valve_keys, valve_controls=valve_controls)
    if warning is not None:
        st.warning(warning, icon=":material/warning:")


def render_irrigation_valve_grid(
    client: ArgosNodeClient,
    *,
    valve_controls: tuple[ValveControl, ...],
    valve_opening_duration_s: float,
    valve_closing_duration_s: float,
) -> dict[str, dict[str, str]]:
    st.html(section_header_html("Electroválvulas"))
    keys_by_valve: dict[str, dict[str, str]] = {}
    rows = (valve_controls[:3], valve_controls[3:])
    for row_index, row_valves in enumerate(rows):
        columns = st.columns(3, gap="small", vertical_alignment="top")
        for column, valve in zip(columns, row_valves):
            with column:
                keys_by_valve[valve.control_key] = render_valve_control_card(
                    client,
                    valve=valve,
                    valve_opening_duration_s=valve_opening_duration_s,
                    valve_closing_duration_s=valve_closing_duration_s,
                )
        if row_index == 1 and len(row_valves) < 3:
            with columns[-1]:
                st.html('<div class="argos-valve-empty" aria-hidden="true"></div>')
    for valve in valve_controls:
        if valve.control_key not in keys_by_valve:
            keys_by_valve[valve.control_key] = render_valve_control_card(
                client,
                valve=valve,
                valve_opening_duration_s=valve_opening_duration_s,
                valve_closing_duration_s=valve_closing_duration_s,
            )
    st.caption("Estado de posición estimado por ARGOS cuando no existe señal independiente de fin de carrera.")
    return keys_by_valve


def render_valve_control_card(
    client: ArgosNodeClient,
    *,
    valve: ValveControl,
    valve_opening_duration_s: float,
    valve_closing_duration_s: float,
) -> dict[str, str]:
    keys = valve_session_keys(valve.control_key)
    initialize_valve_session(keys)
    update_timed_valve_state(keys)

    phase = "not_operational" if not valve.enabled_for_control else st.session_state[keys["phase"]]
    if valve.enabled_for_control and phase in {"unknown", "closed", "open"}:
        refresh_valve_from_backend(client, valve=valve, keys=keys)
        phase = st.session_state[keys["phase"]]

    with st.container(border=True, gap="small", key=f"argos_valve_card_{valve.control_key}"):
        state_label = valve_card_state_label(phase)
        st.html(
            f"""
            <div class="argos-valve-card-inner">
                <h3>{escape(valve.functional_name)}</h3>
                <strong>{escape(state_label)}</strong>
            </div>
            """
        )
        with st.container(horizontal=True, gap="small", key=f"argos_valve_actions_{valve.control_key}"):
            open_disabled = (not valve.enabled_for_control) or phase_is_busy(phase) or phase == "open"
            if st.button(
                "Abrir",
                key=f"{valve.control_key}_open",
                disabled=open_disabled,
                width="stretch",
            ):
                start_valve_command(keys, "sending_open_command", "dashboard_open_click")

            close_disabled = (not valve.enabled_for_control) or phase_is_busy(phase) or phase == "closed"
            if st.button(
                "Cerrar",
                key=f"{valve.control_key}_close",
                type="primary",
                disabled=close_disabled,
                width="stretch",
            ):
                start_valve_command(keys, "sending_close_command", "dashboard_close_click")

        if valve.enabled_for_control and phase not in {"open", "closed"}:
            render_valve_status_line(keys, phase)
        render_valve_progress(keys, phase, valve_opening_duration_s, valve_closing_duration_s)
        if valve.enabled_for_control:
            render_valve_message(st.session_state[keys["message"]], st.session_state[keys["error"]])

    if (
        valve.enabled_for_control
        and phase in {"sending_open_command", "sending_close_command"}
        and not st.session_state[keys["command_in_flight"]]
    ):
        run_valve_command(
            client,
            valve=valve,
            keys=keys,
            command="open" if phase == "sending_open_command" else "close",
            movement_duration_s=valve_opening_duration_s if phase == "sending_open_command" else valve_closing_duration_s,
        )

    if valve.enabled_for_control and st.session_state[keys["phase"]] in {"opening", "closing"}:
        monotonic_time.sleep(1)
        st.rerun()

    return keys


def render_recent_irrigation_events(
    keys_by_valve: dict[str, dict[str, str]],
    *,
    valve_controls: tuple[ValveControl, ...],
) -> None:
    rows: list[str] = []
    for valve in valve_controls:
        keys = keys_by_valve[valve.control_key]
        timing = st.session_state.get(keys["timing"], {})
        response_at = timing.get("response_received_at") if isinstance(timing, dict) else None
        if not valve.enabled_for_control:
            event = "Puesta en servicio"
            message = "Pendiente de puesta en servicio"
        elif st.session_state.get(keys["error"]):
            event = "Error"
            message = "Error de comunicación"
        else:
            event = "Sesión"
            message = st.session_state.get(keys["message"]) or "Sin evento de sesión"
        rows.append(
            '<div class="argos-session-log-row">'
            f"<span>{escape(format_compact_local_datetime(response_at) if response_at else '-')}</span>"
            f"<span>{escape(valve.functional_name)}</span>"
            f"<span>{escape(event)}</span>"
            f"<span>{escape(str(message))}</span>"
            "</div>"
        )
    st.html(
        f"""
        {section_header_html("Eventos recientes")}
        <div class="argos-session-log">
            <div class="argos-session-log-row header">
                <span>Fecha/hora</span>
                <span>Elemento</span>
                <span>Evento</span>
                <span>Detalle</span>
            </div>
            {''.join(rows)}
        </div>
        """
    )


def render_flowmeter_chart_card(
    title: str,
    frame: pd.DataFrame,
    *,
    start_iso: str,
    end_iso: str,
) -> None:
    with st.container(border=True, gap="small"):
        st.html(section_header_html(title))
        if frame.empty:
            st.caption("Sin agregados minutales para el rango seleccionado.")
            return
        chart_frame = flowmeter_chart_frame(frame)
        if chart_frame.empty:
            st.caption("No hay valores de caudal para graficar.")
            return
        st.plotly_chart(build_flowmeter_figure(chart_frame, start_iso=start_iso, end_iso=end_iso), width="stretch")


def render_irrigation_water_card(frame: pd.DataFrame, *, start_iso: str, end_iso: str) -> None:
    with st.container(border=True, gap="small"):
        st.html(section_header_html("Agua y caudal", "eje temporal compartido"))
        if frame.empty:
            st.caption("Sin agregados minutales para el rango seleccionado.")
            return
        figure = build_irrigation_water_figure(frame, start_iso=start_iso, end_iso=end_iso)
        if figure is None:
            st.caption("No hay valores de caudal o acumulado para graficar.")
            return
        st.plotly_chart(figure, width="stretch")


def render_accumulated_water_card(frame: pd.DataFrame, *, start_iso: str, end_iso: str) -> None:
    with st.container(border=True, gap="small"):
        st.html(section_header_html("Acumulado de agua"))
        if frame.empty:
            st.caption("Sin acumulados para el rango seleccionado.")
            return
        figure = build_accumulated_water_figure(frame, start_iso=start_iso, end_iso=end_iso)
        if figure is None:
            st.caption("No hay valores acumulados para graficar.")
            return
        st.plotly_chart(figure, width="stretch")


def render_irrigation_summary_card(
    frame: pd.DataFrame,
    keys_by_valve: dict[str, dict[str, str]],
    *,
    valve_controls: tuple[ValveControl, ...],
    sector_totals_l: dict[str, float] | None = None,
) -> None:
    operational_valves = tuple(valve for valve in valve_controls if valve.irrigation and valve.enabled_for_control)
    operational_keys = tuple(keys_by_valve[valve.control_key] for valve in operational_valves)
    open_count = sum(1 for keys in operational_keys if st.session_state.get(keys["phase"]) == "open")
    active_count = sum(
        1
        for keys in operational_keys
        if st.session_state.get(keys["phase"]) in {"open", "opening", "sending_open_command"}
    )
    error_count = sum(1 for keys in operational_keys if st.session_state.get(keys["phase"]) == "error")
    unknown_count = sum(1 for keys in operational_keys if st.session_state.get(keys["phase"]) == "unknown")
    latest = frame.sort_values("window_start_utc").iloc[-1] if not frame.empty and "window_start_utc" in frame else None
    current_flow = format_number(latest.get("avg_flow_l_min") if latest is not None else None, "L/min")
    session_l = format_number(latest.get("session_l_end") if latest is not None else None, "L")
    st.html(
        irrigation_summary_html(
            open_count,
            active_count,
            error_count,
            unknown_count,
            operational_count=len(operational_valves),
            current_flow=current_flow,
            session_l=session_l,
            sector_totals_l=sector_totals_l,
        )
    )


def irrigation_history_capture_warning(
    frame: pd.DataFrame,
    keys_by_valve: dict[str, dict[str, str]],
    *,
    valve_controls: tuple[ValveControl, ...] | None = None,
    now_utc: datetime | None = None,
) -> str | None:
    valve_controls = valve_controls or irrigation_valve_controls()
    active_phases = {"open", "opening", "sending_open_command"}
    active_valves = tuple(
        valve
        for valve in valve_controls
        if valve.irrigation
        and valve.enabled_for_control
        and valve.control_key in keys_by_valve
        and st.session_state.get(keys_by_valve[valve.control_key]["phase"]) in active_phases
    )
    if not active_valves:
        return None

    if frame.empty or "window_start_utc" not in frame:
        return (
            "Hay riego activo, pero ARGOS no tiene agregados minutales recientes del caudalimetro. "
            "Compruebe que el capturador esta arrancado; si no lo esta, la sesion podra guardar el volumen final, "
            "pero la grafica historica quedara incompleta."
        )

    timestamps = pd.to_datetime(frame["window_start_utc"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return (
            "Hay riego activo, pero ARGOS no puede validar la fecha de los agregados del caudalimetro. "
            "Revise el capturador; si no esta registrando datos, la sesion podra guardar el volumen final, "
            "pero la grafica historica quedara incompleta."
        )

    now = now_utc or datetime.now(UTC)
    latest_age = now - timestamps.max().to_pydatetime()
    if latest_age > timedelta(minutes=FLOWMETER_CAPTURE_STALE_AFTER_MINUTES):
        return (
            "Hay riego activo, pero el ultimo agregado minutal del caudalimetro tiene mas de "
            f"{FLOWMETER_CAPTURE_STALE_AFTER_MINUTES} min. "
            "Compruebe que el capturador sigue activo; la sesion puede cerrarse con volumen final, "
            "pero la grafica historica podria quedar incompleta."
        )
    return None


def irrigation_summary_html(
    open_count: int,
    active_count: int,
    error_count: int,
    unknown_count: int,
    *,
    operational_count: int | None = None,
    current_flow: str | None = None,
    session_l: str | None = None,
    sector_totals_l: dict[str, float] | None = None,
) -> str:
    operational_total = len(irrigation_valve_controls())
    total = operational_total if operational_count is None else operational_count
    sector_totals_l = sector_totals_l or {}
    sector_metrics = "".join(
        compact_metric_html(f"Sector {sector_id}", format_number(sector_totals_l.get(sector_id), "L"))
        for sector_id in ("I", "II", "III", "IV")
    )
    return f"""
    {section_header_html("Resumen operativo")}
    <div class="argos-summary-grid">
        {compact_metric_html("Electroválvulas abiertas", f"{open_count} / {total}")}
        {compact_metric_html("Actuación activa", format_integer(active_count))}
        {compact_metric_html("Caudal actual", current_flow or "Sin dato")}
        {compact_metric_html("Sesión actual", session_l or "Sin dato")}
        {compact_metric_html("Incidencias", format_integer(error_count))}
        {compact_metric_html("Sin respuesta", format_integer(unknown_count))}
        {sector_metrics}
    </div>
    """


def valve_technical_frame(valve_controls: tuple[ValveControl, ...] | None = None) -> pd.DataFrame:
    valve_controls = valve_controls or irrigation_valve_controls()
    return pd.DataFrame.from_records(
        [
            {
                "Nombre": valve.functional_name,
                "EV": valve.technical_id,
                "Relay": valve.relay_id,
                "Control": "Habilitada" if valve.enabled_for_control else "Pendiente",
            }
            for valve in valve_controls
        ]
    )


def flowmeter_chart_frame(frame: pd.DataFrame) -> pd.DataFrame:
    chart_columns = [
        "window_start_utc",
        "avg_flow_l_min",
        "max_flow_l_min",
        "session_active_end",
        "relay1_state_end",
    ]
    return frame[[column for column in chart_columns if column in frame]].dropna(
        subset=["avg_flow_l_min", "max_flow_l_min"],
        how="all",
    )


def valve_control_options() -> dict[str, int]:
    return {valve_control_label(valve): valve.valve_id for valve in irrigation_valve_controls()}


def valve_name_for_id(valve_id: int) -> str:
    valve = valve_control_for_id(valve_id)
    if valve is not None:
        return valve.functional_name
    return f"EV{valve_id}"


def valve_control_for_id(valve_id: int) -> ValveControl | None:
    for valve in irrigation_valve_controls():
        if valve.valve_id == valve_id:
            return valve
    return None


def valve_control_label(valve: ValveControl) -> str:
    return f"{valve.functional_name} · {valve.technical_id}"


def valve_technical_detail(valve: ValveControl) -> str:
    return f"{valve.technical_id} · relay {valve.relay_id}"


def close_all_configured_valves(client: ArgosNodeClient) -> CloseAllValvesResult:
    results: list[CloseAllValveResult] = []
    for valve in irrigation_valve_controls():
        if not valve.irrigation or not valve.enabled_for_control:
            continue
        try:
            response = (
                client.close_irrigation_sector(valve.sector_id)
                if valve.sector_id is not None
                else client.close_valve(valve.valve_id)
            )
        except ArgosNodeError as exc:
            results.append(CloseAllValveResult(valve=valve, error=str(exc)))
            continue
        results.append(CloseAllValveResult(valve=valve, response=response))
    return CloseAllValvesResult(results=tuple(results))


def run_close_all_valves(client: ArgosNodeClient) -> None:
    result = close_all_configured_valves(client)
    for item in result.results:
        keys = valve_session_keys(item.valve.control_key)
        initialize_valve_session(keys)
        if item.ok:
            st.session_state[keys["phase"]] = "closed"
            st.session_state[keys["last_confirmed_phase"]] = "closed"
            st.session_state[keys["raw_response"]] = item.response
            st.session_state[keys["message"]] = "Valve is estimated closed after global close command."
            st.session_state[keys["error"]] = None
        else:
            st.session_state[keys["phase"]] = "error"
            st.session_state[keys["error"]] = f"Global close failed: {item.error}"
    st.session_state["close_all_valves_result"] = result


def render_close_all_valves_result(result: CloseAllValvesResult | None) -> None:
    if result is None:
        return
    if result.ok:
        closed = ", ".join(valve_control_label(item.valve) for item in result.succeeded)
        st.success(f"Cierre global completado: {closed}.")
        return
    failed = "; ".join(f"{valve_control_label(item.valve)}: {item.error}" for item in result.failed)
    succeeded = ", ".join(valve_control_label(item.valve) for item in result.succeeded)
    if succeeded:
        st.warning(f"Cierre parcial. Cerradas: {succeeded}. Fallos: {failed}.")
    else:
        st.error(f"No se pudo cerrar ninguna electroválvula. Fallos: {failed}.")


@st.fragment(run_every=FLOWMETER_LIVE_REFRESH_SECONDS)
def render_live_flowmeter_status(client: ArgosNodeClient, *, show_admin_actions: bool = True) -> None:
    with st.container(border=True, gap="small"):
        st.subheader("Caudalímetro")
        try:
            status = client.get_status()
            if status is None:
                st.caption("Sin respuesta de /status.")
                return
            parsed = parse_flowmeter_status(status)
        except (ArgosNodeError, ArgosNodeStatusError) as exc:
            st.caption(str(exc))
            return

        st.html(flowmeter_status_html(parsed))
        st.caption("En línea")
        if show_admin_actions:
            render_flowmeter_admin_actions(client)


def flowmeter_status_html(parsed: Any) -> str:
    return f"""
    <div class="argos-flowmeter-panel">
        <p class="argos-flowmeter-section-title">Lectura instantánea</p>
        <div class="argos-realtime-flowmeter-grid">
            {compact_metric_html("Caudal actual", format_number(parsed.flow_l_min, "L/min"))}
            {compact_metric_html("Sesión actual", format_number(parsed.session_l, "L"))}
            {compact_metric_html("Última sesión", format_number(parsed.last_session_l, "L"))}
            {compact_metric_html("Año hidrológico", format_number(parsed.hydrological_year_l, "L"))}
            {compact_metric_html("Total histórico", format_number(parsed.total_l, "L"))}
        </div>
    </div>
    """


def render_flowmeter_admin_actions(client: ArgosNodeClient) -> None:
    with st.expander("Acciones admin caudalímetro", expanded=False):
        actions = {
            "total": {
                "label": "Reset total",
                "confirm_label": "Confirmar reset total",
                "question": "¿Seguro que quieres reiniciar el volumen total histórico del caudalímetro?",
                "action": client.reset_flowmeter_total,
                "success_message": "Total reiniciado.",
            },
            "session": {
                "label": "Reset sesión",
                "confirm_label": "Confirmar reset sesión",
                "question": "¿Seguro que quieres reiniciar el volumen de la sesión del caudalímetro?",
                "action": client.reset_flowmeter_session,
                "success_message": "Sesión reiniciada.",
            },
            "hydrological_year": {
                "label": "Reset año hidrológico",
                "confirm_label": "Confirmar reset año",
                "question": "¿Seguro que quieres reiniciar el acumulado del año hidrológico?",
                "action": client.reset_flowmeter_hydrological_year,
                "success_message": "Año hidrológico reiniciado.",
            },
        }
        columns = st.columns(3)
        for column, (action_id, action_config) in zip(columns, actions.items()):
            with column:
                if st.button(
                    action_config["label"],
                    icon=":material/restart_alt:",
                    key=f"flowmeter_reset_{action_id}",
                    width="stretch",
                ):
                    st.session_state["flowmeter_pending_reset_action"] = action_id
        render_flowmeter_reset_confirmation(actions)


def render_flowmeter_reset_confirmation(actions: dict[str, dict[str, Any]]) -> None:
    pending_action = st.session_state.get("flowmeter_pending_reset_action")
    if pending_action not in actions:
        return
    action_config = actions[pending_action]
    st.warning(f"{action_config['question']} Esta acción se enviará al nodo y no se puede deshacer desde ARGOS.")
    confirm_col, cancel_col, _spacer_col = st.columns([1, 1, 3])
    with confirm_col:
        if st.button(
            action_config["confirm_label"],
            icon=":material/check:",
            type="primary",
            key=f"flowmeter_confirm_reset_{pending_action}",
            width="stretch",
        ):
            run_flowmeter_admin_action(action_config["action"], action_config["success_message"])
            st.session_state["flowmeter_pending_reset_action"] = None
    with cancel_col:
        if st.button(
            "Cancelar",
            icon=":material/close:",
            key=f"flowmeter_cancel_reset_{pending_action}",
            width="stretch",
        ):
            st.session_state["flowmeter_pending_reset_action"] = None


def run_flowmeter_admin_action(action: Any, success_message: str) -> None:
    try:
        action()
    except ArgosNodeError as exc:
        st.error(str(exc))
        return
    st.success(success_message)


def render_raw_valve_response(keys: dict[str, str]) -> None:
    error = st.session_state.get(keys["error"])
    if error:
        with st.expander("Diagnóstico técnico de electroválvula"):
            st.code(str(error))

    if not st.session_state[keys["raw_response"]]:
        with st.container(border=True, gap="small"):
            st.subheader("Raw valve response")
            st.caption("Sin respuesta registrada todavía.")
        return

    with st.expander("Raw valve response"):
        st.json(st.session_state[keys["raw_response"]])
        st.caption(
            "The exact relay switching instant is not observable from the dashboard yet. "
            "Movement start is approximated by the HTTP response reception time. "
            "Do not attribute the observed pre-movement delay to a specific component until argos-node logs it "
            "or returns an applied_at field after physically applying the relay state."
        )
        st.json(st.session_state[keys["timing"]])


def render_flowmeter_chart(node_url: str, *, start_iso: str, end_iso: str) -> None:
    chart_start_iso, chart_end_iso = flowmeter_chart_window(start_iso, end_iso)
    rows = cached_flowmeter_minutes(node_url, chart_start_iso, chart_end_iso)
    frame = dataframe_from_records(rows, "window_start_utc")
    with st.container(border=True, gap="small"):
        st.subheader("Caudalímetro")
        if frame.empty:
            st.caption("Sin agregados minutales para el rango seleccionado.")
            return

        chart_columns = [
            "window_start_utc",
            "avg_flow_l_min",
            "max_flow_l_min",
            "session_active_end",
            "relay1_state_end",
        ]
        chart_frame = frame[[column for column in chart_columns if column in frame]].dropna(
            subset=["avg_flow_l_min", "max_flow_l_min"],
            how="all",
        )
        if chart_frame.empty:
            st.caption("No hay valores de caudal para graficar.")
            return
        chart_column, metrics_column = st.columns([5, 1], vertical_alignment="top")
        with chart_column:
            st.plotly_chart(build_flowmeter_figure(chart_frame, start_iso=chart_start_iso, end_iso=chart_end_iso), width="stretch")
        with metrics_column:
            latest = frame.iloc[-1]
            st.html(
                f"""
                <div class="argos-flowmeter-grid">
                    {compact_metric_html("Caudal medio", format_number(latest.get("avg_flow_l_min"), "L/min"))}
                    {compact_metric_html("Volumen minuto", format_number(latest.get("volume_l"), "L"))}
                    {compact_metric_html("Total", format_number(latest.get("total_l_end"), "L"))}
                    {compact_metric_html("Año hidr.", format_number(latest.get("hydrological_year_l_end"), "L"))}
                    {compact_metric_html("Últ. sesión", format_number(latest.get("last_session_l_end"), "L"))}
                    {compact_metric_html("EV", format_binary_ev_state(latest.get("session_active_end", latest.get("relay1_state_end"))))}
                </div>
                """
            )


def render_compact_metric(label: str, value: str) -> None:
    st.html(compact_metric_html(label, value))


def compact_metric_html(label: str, value: str) -> str:
    return (
        '<div class="argos-compact-metric">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(value)}</strong>"
        "</div>"
    )


def build_flowmeter_figure(frame: pd.DataFrame, *, start_iso: str | None = None, end_iso: str | None = None) -> go.Figure:
    frame = frame.sort_values("window_start_utc").copy()
    x_values = local_time_values(frame["window_start_utc"])
    avg_x, avg_y = flowmeter_trace_values(frame["window_start_utc"], x_values, frame["avg_flow_l_min"])
    max_x, max_y = flowmeter_trace_values(frame["window_start_utc"], x_values, frame["max_flow_l_min"])
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=avg_x,
            y=avg_y,
            mode="lines+markers",
            name="Caudal medio",
            line={"color": "#2563eb"},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=max_x,
            y=max_y,
            mode="lines+markers",
            name="Caudal máximo",
            line={"color": "#0f766e"},
        )
    )
    ev_column = "session_active_end" if "session_active_end" in frame else "relay1_state_end"
    if ev_column in frame:
        relay_frame = frame.dropna(subset=[ev_column]).copy()
        if not relay_frame.empty:
            relay_x = local_time_values(relay_frame["window_start_utc"])
            relay_trace_x, relay_trace_y = flowmeter_trace_values(
                relay_frame["window_start_utc"],
                relay_x,
                relay_frame[ev_column].astype(int),
            )
            figure.add_trace(
                go.Scatter(
                    x=relay_trace_x,
                    y=relay_trace_y,
                    mode="lines",
                    name="EV",
                    line={"color": "#ef4444", "shape": "hv", "width": 2},
                    yaxis="y2",
                )
            )
    xaxis: dict[str, Any] = {"title": local_time_axis_title()}
    xaxis_range = flowmeter_visible_xaxis_range(frame, start_iso=start_iso, end_iso=end_iso)
    if xaxis_range is not None:
        xaxis["range"] = xaxis_range
    figure.update_layout(
        height=240,
        margin={"t": 0, "r": 48, "b": 18, "l": 34},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0, "font": {"size": 10}},
        xaxis=xaxis,
        yaxis={"title": "L/min", "rangemode": "tozero", "gridcolor": "rgba(148, 163, 184, 0.28)"},
        yaxis2={
            "title": "EV",
            "overlaying": "y",
            "side": "right",
            "range": [-0.05, 1.05],
            "tickmode": "array",
            "tickvals": [0, 1],
            "ticktext": ["0", "1"],
            "showgrid": False,
        },
    )
    figure.update_xaxes(tickfont={"size": 10}, title_font={"size": 10})
    figure.update_yaxes(tickfont={"size": 10}, title_font={"size": 10})
    return figure


def build_irrigation_water_figure(frame: pd.DataFrame, *, start_iso: str | None = None, end_iso: str | None = None) -> go.Figure | None:
    if frame.empty or "window_start_utc" not in frame:
        return None

    sorted_frame = frame.sort_values("window_start_utc").copy()
    has_flow = {"avg_flow_l_min", "max_flow_l_min"}.intersection(sorted_frame.columns)
    accumulated_columns = [column for column in ("session_l_end",) if column in sorted_frame]
    if not has_flow and not accumulated_columns:
        return None

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.52, 0.48],
        specs=[[{"secondary_y": True}], [{}]],
    )

    flow_frame = flowmeter_chart_frame(sorted_frame) if has_flow else pd.DataFrame()
    if not flow_frame.empty:
        x_values = local_time_values(flow_frame["window_start_utc"])
        avg_x, avg_y = flowmeter_trace_values(flow_frame["window_start_utc"], x_values, flow_frame["avg_flow_l_min"])
        max_x, max_y = flowmeter_trace_values(flow_frame["window_start_utc"], x_values, flow_frame["max_flow_l_min"])
        figure.add_trace(
            go.Scatter(
                x=avg_x,
                y=avg_y,
                mode="lines+markers",
                name="Caudal medio",
                legendgroup="flow",
                line={"color": "#2563eb", "width": 2},
                marker={"size": 4},
            ),
            row=1,
            col=1,
            secondary_y=False,
        )
        figure.add_trace(
            go.Scatter(
                x=max_x,
                y=max_y,
                mode="lines+markers",
                name="Caudal máximo",
                legendgroup="flow",
                line={"color": "#0f766e", "width": 2},
                marker={"size": 4},
            ),
            row=1,
            col=1,
            secondary_y=False,
        )
        ev_column = "session_active_end" if "session_active_end" in flow_frame else "relay1_state_end"
        if ev_column in flow_frame:
            relay_frame = flow_frame.dropna(subset=[ev_column]).copy()
            if not relay_frame.empty:
                relay_x = local_time_values(relay_frame["window_start_utc"])
                relay_trace_x, relay_trace_y = flowmeter_trace_values(
                    relay_frame["window_start_utc"],
                    relay_x,
                    relay_frame[ev_column].astype(int),
                )
                figure.add_trace(
                    go.Scatter(
                        x=relay_trace_x,
                        y=relay_trace_y,
                        mode="lines",
                        name="EV",
                        legendgroup="flow",
                        line={"color": "#ef4444", "shape": "hv", "width": 2},
                    ),
                    row=1,
                    col=1,
                    secondary_y=True,
                )

    accumulated_frame = sorted_frame[["window_start_utc", *accumulated_columns]].dropna(subset=accumulated_columns, how="all")
    if not accumulated_frame.empty:
        series = [("session_l_end", "Sesión actual", "#2563eb")]
        for column, label, color in series:
            if column not in accumulated_frame:
                continue
            trace_frame = accumulated_frame.dropna(subset=[column])
            if trace_frame.empty:
                continue
            figure.add_trace(
                go.Scatter(
                    x=local_time_values(trace_frame["window_start_utc"]),
                    y=trace_frame[column],
                    mode="lines+markers",
                    name=label,
                    legendgroup="accumulated",
                    line={"color": color, "width": 2},
                    marker={"size": 4},
                ),
                row=2,
                col=1,
            )

    xaxis_range = flowmeter_visible_xaxis_range(sorted_frame, start_iso=start_iso, end_iso=end_iso)
    figure.update_layout(
        height=360,
        margin={"t": 44, "r": 48, "b": 24, "l": 42},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.04,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 10},
            "bgcolor": "rgba(255,255,255,0.88)",
        },
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    figure.update_xaxes(
        title_text="",
        tickfont={"size": 10},
        title_font={"size": 10},
        gridcolor="rgba(148, 163, 184, 0.24)",
        range=xaxis_range,
        row=1,
        col=1,
    )
    figure.update_xaxes(
        title_text=local_time_axis_title(),
        tickfont={"size": 10},
        title_font={"size": 10},
        gridcolor="rgba(148, 163, 184, 0.24)",
        range=xaxis_range,
        row=2,
        col=1,
    )
    figure.update_yaxes(
        title_text="Caudal, L/min",
        rangemode="tozero",
        tickfont={"size": 10},
        title_font={"size": 10},
        gridcolor="rgba(148, 163, 184, 0.28)",
        row=1,
        col=1,
        secondary_y=False,
    )
    figure.update_yaxes(
        title_text="EV",
        range=[-0.05, 1.05],
        tickmode="array",
        tickvals=[0, 1],
        ticktext=["0", "1"],
        showgrid=False,
        tickfont={"size": 10},
        title_font={"size": 10},
        row=1,
        col=1,
        secondary_y=True,
    )
    figure.update_yaxes(
        title_text="Riego acumulado, L",
        rangemode="tozero",
        tickfont={"size": 10},
        title_font={"size": 10},
        gridcolor="rgba(148, 163, 184, 0.28)",
        row=2,
        col=1,
    )
    return figure


def build_accumulated_water_figure(frame: pd.DataFrame, *, start_iso: str | None = None, end_iso: str | None = None) -> go.Figure | None:
    columns = [column for column in ("total_l_end", "session_l_end", "hydrological_year_l_end") if column in frame]
    if not columns or "window_start_utc" not in frame:
        return None
    chart_frame = frame[["window_start_utc", *columns]].dropna(subset=columns, how="all").sort_values("window_start_utc")
    if chart_frame.empty:
        return None
    figure = go.Figure()
    series = [
        ("total_l_end", "Total histórico", "#15803d"),
        ("session_l_end", "Sesión actual", "#2563eb"),
        ("hydrological_year_l_end", "Año hidrológico", "#0f766e"),
    ]
    for column, label, color in series:
        if column not in chart_frame:
            continue
        trace_frame = chart_frame.dropna(subset=[column])
        if trace_frame.empty:
            continue
        trace_x = local_time_values(trace_frame["window_start_utc"])
        figure.add_trace(
            go.Scatter(
                x=trace_x,
                y=trace_frame[column],
                mode="lines+markers",
                name=label,
                line={"color": color, "width": 2},
                marker={"size": 4},
            )
        )
    if not figure.data:
        return None
    xaxis: dict[str, Any] = {"title": local_time_axis_title()}
    xaxis_range = flowmeter_visible_xaxis_range(chart_frame, start_iso=start_iso, end_iso=end_iso)
    if xaxis_range is not None:
        xaxis["range"] = xaxis_range
    figure.update_layout(
        height=220,
        margin={"t": 0, "r": 16, "b": 18, "l": 42},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0, "font": {"size": 10}},
        xaxis=xaxis,
        yaxis={"title": "L", "rangemode": "tozero", "gridcolor": "rgba(148, 163, 184, 0.28)"},
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    figure.update_xaxes(tickfont={"size": 10}, title_font={"size": 10})
    figure.update_yaxes(tickfont={"size": 10}, title_font={"size": 10})
    return figure


def flowmeter_visible_xaxis_range(frame: pd.DataFrame, *, start_iso: str | None = None, end_iso: str | None = None) -> list[datetime] | None:
    start = parse_datetime(start_iso)
    end = parse_datetime(end_iso)
    if start is None or end is None or frame.empty or "window_start_utc" not in frame:
        return None

    timestamps = pd.to_datetime(frame["window_start_utc"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return None

    data_start = timestamps.min().to_pydatetime() - timedelta(minutes=1)
    visible_start = max(start, data_start)
    timezone = ZoneInfo(get_settings().local_timezone)
    return [
        visible_start.astimezone(timezone).replace(tzinfo=None),
        end.astimezone(timezone).replace(tzinfo=None),
    ]


def flowmeter_chart_window(start_iso: str, end_iso: str) -> tuple[str, str]:
    start = parse_datetime(start_iso)
    end = parse_datetime(end_iso)
    now = datetime.now(UTC)
    if end is None or end > now:
        end = now
    if start is None:
        start = end - timedelta(hours=FLOWMETER_CHART_WINDOW_HOURS)
    start = max(start, end - timedelta(hours=FLOWMETER_CHART_WINDOW_HOURS))
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def flowmeter_trace_values(
    utc_values: pd.Series,
    local_values: pd.Series,
    y_values: pd.Series,
    *,
    max_gap: timedelta = timedelta(minutes=2),
) -> tuple[list[Any], list[Any]]:
    x_out: list[Any] = []
    y_out: list[Any] = []
    previous_utc: pd.Timestamp | None = None
    for utc_value, local_value, y_value in zip(pd.to_datetime(utc_values, utc=True), local_values, y_values):
        if previous_utc is not None and utc_value - previous_utc > max_gap and x_out:
            x_out.append(local_value)
            y_out.append(None)
        x_out.append(local_value)
        y_out.append(y_value)
        previous_utc = utc_value
    return x_out, y_out


def valve_session_keys(control_key: int | str) -> dict[str, str]:
    prefix = str(control_key)
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


def refresh_valve_from_backend(client: ArgosNodeClient, *, valve: ValveControl, keys: dict[str, str]) -> None:
    try:
        state = (
            client.get_irrigation_sector(valve.sector_id)
            if valve.sector_id is not None
            else client.get_valve(valve.valve_id)
        )
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
        st.caption(valve_estimation_message("open"))
    elif phase == "closed":
        st.caption(valve_estimation_message("closed"))
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


def valve_estimation_message(phase: str) -> str:
    return f"ARGOS estimates the valve is {phase}; no independent position sensor confirms it."


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
    valve: ValveControl,
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
        if valve.sector_id is not None:
            response = (
                client.open_irrigation_sector(valve.sector_id)
                if command == "open"
                else client.close_irrigation_sector(valve.sector_id)
            )
        else:
            response = client.open_valve(valve.valve_id) if command == "open" else client.close_valve(valve.valve_id)
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
        st.caption("Detalle técnico disponible en Respuesta técnica.")
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


def add_csv_download(frame: pd.DataFrame, label: str, file_name: str, *, key: str | None = None) -> None:
    if frame.empty:
        return
    st.download_button(
        label,
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
        icon=":material/download:",
        key=key,
    )


def format_number(value: Any, unit: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, int | float):
        suffix = f" {unit}" if unit else ""
        return f"{value:.2f}{suffix}"
    return str(value)


def format_integer(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return f"{value:d}"
    if isinstance(value, float):
        return f"{value:.0f}"
    return str(value)


def format_binary_signal(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return "1" if int(value) == 1 else "0"
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "on", "high"}:
        return "1"
    if normalized in {"false", "0", "off", "low"}:
        return "0"
    return str(value)


def format_wind_direction(value: Any) -> str:
    if value is None:
        return "-"
    if not isinstance(value, int | float):
        return str(value)

    normalized = value % 360
    compass_points = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    compass = compass_points[int((normalized + 11.25) // 22.5) % len(compass_points)]
    return f"{normalized:.0f} deg · {compass}"


def format_datetime(value: Any) -> str:
    if not value:
        return "-"
    return str(value).replace("T", " ").replace("Z", " UTC")


def format_local_datetime(value: Any) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return "-"
    local = parsed.astimezone()
    month = SPANISH_MONTH_ABBR[local.month]
    return f"{local.day} {month} {local.year} · {local:%H:%M}"


def format_compact_local_datetime(value: Any) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return "-"
    local = parsed.astimezone()
    month = SPANISH_MONTH_ABBR[local.month]
    return f"{local.day} {month} {local.year}, {local:%H:%M}"


def format_compact_date_range(start: str, end: str) -> str:
    return f"{format_compact_date(start)}–{format_compact_date(end)}"


def format_compact_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {SPANISH_MONTH_ABBR[parsed.month]} {parsed.year}"


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, pd.Timestamp):
        parsed = value.to_pydatetime()
    elif isinstance(value, datetime):
        parsed = value
    elif value:
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


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


def format_binary_ev_state(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    if isinstance(value, bool):
        return "Abierta (1)" if value else "Cerrada (0)"
    if isinstance(value, int | float):
        return "Abierta (1)" if int(value) == 1 else "Cerrada (0)"
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "open", "opened", "on"}:
        return "Abierta (1)"
    if normalized in {"false", "0", "closed", "close", "off"}:
        return "Cerrada (0)"
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
