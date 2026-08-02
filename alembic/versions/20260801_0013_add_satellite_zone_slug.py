"""Add stable slug to satellite zones.

Revision ID: 20260801_0013
Revises: 20260801_0012
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260801_0013"
down_revision: str | None = "20260801_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("satellite_zones") as batch_op:
        batch_op.add_column(sa.Column("slug", sa.String(length=100), nullable=True))

    connection = op.get_bind()
    zones = connection.execute(sa.text("SELECT id FROM satellite_zones ORDER BY id")).fetchall()
    used_slugs: set[str] = set()
    for index, row in enumerate(zones):
        slug = "finca_completa" if index == 0 else f"finca_completa_{index + 1}"
        while slug in used_slugs:
            slug = f"{slug}_{index + 1}"
        used_slugs.add(slug)
        connection.execute(sa.text("UPDATE satellite_zones SET slug = :slug WHERE id = :id"), {"slug": slug, "id": row.id})

    with op.batch_alter_table("satellite_zones") as batch_op:
        batch_op.alter_column("slug", existing_type=sa.String(length=100), nullable=False)
        batch_op.drop_constraint("uq_satellite_zones_geometry_hash", type_="unique")
        batch_op.create_unique_constraint("uq_satellite_zones_slug", ["slug"])
        batch_op.create_index("ix_satellite_zones_slug", ["slug"])


def downgrade() -> None:
    with op.batch_alter_table("satellite_zones") as batch_op:
        batch_op.drop_index("ix_satellite_zones_slug")
        batch_op.drop_constraint("uq_satellite_zones_slug", type_="unique")
        batch_op.create_unique_constraint("uq_satellite_zones_geometry_hash", ["geometry_hash"])
        batch_op.drop_column("slug")
