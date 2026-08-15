"""Add ingestion runs.

Revision ID: 20260802_0018
Revises: 20260802_0017
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0018"
down_revision: str | None = "20260802_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("run_uuid", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("requested_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger", sa.String(length=64), nullable=True),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.Column("processing_version", sa.String(length=64), nullable=True),
        sa.Column("parameters_json", sa.JSON(), nullable=True),
        sa.Column("discovered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inserted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rejected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_uuid", name="uq_ingestion_runs_run_uuid"),
    )
    op.create_index("ix_ingestion_runs_source_id", "ingestion_runs", ["source_id"])
    op.create_index("ix_ingestion_runs_source_started", "ingestion_runs", ["source_id", "started_at_utc"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])
    op.create_index("ix_ingestion_runs_started_at_utc", "ingestion_runs", ["started_at_utc"])
    op.create_index("ix_ingestion_runs_finished_at_utc", "ingestion_runs", ["finished_at_utc"])
    op.create_index("ix_ingestion_runs_heartbeat_at_utc", "ingestion_runs", ["heartbeat_at_utc"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_heartbeat_at_utc", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_finished_at_utc", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_started_at_utc", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_status", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_source_started", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_source_id", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
