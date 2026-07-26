"""Add Ecowitt Cloud backfill tables.

Revision ID: 20260710_0006
Revises: 20260710_0005
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0006"
down_revision: str | None = "20260710_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecowitt_cloud_raw_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gateway_id", sa.Integer(), sa.ForeignKey("gateways.id"), nullable=True),
        sa.Column("requested_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("api_version", sa.String(length=32), nullable=True),
        sa.Column("parser_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("payload_hash", name="uq_ecowitt_cloud_raw_reports_payload_hash"),
    )
    op.create_index("ix_ecowitt_cloud_raw_reports_gateway_id", "ecowitt_cloud_raw_reports", ["gateway_id"])
    op.create_index("ix_ecowitt_cloud_raw_reports_observed_at_utc", "ecowitt_cloud_raw_reports", ["observed_at_utc"])
    op.create_index(
        "ix_ecowitt_cloud_raw_reports_gateway_observed",
        "ecowitt_cloud_raw_reports",
        ["gateway_id", "observed_at_utc"],
    )

    with op.batch_alter_table("weather_observations") as batch_op:
        batch_op.add_column(sa.Column("cloud_raw_report_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(length=32), server_default="DIRECT", nullable=False))
        batch_op.alter_column("raw_report_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(
            "fk_weather_observations_cloud_raw_report_id",
            "ecowitt_cloud_raw_reports",
            ["cloud_raw_report_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_weather_observations_cloud_raw_report_id",
            ["cloud_raw_report_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("weather_observations") as batch_op:
        batch_op.drop_constraint("uq_weather_observations_cloud_raw_report_id", type_="unique")
        batch_op.drop_constraint("fk_weather_observations_cloud_raw_report_id", type_="foreignkey")
        batch_op.alter_column("raw_report_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("source")
        batch_op.drop_column("cloud_raw_report_id")
    op.drop_index("ix_ecowitt_cloud_raw_reports_gateway_observed", table_name="ecowitt_cloud_raw_reports")
    op.drop_index("ix_ecowitt_cloud_raw_reports_observed_at_utc", table_name="ecowitt_cloud_raw_reports")
    op.drop_index("ix_ecowitt_cloud_raw_reports_gateway_id", table_name="ecowitt_cloud_raw_reports")
    op.drop_table("ecowitt_cloud_raw_reports")
