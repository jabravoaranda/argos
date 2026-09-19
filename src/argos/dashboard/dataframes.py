from __future__ import annotations

from typing import Any

import pandas as pd


def dataframe_from_records(records: list[dict[str, Any]], date_column: str) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(records)
    if not frame.empty and date_column in frame:
        frame[date_column] = pd.to_datetime(frame[date_column])
    return frame
