"""Add irrigation sector volume attributions.

Revision ID: 20260828_0025
Revises: 20260827_0024
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260828_0025"
down_revision: str | None = "20260827_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "argos_node_flowmeter_minutes",
        sa.Column("unassigned_volume_l", sa.Float(), server_default="0", nullable=False),
    )
    op.create_table(
        "argos_irrigation_sector_minute_attributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flowmeter_minute_id", sa.Integer(), nullable=False),
        sa.Column("node_url", sa.String(length=1024), nullable=False),
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sector_id", sa.String(length=8), nullable=False),
        sa.Column("volume_l", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["flowmeter_minute_id"], ["argos_node_flowmeter_minutes.id"]),
        sa.UniqueConstraint(
            "flowmeter_minute_id",
            "sector_id",
            name="uq_argos_irrigation_sector_minute_attr_minute_sector",
        ),
    )
    op.create_index(
        "ix_argos_irrigation_sector_minute_attr_sector_window",
        "argos_irrigation_sector_minute_attributions",
        ["sector_id", "window_start_utc"],
    )
    op.create_index(
        op.f("ix_argos_irrigation_sector_minute_attributions_window_start_utc"),
        "argos_irrigation_sector_minute_attributions",
        ["window_start_utc"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_argos_irrigation_sector_minute_attributions_window_start_utc"),
        table_name="argos_irrigation_sector_minute_attributions",
    )
    op.drop_index(
        "ix_argos_irrigation_sector_minute_attr_sector_window",
        table_name="argos_irrigation_sector_minute_attributions",
    )
    op.drop_table("argos_irrigation_sector_minute_attributions")
    op.drop_column("argos_node_flowmeter_minutes", "unassigned_volume_l")
