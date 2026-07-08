from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from argos.dashboard.data_loader import DATETIME_COLUMN


def time_series(data: pd.DataFrame, variables: list[str], title: str) -> go.Figure:
    figure = go.Figure()
    if data.empty or not variables:
        figure.update_layout(title=title)
        return figure

    for variable in variables:
        if variable in data.columns:
            figure.add_trace(
                go.Scatter(
                    x=data[DATETIME_COLUMN],
                    y=data[variable],
                    mode="lines+markers",
                    name=variable,
                )
            )
    figure.update_layout(title=title, xaxis_title="Fecha", yaxis_title="Valor", hovermode="x unified")
    return figure


def bar(data: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    if data.empty or x not in data.columns or y not in data.columns:
        return go.Figure().update_layout(title=title)
    return px.bar(data, x=x, y=y, title=title)


def trend_figure(data: pd.DataFrame, variable: str, trend_column: str) -> go.Figure:
    figure = go.Figure()
    if data.empty:
        figure.update_layout(title=f"Tendencia de {variable}")
        return figure

    figure.add_trace(go.Scatter(x=data[DATETIME_COLUMN], y=data[variable], mode="markers", name=variable))
    if trend_column in data.columns:
        figure.add_trace(go.Scatter(x=data[DATETIME_COLUMN], y=data[trend_column], mode="lines", name="tendencia"))
    figure.update_layout(title=f"Tendencia de {variable}", xaxis_title="Fecha", yaxis_title=variable, hovermode="x unified")
    return figure
