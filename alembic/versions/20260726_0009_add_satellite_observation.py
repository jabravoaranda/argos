"""Add satellite observation tables.

Revision ID: 20260726_0009
Revises: 20260710_0008
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260726_0009"
down_revision: str | None = "20260710_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "satellite_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("collection", sa.String(length=100), nullable=False),
        sa.Column("spatial_resolution_m", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_satellite_sources_code"),
    )
    op.create_index("ix_satellite_sources_code", "satellite_sources", ["code"])

    op.create_table(
        "satellite_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("geometry_geojson", sa.JSON(), nullable=False),
        sa.Column("geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("crs", sa.String(length=32), server_default="EPSG:4326", nullable=False),
        sa.Column("area_m2", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("geometry_hash", name="uq_satellite_zones_geometry_hash"),
    )
    op.create_index("ix_satellite_zones_name", "satellite_zones", ["name"])
    op.create_index("ix_satellite_zones_geometry_hash", "satellite_zones", ["geometry_hash"])

    op.create_table(
        "satellite_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("satellite_sources.id"), nullable=False),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("satellite_zones.id"), nullable=False),
        sa.Column("external_item_id", sa.String(length=255), nullable=False),
        sa.Column("acquisition_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("platform", sa.String(length=100), nullable=True),
        sa.Column("collection", sa.String(length=100), nullable=False),
        sa.Column("product_type", sa.String(length=100), nullable=True),
        sa.Column("cloud_cover_metadata", sa.Float(), nullable=True),
        sa.Column("valid_pixel_fraction", sa.Float(), nullable=True),
        sa.Column("invalid_pixel_fraction", sa.Float(), nullable=True),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("processing_version", sa.String(length=64), nullable=False),
        sa.Column("geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "source_id",
            "zone_id",
            "external_item_id",
            "processing_version",
            name="uq_satellite_observations_source_zone_item_version",
        ),
    )
    op.create_index("ix_satellite_observations_source_id", "satellite_observations", ["source_id"])
    op.create_index("ix_satellite_observations_zone_id", "satellite_observations", ["zone_id"])
    op.create_index("ix_satellite_observations_quality", "satellite_observations", ["quality_status"])
    op.create_index(
        "ix_satellite_observations_zone_acquisition",
        "satellite_observations",
        ["zone_id", "acquisition_time"],
    )

    op.create_table(
        "satellite_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.Integer(), sa.ForeignKey("satellite_observations.id"), nullable=False),
        sa.Column("metric_code", sa.String(length=32), nullable=False),
        sa.Column("mean", sa.Float(), nullable=True),
        sa.Column("median", sa.Float(), nullable=True),
        sa.Column("minimum", sa.Float(), nullable=True),
        sa.Column("maximum", sa.Float(), nullable=True),
        sa.Column("standard_deviation", sa.Float(), nullable=True),
        sa.Column("percentile_10", sa.Float(), nullable=True),
        sa.Column("percentile_25", sa.Float(), nullable=True),
        sa.Column("percentile_75", sa.Float(), nullable=True),
        sa.Column("percentile_90", sa.Float(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("no_data_count", sa.Integer(), nullable=True),
        sa.Column("valid_pixel_count", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=32), server_default="dimensionless", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("observation_id", "metric_code", name="uq_satellite_metrics_observation_metric"),
    )
    op.create_index("ix_satellite_metrics_observation_id", "satellite_metrics", ["observation_id"])
    op.create_index("ix_satellite_metrics_metric_code", "satellite_metrics", ["metric_code"])

    op.create_table(
        "satellite_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.Integer(), sa.ForeignKey("satellite_observations.id"), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_satellite_assets_observation_id", "satellite_assets", ["observation_id"])
    op.create_index("ix_satellite_assets_asset_type", "satellite_assets", ["asset_type"])
    op.create_index("ix_satellite_assets_checksum_sha256", "satellite_assets", ["checksum_sha256"])


def downgrade() -> None:
    op.drop_index("ix_satellite_assets_checksum_sha256", table_name="satellite_assets")
    op.drop_index("ix_satellite_assets_asset_type", table_name="satellite_assets")
    op.drop_index("ix_satellite_assets_observation_id", table_name="satellite_assets")
    op.drop_table("satellite_assets")
    op.drop_index("ix_satellite_metrics_metric_code", table_name="satellite_metrics")
    op.drop_index("ix_satellite_metrics_observation_id", table_name="satellite_metrics")
    op.drop_table("satellite_metrics")
    op.drop_index("ix_satellite_observations_zone_acquisition", table_name="satellite_observations")
    op.drop_index("ix_satellite_observations_quality", table_name="satellite_observations")
    op.drop_index("ix_satellite_observations_zone_id", table_name="satellite_observations")
    op.drop_index("ix_satellite_observations_source_id", table_name="satellite_observations")
    op.drop_table("satellite_observations")
    op.drop_index("ix_satellite_zones_geometry_hash", table_name="satellite_zones")
    op.drop_index("ix_satellite_zones_name", table_name="satellite_zones")
    op.drop_table("satellite_zones")
    op.drop_index("ix_satellite_sources_code", table_name="satellite_sources")
    op.drop_table("satellite_sources")
