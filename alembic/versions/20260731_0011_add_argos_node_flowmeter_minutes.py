"""Add argos-node flowmeter minute aggregates.

Revision ID: 20260731_0011
Revises: 20260727_0010
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260731_0011"
down_revision: str | None = "20260727_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "argos_node_flowmeter_minutes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_url", sa.String(length=1024), nullable=False),
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pulse_count_start", sa.Integer(), nullable=False),
        sa.Column("pulse_count_end", sa.Integer(), nullable=False),
        sa.Column("pulse_delta", sa.Integer(), nullable=False),
        sa.Column("volume_l", sa.Float(), nullable=False),
        sa.Column("avg_flow_l_min", sa.Float(), nullable=False),
        sa.Column("max_flow_l_min", sa.Float(), nullable=False),
        sa.Column("samples_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_url", "window_start_utc", name="uq_argos_node_flowmeter_minutes_node_window"),
    )
    op.create_index(
        "ix_argos_node_flowmeter_minutes_node_window",
        "argos_node_flowmeter_minutes",
        ["node_url", "window_start_utc"],
    )
    op.create_index(
        op.f("ix_argos_node_flowmeter_minutes_window_start_utc"),
        "argos_node_flowmeter_minutes",
        ["window_start_utc"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_argos_node_flowmeter_minutes_window_start_utc"), table_name="argos_node_flowmeter_minutes")
    op.drop_index("ix_argos_node_flowmeter_minutes_node_window", table_name="argos_node_flowmeter_minutes")
    op.drop_table("argos_node_flowmeter_minutes")
