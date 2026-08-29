from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from argos.api.weather import require_admin_token
from argos.database.session import get_db_session
from argos.domain.plants import DEFAULT_PLANT_PARCEL_NAME, DEFAULT_PLANT_PARCEL_SLUG, PLANT_SPECIES_LABELS, parse_matrix_position_code
from argos.repositories.field_events import FieldEventRepository
from argos.repositories.plants import PlantRepository
from argos.schemas.field_events import FieldEventRead
from argos.schemas.plants import (
    PlantCatalogRead,
    PlantMatrixCellRead,
    PlantMatrixRead,
    PlantPhotoConfirmRead,
    PlantPhotoConfirmRequest,
    PlantPhotoStageItemRead,
    PlantPhotoStageRead,
    PlantPhotoStageRequest,
    PlantUnitCreate,
    PlantUnitRead,
    PlantUnitUpdate,
    plant_unit_read,
)
from argos.models.field_event import FieldEvent, FieldEventPhoto
from argos.services.field_event_photos import (
    FieldEventPhotoInput,
    add_event_photo_item,
    stage_plant_photos,
    thumbnail_data_url,
)
from argos.services.plants import irrigation_line_name_for_row, irrigation_line_slug_for_row, plantation_matrix_layout


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


@router.post("/photos/stage", response_model=PlantPhotoStageRead)
def stage_plant_photo_batch(
    payload: PlantPhotoStageRequest,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> PlantPhotoStageRead:
    try:
        staged = stage_plant_photos(
            session=session,
            photos=[FieldEventPhotoInput(**photo.model_dump()) for photo in payload.photos],
            fallback_date=payload.fallback_taken_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlantPhotoStageRead(
        items=[
            PlantPhotoStageItemRead(
                index=index,
                filename=item.filename,
                content_type=item.content_type,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
                taken_at=item.taken_at,
                date_source=item.date_source,
                detected_code=item.detected_code,
                confidence=item.confidence,
                resolver=item.resolver,
                status=item.status,
                diagnostic=item.diagnostics,
                diagnostics=item.diagnostics,
                plant_id=item.plant_id,
                plant_public_code=item.plant_public_code,
                matrix_position_code=item.matrix_position_code,
                species=item.species,
                species_label=PLANT_SPECIES_LABELS.get(item.species, item.species) if item.species else None,
                irrigation_sector_id=item.irrigation_sector_id,
                duplicate=item.duplicate,
                thumbnail_data_url=thumbnail_data_url(item.data_base64, item.content_type),
            )
            for index, item in enumerate(staged)
        ]
    )


@router.post("/photos/confirm", response_model=PlantPhotoConfirmRead)
def confirm_plant_photo_batch(
    payload: PlantPhotoConfirmRequest,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> PlantPhotoConfirmRead:
    existing_hashes = set(session.scalars(select(FieldEventPhoto.sha256)).all())
    legacy_hashes = set(session.scalars(select(FieldEvent.photo_sha256).where(FieldEvent.photo_sha256.is_not(None))).all())
    photos_by_plant: dict[int, list[Any]] = {}
    skipped_duplicates = 0
    skipped_unassigned = 0
    seen_hashes: set[str] = set()
    for item in payload.items:
        if item.sha256 in existing_hashes or item.sha256 in legacy_hashes or item.sha256 in seen_hashes:
            skipped_duplicates += 1
            continue
        seen_hashes.add(item.sha256)
        if item.plant_id is None:
            skipped_unassigned += 1
            continue
        photos_by_plant.setdefault(item.plant_id, []).append(item)

    event_ids: list[int] = []
    imported_photos = 0
    repository = PlantRepository(session)
    try:
        for plant_id, items in photos_by_plant.items():
            plant = repository.get_plant(plant_id)
            if plant is None:
                skipped_unassigned += len(items)
                continue
            occurred_at = _batch_event_datetime(items, fallback=payload.fallback_taken_at)
            event = FieldEventRepository(session).create(
                {
                    "occurred_at": occurred_at,
                    "event_type": "observation",
                    "title": f"Seguimiento fotográfico {plant.public_code}",
                    "description": f"Lote fotográfico: {len(items)} foto(s).",
                    "zone_slug": None,
                    "tree_reference": plant.public_code,
                    "target_type": "plant",
                    "target_value": plant.public_code,
                    "source": "manual",
                }
            )
            repository.link_event_to_plants(event=event, plant_ids=[plant.id])
            first_photo = None
            for item in items:
                photo = add_event_photo_item(
                    event=event,
                    photo=FieldEventPhotoInput(
                        filename=item.filename,
                        content_type=item.content_type,
                        data_base64=item.data_base64,
                    ),
                    date_source=item.date_source,
                    taken_at=item.taken_at,
                    detected_code=item.detected_code,
                    resolver_confidence=item.confidence,
                )
                session.add(photo)
                first_photo = first_photo or photo
                imported_photos += 1
                existing_hashes.add(item.sha256)
            if first_photo is not None:
                event.photo_storage_path = first_photo.storage_path
                event.photo_mime_type = first_photo.mime_type
                event.photo_original_filename = first_photo.original_filename
                event.photo_size_bytes = first_photo.size_bytes
                event.photo_sha256 = first_photo.sha256
                event.photo_taken_at = first_photo.taken_at
            event_ids.append(event.id)
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlantPhotoConfirmRead(
        created_events=len(event_ids),
        imported_photos=imported_photos,
        skipped_duplicates=skipped_duplicates,
        skipped_unassigned=skipped_unassigned,
        event_ids=event_ids,
    )


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
    line_slug = payload.irrigation_line_slug or irrigation_line_slug_for_row(matrix_row)
    line = repository.upsert_irrigation_line(
        parcel_id=parcel.id,
        slug=line_slug,
        name=irrigation_line_name_for_row(matrix_row),
        sector_id=payload.irrigation_sector_id,
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
    matrix_row = plant.matrix_row
    if "matrix_position_code" in values:
        matrix_row, _matrix_column = parse_matrix_position_code(values["matrix_position_code"])
    if line_slug or "matrix_position_code" in values:
        line = repository.upsert_irrigation_line(
            parcel_id=plant.parcel_id,
            slug=line_slug or irrigation_line_slug_for_row(matrix_row),
            name=irrigation_line_name_for_row(matrix_row),
            sector_id=values.get("irrigation_sector_id", plant.irrigation_sector_id),
        )
        values["irrigation_line_id"] = line.id
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
    return [_plant_field_event_read(event) for event in repository.plant_history(plant_id=plant_id, limit=limit)]


def _plant_field_event_read(event: Any) -> FieldEventRead:
    read = FieldEventRead.model_validate(event)
    read.plant_unit_ids = [link.plant_unit_id for link in getattr(event, "plant_links", [])]
    if event.photo_storage_path:
        read.photo_url = f"/api/v1/field-events/{event.id}/photo"
    return read


def _batch_event_datetime(items: list[Any], *, fallback: Any) -> Any:
    dated = [item.taken_at for item in items if item.taken_at is not None]
    if dated:
        return min(dated)
    if fallback is not None:
        return fallback
    raise HTTPException(status_code=422, detail="Las fotos sin fecha necesitan una fecha de lote.")
