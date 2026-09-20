"""Add external plant API metadata and request audit records.

Revision ID: 20260920_0030
Revises: 20260829_0029
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260920_0030"
down_revision: str | None = "20260829_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("field_events") as batch_op:
        batch_op.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))
    with op.batch_alter_table("field_event_photos") as batch_op:
        batch_op.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))
    op.create_table(
        "external_api_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token_fingerprint", "idempotency_key", name="uq_external_api_requests_client_key"),
    )
    op.create_index("ix_external_api_requests_created_at", "external_api_requests", ["created_at"])
    op.create_index(
        "ix_external_api_requests_resource",
        "external_api_requests",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_api_requests_resource", table_name="external_api_requests")
    op.drop_index("ix_external_api_requests_created_at", table_name="external_api_requests")
    op.drop_table("external_api_requests")
    with op.batch_alter_table("field_event_photos") as batch_op:
        batch_op.drop_column("metadata_json")
    with op.batch_alter_table("field_events") as batch_op:
        batch_op.drop_column("metadata_json")
