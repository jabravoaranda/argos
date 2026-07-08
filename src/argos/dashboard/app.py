from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from argos.dashboard.aggregations import (
    anomalies,
    annual_monthly,
    daily_hourly,
    daily_summary,
    linear_trend,
    monthly_daily,
    moving_average,
    weekly_daily,
)
from argos.dashboard.data_loader import (
    DATETIME_COLUMN,
    DEFAULT_VARIABLES,
    DEFAULT_WEATHER_DIR,
    available_variables,
    filter_by_date_range,
    load_weather_data,
)
from argos.dashboard.plots import bar, time_series, trend_figure


def main() -> None:
    st.set_page_config(page_title="ARGOS Dashboard", layout="wide")
    st.title("ARGOS Dashboard")

    with st.sidebar:
        st.header("Datos meteorologicos")
        data_dir = Path(st.text_input("Directorio de datos", str(DEFAULT_WEATHER_DIR)))
        if st.button("Recargar datos", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    loaded = _cached_load(data_dir)
    data = loaded.frame
    _show_loader_messages(loaded)

    if data.empty:
        st.info("No hay datos meteorologicos disponibles todavia.")
        return

    min_date = data[DATETIME_COLUMN].min().date()
    max_date = data[DATETIME_COLUMN].max().date()
    variables = available_variables(data)
    default_variables = [variable for variable in DEFAULT_VARIABLES if variable in variables] or variables[:3]

    with st.sidebar:
        date_range = st.date_input("Rango de fechas", value=(min_date, max_date), min_value=min_date, max_value=max_date)
        if not isinstance(date_range, tuple) or len(date_range) != 2:
            st.warning("Selecciona una fecha inicial y una final.")
            return
        selected_variables = st.multiselect("Variables", options=variables, default=default_variables)
        moving_window = st.slider("Ventana de media movil", min_value=2, max_value=48, value=6)

    filtered = filter_by_date_range(data, date_range[0], date_range[1])
    if filtered.empty:
        st.info("No hay datos en el rango seleccionado.")
        return

    available_days = sorted(filtered[DATETIME_COLUMN].dt.date.unique())
    with st.sidebar:
        selected_day = st.selectbox(
            "Dia",
            options=available_days,
            index=0,
            format_func=lambda value: value.isoformat(),
        )

    st.caption(f"{len(filtered)} lecturas desde {len(loaded.files)} CSV.")
    tabs = st.tabs(["Diario", "Semanal", "Mensual", "Anual", "Tendencias"])

    with tabs[0]:
        _render_daily(filtered, selected_day, selected_variables)
    with tabs[1]:
        _render_weekly(filtered, selected_variables)
    with tabs[2]:
        _render_monthly(filtered, selected_variables)
    with tabs[3]:
        _render_annual(filtered, selected_variables)
    with tabs[4]:
        _render_trends(filtered, selected_variables, moving_window)


@st.cache_data(show_spinner=False)
def _cached_load(data_dir: Path):
    return load_weather_data(data_dir)


def _show_loader_messages(loaded) -> None:
    for message in loaded.messages:
        st.warning(message)
    if loaded.missing_columns:
        st.warning("Columnas ausentes en algun CSV: " + ", ".join(loaded.missing_columns))


def _render_daily(data: pd.DataFrame, selected_day, variables: list[str]) -> None:
    day_data = data[data[DATETIME_COLUMN].dt.date == selected_day].copy()
    if day_data.empty:
        st.info("No hay lecturas para el dia seleccionado.")
        return

    st.subheader(f"Diario - {selected_day}")
    st.caption(f"{len(day_data)} lecturas disponibles para el dia seleccionado.")
    st.plotly_chart(time_series(day_data, variables, "Lecturas intradia"), use_container_width=True)
    hourly = daily_hourly(day_data, variables)
    if len(hourly) > 1:
        st.plotly_chart(time_series(hourly, variables, "Promedios horarios"), use_container_width=True)
    else:
        st.info("Aun no hay datos en varias horas distintas para calcular una curva de promedios horarios.")
    summary = daily_summary(day_data)
    _daily_metrics(day_data)
    _downloadable_table(summary, "Resumen diario", "resumen_diario.csv")


def _render_weekly(data: pd.DataFrame, variables: list[str]) -> None:
    st.subheader("Semanal")
    summary = weekly_daily(data)
    flat = _flatten_summary(summary)
    st.plotly_chart(time_series(data, variables, "Evolucion de temperatura, humedad y variables seleccionadas"), use_container_width=True)
    if "lluvia_diaria" in data.columns:
        rain = data[[DATETIME_COLUMN, "lluvia_diaria"]].set_index(DATETIME_COLUMN).resample("D").max().reset_index()
        st.plotly_chart(bar(rain, DATETIME_COLUMN, "lluvia_diaria", "Lluvia acumulada semanal por dia"), use_container_width=True)
    _downloadable_table(flat, "Agregados por dia", "resumen_semanal.csv")


def _render_monthly(data: pd.DataFrame, variables: list[str]) -> None:
    st.subheader("Mensual")
    summary = monthly_daily(data)
    flat = _flatten_summary(summary)
    st.plotly_chart(time_series(data, variables, "Maximos, minimos y evolucion diaria"), use_container_width=True)
    if "lluvia_diaria" in data.columns:
        rain = data[[DATETIME_COLUMN, "lluvia_diaria"]].set_index(DATETIME_COLUMN).resample("D").max().reset_index()
        st.plotly_chart(bar(rain, DATETIME_COLUMN, "lluvia_diaria", "Lluvia acumulada mensual por dia"), use_container_width=True)
    _downloadable_table(flat, "Agregados diarios del mes", "resumen_mensual.csv")


def _render_annual(data: pd.DataFrame, variables: list[str]) -> None:
    st.subheader("Anual")
    summary = annual_monthly(data)
    flat = _flatten_summary(summary)
    st.plotly_chart(time_series(data, variables, "Evolucion estacional"), use_container_width=True)
    if "lluvia_diaria" in data.columns:
        rain = data[[DATETIME_COLUMN, "lluvia_diaria"]].set_index(DATETIME_COLUMN).resample("ME").max().reset_index()
        st.plotly_chart(bar(rain, DATETIME_COLUMN, "lluvia_diaria", "Lluvia anual acumulada por mes"), use_container_width=True)
    _downloadable_table(flat, "Agregados mensuales", "resumen_anual.csv")


def _render_trends(data: pd.DataFrame, variables: list[str], moving_window: int) -> None:
    st.subheader("Tendencias")
    if not variables:
        st.info("Selecciona al menos una variable.")
        return

    averages = moving_average(data, variables, moving_window)
    average_columns = [f"{variable}_media_movil" for variable in variables]
    st.plotly_chart(time_series(averages, average_columns, "Medias moviles"), use_container_width=True)

    anomaly_data = anomalies(data, variables)
    anomaly_columns = [f"{variable}_anomalia" for variable in variables]
    st.plotly_chart(time_series(anomaly_data, anomaly_columns, "Anomalias respecto al periodo seleccionado"), use_container_width=True)

    variable = st.selectbox("Variable para tendencia lineal", variables)
    trend = linear_trend(data, variable)
    st.plotly_chart(trend_figure(trend, variable, f"{variable}_tendencia"), use_container_width=True)
    _downloadable_table(anomaly_data, "Tabla de anomalias", "anomalias.csv")


def _daily_metrics(day_data: pd.DataFrame) -> None:
    columns = st.columns(7)
    metrics = [
        ("Temp. media", "temperatura_exterior", "mean"),
        ("Temp. min", "temperatura_exterior", "min"),
        ("Temp. max", "temperatura_exterior", "max"),
        ("Humedad media", "humedad_exterior", "mean"),
        ("Lluvia diaria", "lluvia_diaria", "max"),
        ("Viento max", "viento_racha", "max"),
        ("UV max", "uv", "max"),
    ]
    for column, (label, variable, method) in zip(columns, metrics, strict=False):
        value = getattr(day_data[variable], method)() if variable in day_data.columns else pd.NA
        column.metric(label, _format_metric(value))

    if "radiacion_solar" in day_data.columns:
        st.metric("Radiacion maxima", _format_metric(day_data["radiacion_solar"].max()))


def _flatten_summary(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return summary
    flat = summary.copy()
    if isinstance(flat.columns, pd.MultiIndex):
        flat.columns = ["_".join(str(part) for part in column if part) for column in flat.columns]
    return flat.reset_index()


def _downloadable_table(data: pd.DataFrame, title: str, file_name: str) -> None:
    st.subheader(title)
    st.dataframe(data, use_container_width=True)
    st.download_button(
        label=f"Descargar {title} en CSV",
        data=data.to_csv(index=False).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
    )


def _format_metric(value) -> str:
    if pd.isna(value):
        return "-"
    return f"{value:.2f}"


if __name__ == "__main__":
    main()
