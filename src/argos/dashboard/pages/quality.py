from __future__ import annotations

import pandas as pd
import streamlit as st

from argos.dashboard.api_client import ArgosApiClient, ArgosApiError
from argos.dashboard.dataframes import dataframe_from_records
from argos.dashboard.raw_reports import build_raw_report_table, latest_payload_preview


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
