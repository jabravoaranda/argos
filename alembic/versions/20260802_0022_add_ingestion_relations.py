"""Add ingestion provenance relations to domain tables.

Revision ID: 20260802_0022
Revises: 20260802_0021
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0022"
down_revision: str | None = "20260802_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_nullable_fk("ecowitt_raw_reports", "ingestion_run_id", "ingestion_runs")
    _add_nullable_fk("ecowitt_cloud_raw_reports", "ingestion_run_id", "ingestion_runs")
    _add_nullable_fk("weather_observations", "ingestion_run_id", "ingestion_runs")
    _add_nullable_fk("aemet_sync_runs", "ingestion_run_id", "ingestion_runs")
    _add_nullable_fk("weather_daily_observations", "ingestion_run_id", "ingestion_runs")
    _add_nullable_fk("weather_daily_observations", "ingestion_item_id", "ingestion_items")
    _add_nullable_fk("satellite_observations", "ingestion_run_id", "ingestion_runs")
    _add_nullable_fk("satellite_observations", "ingestion_item_id", "ingestion_items")
    _add_nullable_fk("satellite_assets", "source_artifact_id", "source_artifacts")
    _add_nullable_fk("argos_node_flowmeter_minutes", "ingestion_run_id", "ingestion_runs")


def downgrade() -> None:
    for table_name, columns in (
        ("argos_node_flowmeter_minutes", ("ingestion_run_id",)),
        ("satellite_assets", ("source_artifact_id",)),
        ("satellite_observations", ("ingestion_item_id", "ingestion_run_id")),
        ("weather_daily_observations", ("ingestion_item_id", "ingestion_run_id")),
        ("aemet_sync_runs", ("ingestion_run_id",)),
        ("weather_observations", ("ingestion_run_id",)),
        ("ecowitt_cloud_raw_reports", ("ingestion_run_id",)),
        ("ecowitt_raw_reports", ("ingestion_run_id",)),
    ):
        for column_name in columns:
            op.drop_index(f"ix_{table_name}_{column_name}", table_name=table_name)
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_constraint(f"fk_{table_name}_{column_name}", type_="foreignkey")
                batch_op.drop_column(column_name)


def _add_nullable_fk(table_name: str, column_name: str, target_table: str) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(sa.Column(column_name, sa.Integer(), nullable=True))
        batch_op.create_foreign_key(f"fk_{table_name}_{column_name}", target_table, [column_name], ["id"])
    op.create_index(f"ix_{table_name}_{column_name}", table_name, [column_name])
