"""Add sync cursors.

Revision ID: 20260802_0020
Revises: 20260802_0019
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0020"
down_revision: str | None = "20260802_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("cursor_type", sa.String(length=64), nullable=False),
        sa.Column("cursor_value_json", sa.JSON(), nullable=False),
        sa.Column("last_successful_run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id"), nullable=True),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_id", "scope", "scope_key", name="uq_sync_cursors_source_scope_key"),
    )
    op.create_index("ix_sync_cursors_source_id", "sync_cursors", ["source_id"])
    op.create_index("ix_sync_cursors_source_scope", "sync_cursors", ["source_id", "scope"])
    op.create_index("ix_sync_cursors_last_successful_run_id", "sync_cursors", ["last_successful_run_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_cursors_last_successful_run_id", table_name="sync_cursors")
    op.drop_index("ix_sync_cursors_source_scope", table_name="sync_cursors")
    op.drop_index("ix_sync_cursors_source_id", table_name="sync_cursors")
    op.drop_table("sync_cursors")
