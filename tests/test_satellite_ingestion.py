from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from argos.config.settings import Settings
from argos.database.base import Base
from argos.integrations.copernicus import StacItem
from argos.models.satellite import SatelliteObservation
from argos.services.satellite_ingestion import SatelliteIngestionService, parse_statistical_response


POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-3.7, 37.1], [-3.699, 37.1], [-3.699, 37.101], [-3.7, 37.101], [-3.7, 37.1]]],
}


class FakeSatelliteAdapter:
    def __init__(self) -> None:
        self.statistics_calls = 0

    def search_sentinel2_items(self, **_kwargs: Any) -> list[StacItem]:
        return [
            StacItem(
                id="S2A_TEST_ITEM",
                acquisition_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                platform="sentinel-2a",
                collection="sentinel-2-l2a",
                product_type="S2MSI2A",
                cloud_cover=12.0,
                raw={"id": "S2A_TEST_ITEM"},
            )
        ]

    def get_sentinel2_statistics(self, **_kwargs: Any) -> dict[str, Any]:
        self.statistics_calls += 1
        return statistical_payload(sample_count=10, no_data_count=2)


def test_parse_statistical_response_extracts_metrics_and_quality_counts() -> None:
    metrics, valid_fraction, invalid_fraction = parse_statistical_response(
        statistical_payload(sample_count=10, no_data_count=3)
    )

    assert metrics["ndvi"]["mean"] == 0.42
    assert metrics["ndvi"]["median"] == 0.43
    assert metrics["ndvi"]["valid_pixel_count"] == 7
    assert valid_fraction == 0.7
    assert invalid_fraction == 0.30000000000000004


def test_satellite_status_disabled_without_credentials() -> None:
    with in_memory_session() as session:
        settings = Settings(ecowitt_ingest_token="test-token", argos_satellite_enabled=False)
        status = SatelliteIngestionService(session=session, settings=settings).status()

    assert status.status == "disabled"
    assert not status.configured


def test_satellite_backfill_is_idempotent() -> None:
    adapter = FakeSatelliteAdapter()
    settings = Settings(
        ecowitt_ingest_token="test-token",
        argos_satellite_enabled=True,
        copernicus_client_id="client",
        copernicus_client_secret="secret",
        argos_satellite_aoi_geojson=json.dumps(POLYGON),
        argos_satellite_preview_enabled=False,
    )
    with in_memory_session() as session:
        service = SatelliteIngestionService(session=session, settings=settings, adapter=adapter)  # type: ignore[arg-type]
        first = service.backfill(
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
        )
        second = service.backfill(
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
        )
        observation_count = session.scalar(select(func.count()).select_from(SatelliteObservation))

    assert first.processed_count == 1
    assert first.found_count == 1
    assert second.processed_count == 0
    assert second.skipped_count == 1
    assert observation_count == 1
    assert adapter.statistics_calls == 1


def statistical_payload(*, sample_count: int, no_data_count: int) -> dict[str, Any]:
    outputs = {}
    for metric in ("ndvi", "savi", "ndre", "ndmi"):
        outputs[metric] = {
            "bands": {
                "B0": {
                    "stats": {
                        "min": 0.1,
                        "max": 0.8,
                        "mean": 0.42,
                        "stDev": 0.05,
                        "sampleCount": sample_count,
                        "noDataCount": no_data_count,
                        "percentiles": {"10": 0.2, "25": 0.3, "50": 0.43, "75": 0.5, "90": 0.6},
                    }
                }
            }
        }
    return {"data": [{"outputs": outputs}]}


def in_memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
