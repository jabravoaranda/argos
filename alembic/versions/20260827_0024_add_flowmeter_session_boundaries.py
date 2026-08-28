"""Add explicit flowmeter session boundaries.

Revision ID: 20260827_0024
Revises: 20260802_0023
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260827_0024"
down_revision: str | None = "20260802_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("argos_node_flowmeter_sessions", sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=True))
    op.add_column("argos_node_flowmeter_sessions", sa.Column("duration_s", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_sessions", sa.Column("volume_l", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_sessions", sa.Column("pulse_count_start", sa.Integer(), nullable=True))
    op.add_column("argos_node_flowmeter_sessions", sa.Column("pulse_count_end", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_argos_node_flowmeter_sessions_started_at_utc"),
        "argos_node_flowmeter_sessions",
        ["started_at_utc"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_argos_node_flowmeter_sessions_started_at_utc"), table_name="argos_node_flowmeter_sessions")
    op.drop_column("argos_node_flowmeter_sessions", "pulse_count_end")
    op.drop_column("argos_node_flowmeter_sessions", "pulse_count_start")
    op.drop_column("argos_node_flowmeter_sessions", "volume_l")
    op.drop_column("argos_node_flowmeter_sessions", "duration_s")
    op.drop_column("argos_node_flowmeter_sessions", "started_at_utc")
