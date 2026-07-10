from __future__ import annotations

from argos.database.base import Base
from argos import models as _models


def test_initial_schema_tables_are_registered() -> None:
    expected_tables = {
        "gateways",
        "gateway_aliases",
        "ecowitt_raw_reports",
        "ecowitt_cloud_raw_reports",
        "weather_observations",
        "daily_statistics",
        "weekly_statistics",
        "unknown_fields",
        "ingestion_events",
        "data_gaps",
    }

    assert expected_tables <= set(Base.metadata.tables)
    assert _models.Gateway.__tablename__ == "gateways"
