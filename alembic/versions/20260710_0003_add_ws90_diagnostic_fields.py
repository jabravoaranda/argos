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
    op.add_column("weather_observations", sa.Column("wind_direction_avg10m_deg", sa.Float(), nullable=True))
    op.add_column("weather_observations", sa.Column("ws90_capacitor_voltage", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("weather_observations", "ws90_capacitor_voltage")
    op.drop_column("weather_observations", "wind_direction_avg10m_deg")
