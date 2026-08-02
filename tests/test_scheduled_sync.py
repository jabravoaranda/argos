from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from argos.config.settings import Settings
from argos.database.base import Base
from argos.services.scheduled_sync import run_daily_data_sync_once


def test_daily_data_sync_skips_unconfigured_sources() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(
        argos_admin_token="admin",
        ecowitt_ingest_token="ingest",
        aemet_api_key=None,
        ecowitt_cloud_application_key=None,
        ecowitt_cloud_api_key=None,
        ecowitt_cloud_mac=None,
        argos_satellite_enabled=False,
    )

    with Session(engine) as session:
        result = run_daily_data_sync_once(
            session=session,
            settings=settings,
            now=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        )

    tasks = {task.name: task for task in result.tasks}
    assert tasks["ecowitt"].status == "skipped"
    assert tasks["aemet"].status == "skipped"
    assert tasks["satellite"].status == "skipped"
