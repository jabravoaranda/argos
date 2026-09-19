from __future__ import annotations

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
