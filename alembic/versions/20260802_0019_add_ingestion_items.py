"""Add ingestion items.

Revision ID: 20260802_0019
Revises: 20260802_0018
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0019"
down_revision: str | None = "20260802_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id"), nullable=False),
        sa.Column("item_key", sa.String(length=512), nullable=False),
        sa.Column("item_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source_external_id", sa.String(length=512), nullable=True),
        sa.Column("requested_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inserted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rejected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("run_id", "item_key", name="uq_ingestion_items_run_item_key"),
    )
    op.create_index("ix_ingestion_items_run_id", "ingestion_items", ["run_id"])
    op.create_index("ix_ingestion_items_run_status", "ingestion_items", ["run_id", "status"])
    op.create_index("ix_ingestion_items_source_external_id", "ingestion_items", ["source_external_id"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_items_source_external_id", table_name="ingestion_items")
    op.drop_index("ix_ingestion_items_run_status", table_name="ingestion_items")
    op.drop_index("ix_ingestion_items_run_id", table_name="ingestion_items")
    op.drop_table("ingestion_items")
