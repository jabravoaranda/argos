"""Add argos-node flowmeter contract counters and sessions.

Revision ID: 20260802_0015
Revises: 20260801_0014
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0015"
down_revision: str | None = "20260801_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("argos_node_flowmeter_minutes", sa.Column("boot_total_l_start", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("boot_total_l_end", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("total_l_start", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("total_l_end", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("hydrological_year_l_start", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("hydrological_year_l_end", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("session_active_start", sa.Boolean(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("session_active_end", sa.Boolean(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("session_l_start", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("session_l_end", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("last_session_l_start", sa.Float(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("last_session_l_end", sa.Float(), nullable=True))
    op.create_table(
        "argos_node_flowmeter_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_url", sa.String(length=1024), nullable=False),
        sa.Column("closed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_session_l", sa.Float(), nullable=False),
        sa.Column("pulse_count", sa.Integer(), nullable=True),
        sa.Column("total_l", sa.Float(), nullable=True),
        sa.Column("hydrological_year_l", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_url", "closed_at_utc", name="uq_argos_node_flowmeter_sessions_node_closed_at"),
    )
    op.create_index(
        "ix_argos_node_flowmeter_sessions_node_closed_at",
        "argos_node_flowmeter_sessions",
        ["node_url", "closed_at_utc"],
    )
    op.create_index(
        op.f("ix_argos_node_flowmeter_sessions_closed_at_utc"),
        "argos_node_flowmeter_sessions",
        ["closed_at_utc"],
    )
    op.create_table(
        "argos_node_flowmeter_reset_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_url", sa.String(length=1024), nullable=False),
        sa.Column("reset_type", sa.String(length=64), nullable=False),
        sa.Column("administrative_year", sa.Integer(), nullable=False),
        sa.Column("reset_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_url", "reset_type", "administrative_year", name="uq_argos_node_flowmeter_reset_year"),
    )
    op.create_index(
        "ix_argos_node_flowmeter_reset_events_node_type",
        "argos_node_flowmeter_reset_events",
        ["node_url", "reset_type"],
    )
    op.create_index(
        op.f("ix_argos_node_flowmeter_reset_events_reset_at_utc"),
        "argos_node_flowmeter_reset_events",
        ["reset_at_utc"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_argos_node_flowmeter_reset_events_reset_at_utc"), table_name="argos_node_flowmeter_reset_events")
    op.drop_index("ix_argos_node_flowmeter_reset_events_node_type", table_name="argos_node_flowmeter_reset_events")
    op.drop_table("argos_node_flowmeter_reset_events")
    op.drop_index(op.f("ix_argos_node_flowmeter_sessions_closed_at_utc"), table_name="argos_node_flowmeter_sessions")
    op.drop_index("ix_argos_node_flowmeter_sessions_node_closed_at", table_name="argos_node_flowmeter_sessions")
    op.drop_table("argos_node_flowmeter_sessions")
    op.drop_column("argos_node_flowmeter_minutes", "last_session_l_end")
    op.drop_column("argos_node_flowmeter_minutes", "last_session_l_start")
    op.drop_column("argos_node_flowmeter_minutes", "session_l_end")
    op.drop_column("argos_node_flowmeter_minutes", "session_l_start")
    op.drop_column("argos_node_flowmeter_minutes", "session_active_end")
    op.drop_column("argos_node_flowmeter_minutes", "session_active_start")
    op.drop_column("argos_node_flowmeter_minutes", "hydrological_year_l_end")
    op.drop_column("argos_node_flowmeter_minutes", "hydrological_year_l_start")
    op.drop_column("argos_node_flowmeter_minutes", "total_l_end")
    op.drop_column("argos_node_flowmeter_minutes", "total_l_start")
    op.drop_column("argos_node_flowmeter_minutes", "boot_total_l_end")
    op.drop_column("argos_node_flowmeter_minutes", "boot_total_l_start")
