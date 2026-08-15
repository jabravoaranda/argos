"""Harden Ecowitt observation identity nullability.

Revision ID: 20260802_0023
Revises: 20260802_0022
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0023"
down_revision: str | None = "20260802_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    null_count = op.get_bind().execute(
        sa.text(
            """
            SELECT count(*)
            FROM weather_observations
            WHERE gateway_id IS NULL OR observed_at_utc IS NULL OR source IS NULL
            """
        )
    ).scalar_one()
    if null_count:
        raise RuntimeError(
            "Cannot make Ecowitt observation identity NOT NULL; "
            f"{null_count} rows have NULL gateway_id, observed_at_utc or source."
        )
    with op.batch_alter_table("weather_observations") as batch_op:
        batch_op.alter_column("gateway_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("observed_at_utc", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.alter_column("source", existing_type=sa.String(length=32), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("weather_observations") as batch_op:
        batch_op.alter_column("source", existing_type=sa.String(length=32), nullable=True)
        batch_op.alter_column("observed_at_utc", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column("gateway_id", existing_type=sa.Integer(), nullable=True)
