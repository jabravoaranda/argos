"""Add stable station identity.

Revision ID: 20260710_0008
Revises: 20260710_0007
Create Date: 2026-07-10
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0008"
down_revision: str | None = "20260710_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATION_SLUG = "tomillar"


def upgrade() -> None:
    op.create_table(
        "stations",
        sa.Column("uuid", sa.String(length=36), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_stations_slug"),
        sa.UniqueConstraint("code", name="uq_stations_code"),
    )
    op.create_index("ix_stations_slug", "stations", ["slug"])
    op.create_index("ix_stations_code", "stations", ["code"])

    station_uuid = str(uuid.uuid4())
    stations = sa.table(
        "stations",
        sa.column("uuid", sa.String),
        sa.column("slug", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("metadata_json", sa.JSON),
    )
    op.bulk_insert(
        stations,
        [
            {
                "uuid": station_uuid,
                "slug": STATION_SLUG,
                "code": STATION_SLUG,
                "name": "Tomillar",
                "metadata_json": {"identity_scope": "physical_site"},
            }
        ],
    )

    for table_name in (
        "gateways",
        "ecowitt_raw_reports",
        "ecowitt_cloud_raw_reports",
        "weather_observations",
        "daily_statistics",
        "weekly_statistics",
        "ingestion_events",
        "data_gaps",
    ):
        _add_station_uuid(table_name)
        op.execute(sa.text(f"UPDATE {table_name} SET station_uuid = :station_uuid").bindparams(station_uuid=station_uuid))
        op.create_index(f"ix_{table_name}_station_uuid", table_name, ["station_uuid"])


def downgrade() -> None:
    for table_name in (
        "data_gaps",
        "weekly_statistics",
        "daily_statistics",
        "ingestion_events",
        "weather_observations",
        "ecowitt_cloud_raw_reports",
        "ecowitt_raw_reports",
        "gateways",
    ):
        op.drop_index(f"ix_{table_name}_station_uuid", table_name=table_name)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(f"fk_{table_name}_station_uuid", type_="foreignkey")
            batch_op.drop_column("station_uuid")

    op.drop_index("ix_stations_code", table_name="stations")
    op.drop_index("ix_stations_slug", table_name="stations")
    op.drop_table("stations")


def _add_station_uuid(table_name: str) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(sa.Column("station_uuid", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(f"fk_{table_name}_station_uuid", "stations", ["station_uuid"], ["uuid"])
