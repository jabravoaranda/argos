"""Add gateway aliases.

Revision ID: 20260710_0007
Revises: 20260710_0006
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0007"
down_revision: str | None = "20260710_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gateway_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gateway_id", sa.Integer(), sa.ForeignKey("gateways.id"), nullable=False),
        sa.Column("alias_type", sa.String(length=64), nullable=False),
        sa.Column("alias_value", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("alias_type", "alias_value", name="uq_gateway_aliases_type_value"),
    )
    op.create_index("ix_gateway_aliases_gateway_id", "gateway_aliases", ["gateway_id"])


def downgrade() -> None:
    op.drop_index("ix_gateway_aliases_gateway_id", table_name="gateway_aliases")
    op.drop_table("gateway_aliases")
