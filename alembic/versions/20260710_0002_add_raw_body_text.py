"""Add raw body text to Ecowitt reports.

Revision ID: 20260710_0002
Revises: 20260710_0001
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0002"
down_revision: str | None = "20260710_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ecowitt_raw_reports", sa.Column("raw_body_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ecowitt_raw_reports", "raw_body_text")
