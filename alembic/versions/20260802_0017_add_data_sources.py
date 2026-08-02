"""Add common data sources.

Revision ID: 20260802_0017
Revises: 20260802_0016
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0017"
down_revision: str | None = "20260802_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INITIAL_SOURCES = (
    ("ecowitt_lan", "Ecowitt LAN", "weather_station", "Ecowitt", {"granularity": "raw_report"}),
    ("ecowitt_cloud", "Ecowitt Cloud", "weather_station", "Ecowitt", {"granularity": "backfill_or_sync"}),
    ("aemet_api", "AEMET OpenData API", "weather_reference", "AEMET", {"granularity": "date_interval"}),
    ("aemet_csv", "AEMET CSV import", "weather_reference", "AEMET", {"granularity": "file"}),
    ("copernicus_sentinel2", "Copernicus Sentinel-2", "satellite", "Copernicus CDSE", {"granularity": "scene"}),
    ("argos_node_flowmeter", "argos-node flowmeter", "controller", "argos-node", {"granularity": "capture_process"}),
    ("manual_field_event", "Manual field event", "manual", None, {"granularity": "event"}),
)


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_data_sources_code"),
    )
    op.create_index("ix_data_sources_code", "data_sources", ["code"])
    op.create_index("ix_data_sources_source_type", "data_sources", ["source_type"])
    _seed_sources()


def downgrade() -> None:
    op.drop_index("ix_data_sources_source_type", table_name="data_sources")
    op.drop_index("ix_data_sources_code", table_name="data_sources")
    op.drop_table("data_sources")


def _seed_sources() -> None:
    data_sources = sa.table(
        "data_sources",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("source_type", sa.String),
        sa.column("provider", sa.String),
        sa.column("configuration_json", sa.JSON),
    )
    bind = op.get_bind()
    for code, name, source_type, provider, configuration_json in INITIAL_SOURCES:
        exists = bind.execute(sa.text("SELECT 1 FROM data_sources WHERE code = :code"), {"code": code}).first()
        if exists is None:
            bind.execute(
                data_sources.insert().values(
                    code=code,
                    name=name,
                    source_type=source_type,
                    provider=provider,
                    configuration_json=configuration_json,
                )
            )
