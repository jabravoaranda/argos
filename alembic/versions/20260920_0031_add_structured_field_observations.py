"""Add structured agronomic observation fields.

Revision ID: 20260920_0031
Revises: 20260920_0030
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260920_0031"
down_revision: str | None = "20260920_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


STRUCTURED_COLUMNS = (
    "visual_observations",
    "interpretation",
    "recommendations",
    "actions_taken",
    "limitations",
)


def upgrade() -> None:
    with op.batch_alter_table("field_events") as batch_op:
        for column in STRUCTURED_COLUMNS:
            batch_op.add_column(sa.Column(column, sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("field_events") as batch_op:
        for column in reversed(STRUCTURED_COLUMNS):
            batch_op.drop_column(column)
