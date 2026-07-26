"""Create initial ARGOS schema.

Revision ID: 20260710_0001
Revises: None
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gateways",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("mac_address", sa.String(length=64), nullable=False),
        sa.Column("station_type", sa.String(length=100), nullable=True),
        sa.Column("firmware_version", sa.String(length=100), nullable=True),
        sa.Column("hardware_version", sa.String(length=100), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("mac_address", name="uq_gateways_mac_address"),
        sa.UniqueConstraint("uuid", name="uq_gateways_uuid"),
    )
    op.create_index("ix_gateways_mac_address", "gateways", ["mac_address"])
    op.create_index("ix_gateways_last_seen_at", "gateways", ["last_seen_at"])

    op.create_table(
        "ecowitt_raw_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gateway_id", sa.Integer(), sa.ForeignKey("gateways.id"), nullable=True),
        sa.Column("received_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_timestamp_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_method", sa.String(length=16), nullable=False),
        sa.Column("source_ip", sa.String(length=128), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("headers_json", sa.JSON(), nullable=True),
        sa.Column("query_string", sa.Text(), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("payload_hash", name="uq_ecowitt_raw_reports_payload_hash"),
    )
    op.create_index("ix_ecowitt_raw_reports_gateway_id", "ecowitt_raw_reports", ["gateway_id"])
    op.create_index("ix_ecowitt_raw_reports_received_at_utc", "ecowitt_raw_reports", ["received_at_utc"])
    op.create_index("ix_ecowitt_raw_reports_device_timestamp_utc", "ecowitt_raw_reports", ["device_timestamp_utc"])
    op.create_index(
        "ix_ecowitt_raw_reports_gateway_received",
        "ecowitt_raw_reports",
        ["gateway_id", "received_at_utc"],
    )

    op.create_table(
        "weather_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gateway_id", sa.Integer(), sa.ForeignKey("gateways.id"), nullable=True),
        sa.Column("raw_report_id", sa.Integer(), sa.ForeignKey("ecowitt_raw_reports.id"), nullable=False),
        sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("indoor_temperature_c", sa.Float(), nullable=True),
        sa.Column("indoor_humidity_pct", sa.Float(), nullable=True),
        sa.Column("outdoor_temperature_c", sa.Float(), nullable=True),
        sa.Column("outdoor_humidity_pct", sa.Float(), nullable=True),
        sa.Column("dew_point_c", sa.Float(), nullable=True),
        sa.Column("feels_like_c", sa.Float(), nullable=True),
        sa.Column("vpd_kpa", sa.Float(), nullable=True),
        sa.Column("absolute_pressure_hpa", sa.Float(), nullable=True),
        sa.Column("relative_pressure_hpa", sa.Float(), nullable=True),
        sa.Column("wind_direction_deg", sa.Float(), nullable=True),
        sa.Column("wind_direction_avg10m_deg", sa.Float(), nullable=True),
        sa.Column("wind_speed_ms", sa.Float(), nullable=True),
        sa.Column("wind_gust_ms", sa.Float(), nullable=True),
        sa.Column("daily_max_gust_ms", sa.Float(), nullable=True),
        sa.Column("solar_radiation_wm2", sa.Float(), nullable=True),
        sa.Column("uv_index", sa.Float(), nullable=True),
        sa.Column("rain_rate_mm_h", sa.Float(), nullable=True),
        sa.Column("rain_event_mm", sa.Float(), nullable=True),
        sa.Column("rain_hour_mm", sa.Float(), nullable=True),
        sa.Column("rain_last_24h_mm", sa.Float(), nullable=True),
        sa.Column("rain_day_mm", sa.Float(), nullable=True),
        sa.Column("rain_week_mm", sa.Float(), nullable=True),
        sa.Column("rain_month_mm", sa.Float(), nullable=True),
        sa.Column("rain_year_mm", sa.Float(), nullable=True),
        sa.Column("piezo_rain_mm", sa.Float(), nullable=True),
        sa.Column("battery_voltage", sa.Float(), nullable=True),
        sa.Column("ws90_capacitor_voltage", sa.Float(), nullable=True),
        sa.Column("signal_dbm", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("raw_report_id", name="uq_weather_observations_raw_report_id"),
    )
    op.create_index("ix_weather_observations_gateway_id", "weather_observations", ["gateway_id"])
    op.create_index("ix_weather_observations_observed_at_utc", "weather_observations", ["observed_at_utc"])
    op.create_index(
        "ix_weather_observations_gateway_observed",
        "weather_observations",
        ["gateway_id", "observed_at_utc"],
    )

    for table_name, unique_name, index_name in (
        ("daily_statistics", "uq_daily_statistics_gateway_period", "ix_daily_statistics_gateway_period"),
        ("weekly_statistics", "uq_weekly_statistics_gateway_period", "ix_weekly_statistics_gateway_period"),
    ):
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("gateway_id", sa.Integer(), sa.ForeignKey("gateways.id"), nullable=True),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False),
            sa.Column("outdoor_temperature_mean_c", sa.Float(), nullable=True),
            sa.Column("outdoor_temperature_min_c", sa.Float(), nullable=True),
            sa.Column("outdoor_temperature_max_c", sa.Float(), nullable=True),
            sa.Column("outdoor_humidity_mean_pct", sa.Float(), nullable=True),
            sa.Column("relative_pressure_mean_hpa", sa.Float(), nullable=True),
            sa.Column("wind_gust_max_ms", sa.Float(), nullable=True),
            sa.Column("solar_radiation_max_wm2", sa.Float(), nullable=True),
            sa.Column("uv_index_max", sa.Float(), nullable=True),
            sa.Column("rain_day_max_mm", sa.Float(), nullable=True),
            sa.Column("rain_event_max_mm", sa.Float(), nullable=True),
            sa.Column("rain_last_24h_max_mm", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("gateway_id", "period_start", name=unique_name),
        )
        op.create_index(index_name, table_name, ["gateway_id", "period_start"])

    op.create_table(
        "unknown_fields",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_name", sa.String(length=255), nullable=False),
        sa.Column("sample_value", sa.Text(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalized_mapping", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("field_name", name="uq_unknown_fields_field_name"),
    )
    op.create_index("ix_unknown_fields_field_name", "unknown_fields", ["field_name"])

    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gateway_id", sa.Integer(), sa.ForeignKey("gateways.id"), nullable=True),
        sa.Column("raw_report_id", sa.Integer(), sa.ForeignKey("ecowitt_raw_reports.id"), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ingestion_events_gateway_id", "ingestion_events", ["gateway_id"])
    op.create_index("ix_ingestion_events_raw_report_id", "ingestion_events", ["raw_report_id"])

    op.create_table(
        "data_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gateway_id", sa.Integer(), sa.ForeignKey("gateways.id"), nullable=True),
        sa.Column("gap_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gap_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_reports", sa.Integer(), nullable=True),
        sa.Column("received_reports", sa.Integer(), nullable=True),
        sa.Column("resolved", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("resolution_method", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_data_gaps_gateway_id", "data_gaps", ["gateway_id"])


def downgrade() -> None:
    op.drop_index("ix_data_gaps_gateway_id", table_name="data_gaps")
    op.drop_table("data_gaps")
    op.drop_index("ix_ingestion_events_raw_report_id", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_gateway_id", table_name="ingestion_events")
    op.drop_table("ingestion_events")
    op.drop_index("ix_unknown_fields_field_name", table_name="unknown_fields")
    op.drop_table("unknown_fields")
    op.drop_index("ix_weather_observations_gateway_observed", table_name="weather_observations")
    op.drop_index("ix_weather_observations_observed_at_utc", table_name="weather_observations")
    op.drop_index("ix_weather_observations_gateway_id", table_name="weather_observations")
    op.drop_index("ix_weekly_statistics_gateway_period", table_name="weekly_statistics")
    op.drop_table("weekly_statistics")
    op.drop_index("ix_daily_statistics_gateway_period", table_name="daily_statistics")
    op.drop_table("daily_statistics")
    op.drop_table("weather_observations")
    op.drop_index("ix_ecowitt_raw_reports_gateway_received", table_name="ecowitt_raw_reports")
    op.drop_index("ix_ecowitt_raw_reports_device_timestamp_utc", table_name="ecowitt_raw_reports")
    op.drop_index("ix_ecowitt_raw_reports_received_at_utc", table_name="ecowitt_raw_reports")
    op.drop_index("ix_ecowitt_raw_reports_gateway_id", table_name="ecowitt_raw_reports")
    op.drop_table("ecowitt_raw_reports")
    op.drop_index("ix_gateways_last_seen_at", table_name="gateways")
    op.drop_index("ix_gateways_mac_address", table_name="gateways")
    op.drop_table("gateways")
