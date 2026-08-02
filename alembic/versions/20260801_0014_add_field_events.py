"""Add field events diary.

Revision ID: 20260801_0014
Revises: 20260801_0013
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260801_0014"
down_revision: str | None = "20260801_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("zone_slug", sa.String(length=100), nullable=True),
        sa.Column("tree_reference", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), server_default="manual", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_field_events_occurred_at", "field_events", ["occurred_at"])
    op.create_index("ix_field_events_event_type", "field_events", ["event_type"])
    op.create_index("ix_field_events_zone_slug", "field_events", ["zone_slug"])


def downgrade() -> None:
    op.drop_index("ix_field_events_zone_slug", table_name="field_events")
    op.drop_index("ix_field_events_event_type", table_name="field_events")
    op.drop_index("ix_field_events_occurred_at", table_name="field_events")
    op.drop_table("field_events")
