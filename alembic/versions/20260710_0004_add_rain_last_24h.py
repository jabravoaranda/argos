"""Add rolling 24 hour rainfall.

Revision ID: 20260710_0004
Revises: 20260710_0003
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0004"
down_revision: str | None = "20260710_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {existing["name"] for existing in sa.inspect(bind).get_columns("weather_observations")}
    if "rain_last_24h_mm" not in existing_columns:
        op.add_column("weather_observations", sa.Column("rain_last_24h_mm", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {existing["name"] for existing in sa.inspect(bind).get_columns("weather_observations")}
    if "rain_last_24h_mm" in existing_columns:
        op.drop_column("weather_observations", "rain_last_24h_mm")
