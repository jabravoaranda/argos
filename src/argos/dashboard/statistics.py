from __future__ import annotations

from typing import Any

import pandas as pd


def build_descriptive_statistics(frame: pd.DataFrame, variables: list[str], labels: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    row_count = len(frame)
    for variable in variables:
        if variable not in frame:
            continue
        values = pd.to_numeric(frame[variable], errors="coerce")
        valid = values.dropna()
        missing_count = int(row_count - len(valid))
        row: dict[str, Any] = {
            "variable": labels.get(variable, variable),
            "samples": row_count,
            "valid": int(len(valid)),
            "missing": missing_count,
            "missing_pct": (missing_count / row_count * 100.0) if row_count else 0.0,
        }
        if valid.empty:
            row.update(
                {
                    "mean": None,
                    "median": None,
                    "std": None,
                    "min": None,
                    "p05": None,
                    "p25": None,
                    "p75": None,
                    "p95": None,
                    "max": None,
                    "range": None,
                    "iqr": None,
                }
            )
        else:
            p05 = float(valid.quantile(0.05))
            p25 = float(valid.quantile(0.25))
            p75 = float(valid.quantile(0.75))
            p95 = float(valid.quantile(0.95))
            min_value = float(valid.min())
            max_value = float(valid.max())
            row.update(
                {
                    "mean": float(valid.mean()),
                    "median": float(valid.median()),
                    "std": float(valid.std()) if len(valid) > 1 else 0.0,
                    "min": min_value,
                    "p05": p05,
                    "p25": p25,
                    "p75": p75,
                    "p95": p95,
                    "max": max_value,
                    "range": max_value - min_value,
                    "iqr": p75 - p25,
                }
            )
        rows.append(row)

    return pd.DataFrame.from_records(rows)
