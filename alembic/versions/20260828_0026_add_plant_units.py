"""Add persistent plant units and matrix layout.

Revision ID: 20260828_0026
Revises: 20260828_0025
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260828_0026"
down_revision: str | None = "20260828_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plant_parcels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("matrix_rows", sa.Integer(), server_default="12", nullable=False),
        sa.Column("matrix_columns", sa.Integer(), server_default="12", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("matrix_rows = 12", name="ck_plant_parcels_matrix_rows_12"),
        sa.CheckConstraint("matrix_columns = 12", name="ck_plant_parcels_matrix_columns_12"),
        sa.UniqueConstraint("slug", name="uq_plant_parcels_slug"),
    )
    op.create_index(op.f("ix_plant_parcels_slug"), "plant_parcels", ["slug"])

    op.create_table(
        "plant_irrigation_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parcel_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sector_id", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "sector_id IS NULL OR sector_id IN ('I', 'II', 'III', 'IV')",
            name="ck_plant_irrigation_lines_sector_id",
        ),
        sa.ForeignKeyConstraint(["parcel_id"], ["plant_parcels.id"]),
        sa.UniqueConstraint("parcel_id", "slug", name="uq_plant_irrigation_lines_parcel_slug"),
    )
    op.create_index(op.f("ix_plant_irrigation_lines_parcel_id"), "plant_irrigation_lines", ["parcel_id"])
    op.create_index(op.f("ix_plant_irrigation_lines_sector_id"), "plant_irrigation_lines", ["sector_id"])
    op.create_index(op.f("ix_plant_irrigation_lines_slug"), "plant_irrigation_lines", ["slug"])

    op.create_table(
        "plant_matrix_cells",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parcel_id", sa.Integer(), nullable=False),
        sa.Column("matrix_row", sa.Integer(), nullable=False),
        sa.Column("matrix_column", sa.Integer(), nullable=False),
        sa.Column("matrix_position_code", sa.String(length=2), nullable=False),
        sa.Column("cell_type", sa.String(length=32), server_default="empty", nullable=False),
        sa.Column("visible_code", sa.String(length=100), nullable=True),
        sa.Column("species_code", sa.String(length=16), nullable=True),
        sa.Column("feature_label", sa.String(length=100), nullable=True),
        sa.Column("displacement_marker", sa.String(length=1), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("matrix_row BETWEEN 1 AND 12", name="ck_plant_matrix_cells_matrix_row"),
        sa.CheckConstraint("matrix_column BETWEEN 1 AND 12", name="ck_plant_matrix_cells_matrix_column"),
        sa.CheckConstraint("cell_type IN ('empty', 'plant', 'infrastructure')", name="ck_plant_matrix_cells_cell_type"),
        sa.CheckConstraint(
            "displacement_marker IS NULL OR displacement_marker IN ('#', 'b')",
            name="ck_plant_matrix_cells_displacement_marker",
        ),
        sa.ForeignKeyConstraint(["parcel_id"], ["plant_parcels.id"]),
        sa.UniqueConstraint("parcel_id", "matrix_row", "matrix_column", name="uq_plant_matrix_cells_parcel_position"),
    )
    op.create_index(op.f("ix_plant_matrix_cells_matrix_position_code"), "plant_matrix_cells", ["matrix_position_code"])
    op.create_index(op.f("ix_plant_matrix_cells_parcel_id"), "plant_matrix_cells", ["parcel_id"])
    op.create_index("ix_plant_matrix_cells_parcel_type", "plant_matrix_cells", ["parcel_id", "cell_type"])

    op.create_table(
        "plant_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_code", sa.String(length=100), nullable=False),
        sa.Column("species", sa.String(length=100), nullable=False),
        sa.Column("variety", sa.String(length=100), nullable=True),
        sa.Column("rootstock", sa.String(length=100), nullable=True),
        sa.Column("parcel_id", sa.Integer(), nullable=False),
        sa.Column("matrix_row", sa.Integer(), nullable=False),
        sa.Column("matrix_column", sa.Integer(), nullable=False),
        sa.Column("matrix_position_code", sa.String(length=2), nullable=False),
        sa.Column("planted_on", sa.Date(), nullable=True),
        sa.Column("planted_on_precision", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("irrigation_sector_id", sa.String(length=8), nullable=True),
        sa.Column("irrigation_line_id", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("matrix_row BETWEEN 1 AND 12", name="ck_plant_units_matrix_row"),
        sa.CheckConstraint("matrix_column BETWEEN 1 AND 12", name="ck_plant_units_matrix_column"),
        sa.CheckConstraint("status IN ('active', 'incident', 'removed', 'replaced')", name="ck_plant_units_status"),
        sa.CheckConstraint(
            "planted_on_precision IN ('exact', 'year_month', 'year', 'unknown')",
            name="ck_plant_units_planted_on_precision",
        ),
        sa.CheckConstraint(
            "irrigation_sector_id IS NULL OR irrigation_sector_id IN ('I', 'II', 'III', 'IV')",
            name="ck_plant_units_irrigation_sector_id",
        ),
        sa.ForeignKeyConstraint(["irrigation_line_id"], ["plant_irrigation_lines.id"]),
        sa.ForeignKeyConstraint(["parcel_id"], ["plant_parcels.id"]),
        sa.UniqueConstraint("parcel_id", "matrix_row", "matrix_column", name="uq_plant_units_parcel_matrix_position"),
        sa.UniqueConstraint("public_code", name="uq_plant_units_public_code"),
    )
    op.create_index(op.f("ix_plant_units_irrigation_line_id"), "plant_units", ["irrigation_line_id"])
    op.create_index(op.f("ix_plant_units_irrigation_sector_id"), "plant_units", ["irrigation_sector_id"])
    op.create_index(op.f("ix_plant_units_matrix_position_code"), "plant_units", ["matrix_position_code"])
    op.create_index(op.f("ix_plant_units_parcel_id"), "plant_units", ["parcel_id"])
    op.create_index("ix_plant_units_parcel_sector", "plant_units", ["parcel_id", "irrigation_sector_id"])
    op.create_index("ix_plant_units_parcel_status", "plant_units", ["parcel_id", "status"])
    op.create_index(op.f("ix_plant_units_public_code"), "plant_units", ["public_code"])

    op.create_table(
        "field_event_plant_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_event_id", sa.Integer(), nullable=False),
        sa.Column("plant_unit_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["field_event_id"], ["field_events.id"]),
        sa.ForeignKeyConstraint(["plant_unit_id"], ["plant_units.id"]),
        sa.UniqueConstraint("field_event_id", "plant_unit_id", name="uq_field_event_plant_units_event_plant"),
    )
    op.create_index(op.f("ix_field_event_plant_units_field_event_id"), "field_event_plant_units", ["field_event_id"])
    op.create_index(op.f("ix_field_event_plant_units_plant_unit_id"), "field_event_plant_units", ["plant_unit_id"])

    op.add_column("field_events", sa.Column("target_type", sa.String(length=32), nullable=True))
    op.add_column("field_events", sa.Column("target_value", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_field_events_target_type"), "field_events", ["target_type"])


def downgrade() -> None:
    op.drop_index(op.f("ix_field_events_target_type"), table_name="field_events")
    op.drop_column("field_events", "target_value")
    op.drop_column("field_events", "target_type")
    op.drop_index(op.f("ix_field_event_plant_units_plant_unit_id"), table_name="field_event_plant_units")
    op.drop_index(op.f("ix_field_event_plant_units_field_event_id"), table_name="field_event_plant_units")
    op.drop_table("field_event_plant_units")
    op.drop_index(op.f("ix_plant_units_public_code"), table_name="plant_units")
    op.drop_index("ix_plant_units_parcel_status", table_name="plant_units")
    op.drop_index("ix_plant_units_parcel_sector", table_name="plant_units")
    op.drop_index(op.f("ix_plant_units_parcel_id"), table_name="plant_units")
    op.drop_index(op.f("ix_plant_units_matrix_position_code"), table_name="plant_units")
    op.drop_index(op.f("ix_plant_units_irrigation_sector_id"), table_name="plant_units")
    op.drop_index(op.f("ix_plant_units_irrigation_line_id"), table_name="plant_units")
    op.drop_table("plant_units")
    op.drop_index("ix_plant_matrix_cells_parcel_type", table_name="plant_matrix_cells")
    op.drop_index(op.f("ix_plant_matrix_cells_parcel_id"), table_name="plant_matrix_cells")
    op.drop_index(op.f("ix_plant_matrix_cells_matrix_position_code"), table_name="plant_matrix_cells")
    op.drop_table("plant_matrix_cells")
    op.drop_index(op.f("ix_plant_irrigation_lines_slug"), table_name="plant_irrigation_lines")
    op.drop_index(op.f("ix_plant_irrigation_lines_sector_id"), table_name="plant_irrigation_lines")
    op.drop_index(op.f("ix_plant_irrigation_lines_parcel_id"), table_name="plant_irrigation_lines")
    op.drop_table("plant_irrigation_lines")
    op.drop_index(op.f("ix_plant_parcels_slug"), table_name="plant_parcels")
    op.drop_table("plant_parcels")
