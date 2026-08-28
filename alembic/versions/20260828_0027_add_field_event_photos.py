"""Add field event photo metadata.

Revision ID: 20260828_0027
Revises: 20260828_0026
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260828_0027"
down_revision: str | None = "20260828_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("field_events", sa.Column("photo_storage_path", sa.String(length=500), nullable=True))
    op.add_column("field_events", sa.Column("photo_mime_type", sa.String(length=100), nullable=True))
    op.add_column("field_events", sa.Column("photo_original_filename", sa.String(length=255), nullable=True))
    op.add_column("field_events", sa.Column("photo_size_bytes", sa.Integer(), nullable=True))
    op.add_column("field_events", sa.Column("photo_sha256", sa.String(length=64), nullable=True))
    op.add_column("field_events", sa.Column("photo_taken_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("field_events", "photo_taken_at")
    op.drop_column("field_events", "photo_sha256")
    op.drop_column("field_events", "photo_size_bytes")
    op.drop_column("field_events", "photo_original_filename")
    op.drop_column("field_events", "photo_mime_type")
    op.drop_column("field_events", "photo_storage_path")
