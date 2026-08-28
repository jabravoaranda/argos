from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from argos.api.weather import require_admin_token
from argos.database.session import get_db_session
from argos.domain.plants import DEFAULT_PLANT_PARCEL_NAME, DEFAULT_PLANT_PARCEL_SLUG, parse_matrix_position_code
from argos.repositories.plants import PlantRepository
from argos.schemas.field_events import FieldEventRead
from argos.schemas.plants import (
    PlantCatalogRead,
    PlantMatrixCellRead,
    PlantMatrixRead,
    PlantUnitCreate,
    PlantUnitRead,
    PlantUnitUpdate,
    plant_unit_read,
)
from argos.services.plants import plantation_matrix_layout


router = APIRouter(prefix="/api/v1/plants", tags=["plants"])


@router.get("/catalog", response_model=PlantCatalogRead)
def plant_catalog() -> PlantCatalogRead:
    return PlantCatalogRead.current()


@router.get("/parcels")
def list_plant_parcels(session: Session = Depends(get_db_session)) -> list[dict[str, Any]]:
    parcels = PlantRepository(session).list_parcels()
    if not parcels:
        return [{"slug": DEFAULT_PLANT_PARCEL_SLUG, "name": DEFAULT_PLANT_PARCEL_NAME, "matrix_rows": 12, "matrix_columns": 12}]
    return [
        {"id": parcel.id, "slug": parcel.slug, "name": parcel.name, "matrix_rows": parcel.matrix_rows, "matrix_columns": parcel.matrix_columns}
        for parcel in parcels
    ]


@router.get("/matrix", response_model=PlantMatrixRead)
def get_plant_matrix(
    parcel_slug: str = DEFAULT_PLANT_PARCEL_SLUG,
    session: Session = Depends(get_db_session),
) -> PlantMatrixRead:
    layout = plantation_matrix_layout(session=session, parcel_slug=parcel_slug)
    return PlantMatrixRead(
        parcel=layout["parcel"],
        row_labels=layout["row_labels"],
        column_labels=layout["column_labels"],
        cells=[
            PlantMatrixCellRead(
                **{
                    **cell,
                    "plant": plant_unit_read(cell["plant"]) if cell.get("plant") is not None else None,
                }
            )
            for cell in layout["cells"]
        ],
    )


@router.get("", response_model=list[PlantUnitRead])
def list_plants(
    parcel_slug: str | None = DEFAULT_PLANT_PARCEL_SLUG,
    status_filter: str | None = Query(default=None, alias="status"),
    species: str | None = None,
    irrigation_sector_id: str | None = None,
    search: str | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> list[PlantUnitRead]:
    plants = PlantRepository(session).list_plants(
        parcel_slug=parcel_slug,
        status=status_filter,
        species=species,
        irrigation_sector_id=irrigation_sector_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [plant_unit_read(plant) for plant in plants]


@router.post("", response_model=PlantUnitRead, status_code=status.HTTP_201_CREATED)
def create_or_update_plant(
    payload: PlantUnitCreate,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> PlantUnitRead:
    repository = PlantRepository(session)
    parcel_name = DEFAULT_PLANT_PARCEL_NAME if payload.parcel_slug == DEFAULT_PLANT_PARCEL_SLUG else payload.parcel_slug
    parcel = repository.upsert_parcel(slug=payload.parcel_slug, name=parcel_name)
    matrix_row, matrix_column = parse_matrix_position_code(payload.matrix_position_code)
    line = (
        repository.get_irrigation_line(parcel_id=parcel.id, slug=payload.irrigation_line_slug)
        if payload.irrigation_line_slug
        else None
    )
    plant, _created = repository.upsert_plant_by_public_code(
        public_code=payload.public_code,
        values={
            "species": payload.species,
            "variety": payload.variety,
            "rootstock": payload.rootstock,
            "parcel_id": parcel.id,
            "matrix_row": matrix_row,
            "matrix_column": matrix_column,
            "matrix_position_code": payload.matrix_position_code,
            "planted_on": payload.planted_on,
            "planted_on_precision": payload.planted_on_precision,
            "status": payload.status,
            "irrigation_sector_id": payload.irrigation_sector_id,
            "irrigation_line_id": line.id if line else None,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "notes": payload.notes,
        },
    )
    session.commit()
    return plant_unit_read(plant)


@router.get("/{plant_id}", response_model=PlantUnitRead)
def get_plant(plant_id: int, session: Session = Depends(get_db_session)) -> PlantUnitRead:
    plant = PlantRepository(session).get_plant(plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail="Plant not found.")
    return plant_unit_read(plant)


@router.patch("/{plant_id}", response_model=PlantUnitRead)
def update_plant(
    plant_id: int,
    payload: PlantUnitUpdate,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> PlantUnitRead:
    repository = PlantRepository(session)
    plant = repository.get_plant(plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail="Plant not found.")
    values = payload.model_dump(exclude_unset=True)
    line_slug = values.pop("irrigation_line_slug", None)
    if line_slug:
        line = repository.get_irrigation_line(parcel_id=plant.parcel_id, slug=line_slug)
        values["irrigation_line_id"] = line.id if line else None
    for key, value in values.items():
        setattr(plant, key, value)
    session.commit()
    return plant_unit_read(plant)


@router.get("/{plant_id}/history", response_model=list[FieldEventRead])
def get_plant_history(
    plant_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[FieldEventRead]:
    repository = PlantRepository(session)
    plant = repository.get_plant(plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail="Plant not found.")
    return [FieldEventRead.model_validate(event) for event in repository.plant_history(plant_id=plant_id, limit=limit)]
