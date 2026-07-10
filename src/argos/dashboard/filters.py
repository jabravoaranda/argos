from __future__ import annotations

import pandas as pd


def filter_observations_by_source(frame: pd.DataFrame, selected_sources: list[str]) -> pd.DataFrame:
    if frame.empty or "source" not in frame.columns or not selected_sources:
        return frame
    return frame[frame["source"].isin(selected_sources)].copy()


def observation_source_counts(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty or "source" not in frame.columns:
        return {}
    counts = frame["source"].fillna("UNKNOWN").value_counts().sort_index()
    return {str(source): int(count) for source, count in counts.items()}
