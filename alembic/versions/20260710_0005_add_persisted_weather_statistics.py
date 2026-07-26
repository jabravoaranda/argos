"""Add persisted weather statistics.

Revision ID: 20260710_0005
Revises: 20260710_0004
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0005"
down_revision: str | None = "20260710_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


STATISTIC_COLUMNS = (
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
)


def upgrade() -> None:
    _create_statistics_table_if_missing(
        "daily_statistics",
        "uq_daily_statistics_gateway_period",
        "ix_daily_statistics_gateway_period",
    )
    _create_statistics_table_if_missing(
        "weekly_statistics",
        "uq_weekly_statistics_gateway_period",
        "ix_weekly_statistics_gateway_period",
    )


def downgrade() -> None:
    _drop_table_if_present("weekly_statistics", "ix_weekly_statistics_gateway_period")
    _drop_table_if_present("daily_statistics", "ix_daily_statistics_gateway_period")


def _create_statistics_table_if_missing(table_name: str, unique_name: str, index_name: str) -> None:
    bind = op.get_bind()
    if table_name in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        table_name,
        *[column.copy() for column in STATISTIC_COLUMNS],
        sa.UniqueConstraint("gateway_id", "period_start", name=unique_name),
    )
    op.create_index(index_name, table_name, ["gateway_id", "period_start"])


def _drop_table_if_present(table_name: str, index_name: str) -> None:
    bind = op.get_bind()
    if table_name not in sa.inspect(bind).get_table_names():
        return
    op.drop_index(index_name, table_name=table_name)
    op.drop_table(table_name)
