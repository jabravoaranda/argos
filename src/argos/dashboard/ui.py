from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st


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


def compact_metric_html(label: str, value: str) -> str:
    return (
        '<div class="argos-compact-metric">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(value)}</strong>"
        "</div>"
    )
