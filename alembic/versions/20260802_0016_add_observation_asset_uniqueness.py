"""Add database-level idempotence constraints.

Revision ID: 20260802_0016
Revises: 20260802_0015
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0016"
down_revision: str | None = "20260802_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _assert_no_duplicates(
        name="weather_observations(gateway_id, observed_at_utc, source)",
        query=sa.text(
            """
            SELECT gateway_id, observed_at_utc, source, count(*) AS duplicate_count, group_concat(id) AS ids
            FROM weather_observations
            GROUP BY gateway_id, observed_at_utc, source
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 20
            """
        ),
    )
    _assert_no_duplicates(
        name="satellite_assets(observation_id, asset_type)",
        query=sa.text(
            """
            SELECT observation_id, asset_type, count(*) AS duplicate_count, group_concat(id) AS ids
            FROM satellite_assets
            GROUP BY observation_id, asset_type
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 20
            """
        ),
    )

    with op.batch_alter_table("weather_observations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_weather_observations_gateway_observed_source",
            ["gateway_id", "observed_at_utc", "source"],
        )
    with op.batch_alter_table("satellite_assets") as batch_op:
        batch_op.create_unique_constraint(
            "uq_satellite_assets_observation_type",
            ["observation_id", "asset_type"],
        )


def downgrade() -> None:
    with op.batch_alter_table("satellite_assets") as batch_op:
        batch_op.drop_constraint("uq_satellite_assets_observation_type", type_="unique")
    with op.batch_alter_table("weather_observations") as batch_op:
        batch_op.drop_constraint("uq_weather_observations_gateway_observed_source", type_="unique")


def _assert_no_duplicates(*, name: str, query: sa.TextClause) -> None:
    rows = [dict(row._mapping) for row in op.get_bind().execute(query).all()]
    if rows:
        raise RuntimeError(f"Cannot add unique constraint for {name}; duplicate groups found: {rows}")
