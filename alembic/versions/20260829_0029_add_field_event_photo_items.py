"""Add per-photo field event metadata.

Revision ID: 20260829_0029
Revises: 20260829_0028
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260829_0029"
down_revision: str | None = "20260829_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_event_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_event_id", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_source", sa.String(length=32), nullable=False),
        sa.Column("detected_code", sa.String(length=100), nullable=True),
        sa.Column("resolver_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["field_event_id"], ["field_events.id"]),
        sa.UniqueConstraint("sha256", name="uq_field_event_photos_sha256"),
    )
    op.create_index(op.f("ix_field_event_photos_field_event_id"), "field_event_photos", ["field_event_id"])
    op.create_index(op.f("ix_field_event_photos_sha256"), "field_event_photos", ["sha256"])


def downgrade() -> None:
    op.drop_index(op.f("ix_field_event_photos_sha256"), table_name="field_event_photos")
    op.drop_index(op.f("ix_field_event_photos_field_event_id"), table_name="field_event_photos")
    op.drop_table("field_event_photos")
