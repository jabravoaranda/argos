"""Add source artifacts.

Revision ID: 20260802_0021
Revises: 20260802_0020
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0021"
down_revision: str | None = "20260802_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id"), nullable=True),
        sa.Column("ingestion_item_id", sa.Integer(), sa.ForeignKey("ingestion_items.id"), nullable=True),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("storage_backend", sa.String(length=64), server_default="local_filesystem", nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("immutable", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("regenerable", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("provider_external_id", sa.String(length=512), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_source_artifacts_source_id", "source_artifacts", ["source_id"])
    op.create_index("ix_source_artifacts_run_id", "source_artifacts", ["run_id"])
    op.create_index("ix_source_artifacts_ingestion_item_id", "source_artifacts", ["ingestion_item_id"])
    op.create_index("ix_source_artifacts_source_role", "source_artifacts", ["source_id", "role"])
    op.create_index("ix_source_artifacts_sha256", "source_artifacts", ["sha256"])
    op.create_index("ix_source_artifacts_provider_external_id", "source_artifacts", ["provider_external_id"])


def downgrade() -> None:
    op.drop_index("ix_source_artifacts_provider_external_id", table_name="source_artifacts")
    op.drop_index("ix_source_artifacts_sha256", table_name="source_artifacts")
    op.drop_index("ix_source_artifacts_source_role", table_name="source_artifacts")
    op.drop_index("ix_source_artifacts_ingestion_item_id", table_name="source_artifacts")
    op.drop_index("ix_source_artifacts_run_id", table_name="source_artifacts")
    op.drop_index("ix_source_artifacts_source_id", table_name="source_artifacts")
    op.drop_table("source_artifacts")
