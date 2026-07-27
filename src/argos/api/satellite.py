from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from argos.api.weather import require_admin_token
from argos.config.settings import Settings, get_settings
from argos.database.session import get_db_session
from argos.repositories.satellite import SatelliteRepository
from argos.schemas.satellite import (
    SatelliteIngestionRead,
    SatelliteExportRow,
    SatelliteObservationRead,
    SatelliteSourceRead,
    SatelliteStatusRead,
    SatelliteTimeseriesPoint,
    SatelliteTimeseriesRead,
    SatelliteZoneRead,
)
from argos.services.satellite_indices import PROCESSING_VERSION
from argos.services.satellite_ingestion import SatelliteIngestionService

router = APIRouter(prefix="/api/v1/satellite", tags=["satellite"])

EXPORT_COLUMNS = [
    "acquisition_time",
    "zone_name",
    "metric_code",
    "mean",
    "median",
    "minimum",
    "maximum",
    "standard_deviation",
    "percentile_10",
    "percentile_25",
    "percentile_75",
    "percentile_90",
    "valid_pixel_fraction",
    "cloud_cover_metadata",
    "quality_status",
    "processing_version",
]


@router.get("/status", response_model=SatelliteStatusRead)
def satellite_status(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SatelliteStatusRead:
    return SatelliteStatusRead.model_validate(
        SatelliteIngestionService(session=session, settings=settings).status(), from_attributes=True
    )


@router.get("/sources", response_model=list[SatelliteSourceRead])
def satellite_sources(session: Session = Depends(get_db_session)) -> list[SatelliteSourceRead]:
    return [SatelliteSourceRead.model_validate(source) for source in SatelliteRepository(session).sources()]


@router.get("/zones", response_model=list[SatelliteZoneRead])
def satellite_zones(session: Session = Depends(get_db_session)) -> list[SatelliteZoneRead]:
    return [SatelliteZoneRead.model_validate(zone) for zone in SatelliteRepository(session).zones()]


@router.get("/bounds")
def satellite_bounds(
    zone_id: int | None = None,
    quality_status: str | None = None,
    session: Session = Depends(get_db_session),
) -> dict[str, str | None]:
    first, last = SatelliteRepository(session).observation_bounds(zone_id=zone_id, quality_status=quality_status)
    return {
        "first_date": first.date().isoformat() if first else None,
        "last_date": last.date().isoformat() if last else None,
    }


@router.get("/observations", response_model=list[SatelliteObservationRead])
def satellite_observations(
    zone_id: int | None = None,
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    quality_status: str | None = None,
    session: Session = Depends(get_db_session),
) -> list[SatelliteObservationRead]:
    observations = SatelliteRepository(session).observations(
        zone_id=zone_id,
        start=start,
        end=end,
        quality_status=quality_status,
    )
    return [SatelliteObservationRead.model_validate(observation) for observation in observations]


@router.get("/observations/{observation_id}", response_model=SatelliteObservationRead)
def satellite_observation(observation_id: int, session: Session = Depends(get_db_session)) -> SatelliteObservationRead:
    observation = SatelliteRepository(session).observation(observation_id)
    if observation is None:
        raise HTTPException(status_code=404, detail="Satellite observation not found.")
    return SatelliteObservationRead.model_validate(observation)


@router.get("/timeseries", response_model=SatelliteTimeseriesRead)
def satellite_timeseries(
    zone_id: int | None = None,
    metric: str = "ndvi",
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    quality_status: str | None = None,
    session: Session = Depends(get_db_session),
) -> SatelliteTimeseriesRead:
    repository = SatelliteRepository(session)
    observations = repository.observations(zone_id=zone_id, start=start, end=end, quality_status=quality_status)
    selected_zone = observations[0].zone if observations else None
    points = []
    for observation in observations:
        metric_record = next((item for item in observation.metrics if item.metric_code == metric), None)
        if metric_record is None:
            continue
        points.append(
            SatelliteTimeseriesPoint(
                acquisition_time=observation.acquisition_time,
                mean=metric_record.mean,
                median=metric_record.median,
                p25=metric_record.percentile_25,
                p75=metric_record.percentile_75,
                valid_pixel_fraction=observation.valid_pixel_fraction,
                quality_status=observation.quality_status,
            )
        )
    return SatelliteTimeseriesRead(
        zone=SatelliteZoneRead.model_validate(selected_zone) if selected_zone else None,
        metric=metric,
        processing_version=PROCESSING_VERSION,
        points=points,
    )


@router.get("/latest", response_model=SatelliteObservationRead | None)
def latest_satellite_observation(
    zone_id: int | None = None,
    session: Session = Depends(get_db_session),
) -> SatelliteObservationRead | None:
    observation = SatelliteRepository(session).latest_observation(zone_id=zone_id)
    if observation is None:
        return None
    return SatelliteObservationRead.model_validate(observation)


@router.get("/export.json", response_model=list[SatelliteExportRow])
def export_satellite_json(
    zone_id: int | None = None,
    metric: str | None = None,
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    quality_status: str | None = None,
    session: Session = Depends(get_db_session),
) -> list[SatelliteExportRow]:
    rows = build_satellite_export_rows(
        session=session,
        zone_id=zone_id,
        metric=metric,
        start=start,
        end=end,
        quality_status=quality_status,
    )
    return [SatelliteExportRow(**row) for row in rows]


@router.get("/export.csv")
def export_satellite_csv(
    zone_id: int | None = None,
    metric: str | None = None,
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    quality_status: str | None = None,
    session: Session = Depends(get_db_session),
) -> Response:
    rows = build_satellite_export_rows(
        session=session,
        zone_id=zone_id,
        metric=metric,
        start=start,
        end=end,
        quality_status=quality_status,
    )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        csv_row = dict(row)
        csv_row["acquisition_time"] = row["acquisition_time"].isoformat()
        writer.writerow(csv_row)
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="argos_satellite_export.csv"'},
    )


@router.get("/assets/{asset_id}")
def satellite_asset(asset_id: int, session: Session = Depends(get_db_session)) -> FileResponse:
    asset = SatelliteRepository(session).asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Satellite asset not found.")
    path = Path(asset.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Satellite asset file is missing.")
    return FileResponse(path, media_type=asset.mime_type, filename=path.name)


@router.post("/update", response_model=SatelliteIngestionRead)
def update_satellite(
    zone: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SatelliteIngestionRead:
    result = SatelliteIngestionService(session=session, settings=settings).update(zone_name=zone, force=force, dry_run=dry_run)
    return SatelliteIngestionRead.model_validate(result, from_attributes=True)


@router.post("/backfill", response_model=SatelliteIngestionRead)
def backfill_satellite(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    zone: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SatelliteIngestionRead:
    result = SatelliteIngestionService(session=session, settings=settings).backfill(
        start=start,
        end=end,
        zone_name=zone,
        force=force,
        dry_run=dry_run,
    )
    return SatelliteIngestionRead.model_validate(result, from_attributes=True)


def build_satellite_export_rows(
    *,
    session: Session,
    zone_id: int | None,
    metric: str | None,
    start: datetime | None,
    end: datetime | None,
    quality_status: str | None,
) -> list[dict]:
    observations = SatelliteRepository(session).observations(
        zone_id=zone_id,
        start=start,
        end=end,
        quality_status=quality_status,
    )
    rows = []
    for observation in observations:
        for metric_record in observation.metrics:
            if metric is not None and metric_record.metric_code != metric:
                continue
            rows.append(
                {
                    "acquisition_time": observation.acquisition_time,
                    "zone_name": observation.zone.name,
                    "metric_code": metric_record.metric_code,
                    "mean": metric_record.mean,
                    "median": metric_record.median,
                    "minimum": metric_record.minimum,
                    "maximum": metric_record.maximum,
                    "standard_deviation": metric_record.standard_deviation,
                    "percentile_10": metric_record.percentile_10,
                    "percentile_25": metric_record.percentile_25,
                    "percentile_75": metric_record.percentile_75,
                    "percentile_90": metric_record.percentile_90,
                    "valid_pixel_fraction": observation.valid_pixel_fraction,
                    "cloud_cover_metadata": observation.cloud_cover_metadata,
                    "quality_status": observation.quality_status,
                    "processing_version": observation.processing_version,
                }
            )
    return rows
