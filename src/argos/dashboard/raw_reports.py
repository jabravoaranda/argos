from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


def build_raw_report_table(raw_reports: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(raw_reports)
    if frame.empty:
        return frame
    if "received_at_utc" in frame:
        frame["received_at_utc"] = pd.to_datetime(frame["received_at_utc"])
    if "payload_json" in frame:
        frame["payload_keys"] = frame["payload_json"].map(format_payload_keys)
        frame = frame.drop(columns=["payload_json"])
    return frame


def latest_payload_preview(raw_reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not raw_reports:
        return None
    payload = raw_reports[0].get("payload_json")
    if isinstance(payload, dict):
        return payload
    return None


def format_payload_keys(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return ", ".join(sorted(str(key) for key in payload))
