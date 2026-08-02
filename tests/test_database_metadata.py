from __future__ import annotations

from argos.database.base import Base
from argos import models as _models


def test_initial_schema_tables_are_registered() -> None:
    expected_tables = {
        "stations",
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
        "argos_node_flowmeter_minutes",
        "argos_node_flowmeter_reset_events",
        "argos_node_flowmeter_sessions",
        "field_events",
    }

    assert expected_tables <= set(Base.metadata.tables)
    assert _models.Station.__tablename__ == "stations"
    assert _models.Gateway.__tablename__ == "gateways"
    assert _models.ArgosNodeFlowmeterMinute.__tablename__ == "argos_node_flowmeter_minutes"
    assert _models.ArgosNodeFlowmeterSession.__tablename__ == "argos_node_flowmeter_sessions"
    assert _models.FieldEvent.__tablename__ == "field_events"
