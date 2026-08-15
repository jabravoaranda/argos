from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from argos.ops.data_duplicates import audit_duplicates, has_structural_duplicates


SCHEMA = """
CREATE TABLE weather_observations (id INTEGER PRIMARY KEY, gateway_id INTEGER, observed_at_utc TEXT, source TEXT);
CREATE TABLE ecowitt_raw_reports (id INTEGER PRIMARY KEY, payload_hash TEXT);
CREATE TABLE ecowitt_cloud_raw_reports (id INTEGER PRIMARY KEY, payload_hash TEXT);
CREATE TABLE weather_daily_observations (id INTEGER PRIMARY KEY, station_id INTEGER, observation_date TEXT);
CREATE TABLE satellite_observations (
    id INTEGER PRIMARY KEY,
    source_id INTEGER,
    zone_id INTEGER,
    external_item_id TEXT,
    processing_version TEXT
);
CREATE TABLE satellite_assets (id INTEGER PRIMARY KEY, observation_id INTEGER, asset_type TEXT);
CREATE TABLE argos_node_flowmeter_minutes (id INTEGER PRIMARY KEY, node_url TEXT, window_start_utc TEXT);
CREATE TABLE field_events (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT,
    event_type TEXT,
    title TEXT,
    zone_slug TEXT
);
"""


def test_audit_duplicates_passes_without_duplicates() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    create_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO weather_observations VALUES (1, 1, '2026-08-02T00:00:00Z', 'DIRECT')")
        )

    with Session(engine) as session:
        results = audit_duplicates(session)

    assert not has_structural_duplicates(results)
    assert all(result.duplicate_groups == 0 for result in results)


def test_audit_duplicates_fails_for_structural_duplicates() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    create_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO weather_observations VALUES
                (1, 1, '2026-08-02T00:00:00Z', 'DIRECT'),
                (2, 1, '2026-08-02T00:00:00Z', 'DIRECT')
                """
            )
        )

    with Session(engine) as session:
        results = audit_duplicates(session)

    ecowitt = next(result for result in results if result.name == "ecowitt_observations")
    assert ecowitt.duplicate_groups == 1
    assert ecowitt.affected_rows == 2
    assert has_structural_duplicates(results)


def test_field_event_duplicates_are_warning_only() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    create_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO field_events VALUES
                (1, '2026-08-02T00:00:00Z', 'irrigation', 'Riego', 'norte'),
                (2, '2026-08-02T00:00:00Z', 'irrigation', 'Riego', 'norte')
                """
            )
        )

    with Session(engine) as session:
        results = audit_duplicates(session)

    field_events = next(result for result in results if result.name == "field_events")
    assert field_events.duplicate_groups == 1
    assert field_events.affected_rows == 2
    assert not has_structural_duplicates(results)


def create_schema(engine) -> None:
    raw_connection = engine.raw_connection()
    try:
        raw_connection.executescript(SCHEMA)
        raw_connection.commit()
    finally:
        raw_connection.close()
