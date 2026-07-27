"""Add AEMET daily weather tables.

Revision ID: 20260727_0010
Revises: 20260726_0009
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0010"
down_revision: str | None = "20260726_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weather_stations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("municipality", sa.String(length=255), nullable=True),
        sa.Column("province", sa.String(length=255), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("altitude_m", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "external_id", name="uq_weather_stations_provider_external"),
    )
    op.create_index("ix_weather_stations_provider_external", "weather_stations", ["provider", "external_id"])

    op.create_table(
        "weather_daily_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("weather_stations.id"), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("temperature_mean_c", sa.Float(), nullable=True),
        sa.Column("temperature_min_c", sa.Float(), nullable=True),
        sa.Column("temperature_max_c", sa.Float(), nullable=True),
        sa.Column("precipitation_mm", sa.Float(), nullable=True),
        sa.Column("precipitation_trace", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("wind_speed_mean_ms", sa.Float(), nullable=True),
        sa.Column("wind_gust_ms", sa.Float(), nullable=True),
        sa.Column("wind_gust_direction", sa.String(length=32), nullable=True),
        sa.Column("sunshine_hours", sa.Float(), nullable=True),
        sa.Column("pressure_max_hpa", sa.Float(), nullable=True),
        sa.Column("pressure_min_hpa", sa.Float(), nullable=True),
        sa.Column("humidity_mean_pct", sa.Float(), nullable=True),
        sa.Column("humidity_min_pct", sa.Float(), nullable=True),
        sa.Column("humidity_max_pct", sa.Float(), nullable=True),
        sa.Column("quality_flag", sa.String(length=255), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("station_id", "observation_date", name="uq_weather_daily_observations_station_date"),
    )
    op.create_index(
        "ix_weather_daily_observations_station_date",
        "weather_daily_observations",
        ["station_id", "observation_date"],
    )

    op.create_table(
        "aemet_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("weather_stations.id"), nullable=True),
        sa.Column("station_external_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("requested_start", sa.Date(), nullable=False),
        sa.Column("requested_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intervals_json", sa.JSON(), nullable=False),
        sa.Column("records_received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_aemet_sync_runs_station_started", "aemet_sync_runs", ["station_id", "started_at"])
    op.create_index("ix_aemet_sync_runs_status", "aemet_sync_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_aemet_sync_runs_status", table_name="aemet_sync_runs")
    op.drop_index("ix_aemet_sync_runs_station_started", table_name="aemet_sync_runs")
    op.drop_table("aemet_sync_runs")
    op.drop_index("ix_weather_daily_observations_station_date", table_name="weather_daily_observations")
    op.drop_table("weather_daily_observations")
    op.drop_index("ix_weather_stations_provider_external", table_name="weather_stations")
    op.drop_table("weather_stations")
