"""Add relay 1 state aggregates to flowmeter minutes.

Revision ID: 20260801_0012
Revises: 20260731_0011
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260801_0012"
down_revision: str | None = "20260731_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("argos_node_flowmeter_minutes", sa.Column("relay1_state_start", sa.Boolean(), nullable=True))
    op.add_column("argos_node_flowmeter_minutes", sa.Column("relay1_state_end", sa.Boolean(), nullable=True))
    op.add_column(
        "argos_node_flowmeter_minutes",
        sa.Column("relay1_open_samples_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("argos_node_flowmeter_minutes", sa.Column("relay1_open_fraction", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("argos_node_flowmeter_minutes", "relay1_open_fraction")
    op.drop_column("argos_node_flowmeter_minutes", "relay1_open_samples_count")
    op.drop_column("argos_node_flowmeter_minutes", "relay1_state_end")
    op.drop_column("argos_node_flowmeter_minutes", "relay1_state_start")
