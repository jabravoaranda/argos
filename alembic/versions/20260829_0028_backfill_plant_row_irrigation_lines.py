"""Backfill plant irrigation lines from matrix rows.

Revision ID: 20260829_0028
Revises: 20260828_0027
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260829_0028"
down_revision: str | None = "20260828_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MATRIX_DIGITS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "A", "B", "C")


def upgrade() -> None:
    connection = op.get_bind()
    parcels = connection.exec_driver_sql("SELECT id FROM plant_parcels").fetchall()
    for parcel in parcels:
        parcel_id = parcel[0]
        for index, label in enumerate(MATRIX_DIGITS, start=1):
            slug = f"fila-{label.lower()}"
            connection.execute(
                sa.text(
                    """
                INSERT INTO plant_irrigation_lines (parcel_id, slug, name, sector_id)
                SELECT :parcel_id, :slug, :name, NULL
                WHERE NOT EXISTS (
                    SELECT 1 FROM plant_irrigation_lines
                    WHERE parcel_id = :parcel_id AND slug = :slug
                )
                """,
                ),
                {"parcel_id": parcel_id, "slug": slug, "name": f"Fila {label}"},
            )
            connection.execute(
                sa.text(
                    """
                UPDATE plant_units
                SET irrigation_line_id = (
                    SELECT id
                    FROM plant_irrigation_lines
                    WHERE plant_irrigation_lines.parcel_id = plant_units.parcel_id
                    AND plant_irrigation_lines.slug = :slug
                )
                WHERE parcel_id = :parcel_id
                AND matrix_row = :matrix_row
                AND irrigation_line_id IS NULL
                """,
                ),
                {"slug": slug, "parcel_id": parcel_id, "matrix_row": index},
            )


def downgrade() -> None:
    # Preserve operational line assignments: the upgrade cannot distinguish
    # rows it created from matching rows that already existed.
    pass
