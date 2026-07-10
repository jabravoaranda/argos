"""Add WS90 diagnostic and average wind fields.

Revision ID: 20260710_0003
Revises: 20260710_0002
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0003"
down_revision: str | None = "20260710_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_column_if_missing("weather_observations", sa.Column("wind_direction_avg10m_deg", sa.Float(), nullable=True))
    _add_column_if_missing("weather_observations", sa.Column("ws90_capacitor_voltage", sa.Float(), nullable=True))


def downgrade() -> None:
    _drop_column_if_present("weather_observations", "ws90_capacitor_voltage")
    _drop_column_if_present("weather_observations", "wind_direction_avg10m_deg")


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    existing_columns = {existing["name"] for existing in sa.inspect(bind).get_columns(table_name)}
    if column.name not in existing_columns:
        op.add_column(table_name, column)


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    existing_columns = {existing["name"] for existing in sa.inspect(bind).get_columns(table_name)}
    if column_name in existing_columns:
        op.drop_column(table_name, column_name)
