from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from argos.api.weather import require_admin_token
from argos.database.session import get_db_session
from argos.domain.field_events import FIELD_EVENT_TYPE_LABELS, FIELD_EVENT_TYPES, FIELD_ZONE_LABELS, FIELD_ZONES
from argos.repositories.field_events import FieldEventRepository
from argos.repositories.plants import PlantRepository
from argos.schemas.field_events import (
    FieldEventCatalogItemRead,
    FieldEventCatalogRead,
    FieldEventCreate,
    FieldEventRead,
    FieldEventUpdate,
)
from argos.services.data_layout import resolve_storage_path
from argos.services.field_event_photos import FieldEventPhotoInput, attach_field_event_photo

router = APIRouter(prefix="/api/v1/field-events", tags=["field-events"])

CSV_COLUMNS = [
    ("occurred_at", "Fecha y hora"),
    ("event_type_label", "Tipo"),
    ("title", "Título"),
    ("zone_label", "Zona"),
    ("tree_reference", "Árbol/fila"),
    ("quantity", "Cantidad"),
    ("unit", "Unidad"),
    ("description", "Descripción"),
    ("source", "Origen"),
]


@router.get("/catalog", response_model=FieldEventCatalogRead)
def field_event_catalog() -> FieldEventCatalogRead:
    return FieldEventCatalogRead(
        event_types=[FieldEventCatalogItemRead(slug=item.slug, label=item.label) for item in FIELD_EVENT_TYPES],
        zones=[FieldEventCatalogItemRead(slug=item.slug, label=item.label) for item in FIELD_ZONES],
    )


@router.get("", response_model=list[FieldEventRead])
def list_field_events(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    event_type: str | None = None,
    zone_slug: str | None = None,
    search: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> list[FieldEventRead]:
    events = FieldEventRepository(session).list(
        start=start,
        end=end,
        event_type=event_type,
        zone_slug=zone_slug,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [_field_event_read(event) for event in events]


@router.get("/export.csv")
def export_field_events_csv(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    event_type: str | None = None,
    zone_slug: str | None = None,
    search: str | None = None,
    session: Session = Depends(get_db_session),
) -> Response:
    events = FieldEventRepository(session).list(
        start=start,
        end=end,
        event_type=event_type,
        zone_slug=zone_slug,
        search=search,
        limit=1000,
        offset=0,
    )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[label for _key, label in CSV_COLUMNS], lineterminator="\n")
    writer.writeheader()
    for event in events:
        row = _event_export_row(event)
        writer.writerow({label: row.get(key) for key, label in CSV_COLUMNS})
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="argos_diario_campo.csv"'},
    )


@router.post("", response_model=FieldEventRead, status_code=status.HTTP_201_CREATED)
def create_field_event(
    payload: FieldEventCreate,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> FieldEventRead:
    values = payload.model_dump()
    plant_unit_ids = values.pop("plant_unit_ids", [])
    photo = values.pop("photo", None)
    _validate_quantity_unit(values.get("quantity"), values.get("unit"))
    event = FieldEventRepository(session).create(values)
    if plant_unit_ids:
        PlantRepository(session).link_event_to_plants(event=event, plant_ids=plant_unit_ids)
    if photo is not None:
        try:
            attach_field_event_photo(event, FieldEventPhotoInput(**photo))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return _field_event_read(event)


@router.get("/{event_id}", response_model=FieldEventRead)
def get_field_event(event_id: int, session: Session = Depends(get_db_session)) -> FieldEventRead:
    event = FieldEventRepository(session).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Field event not found.")
    return _field_event_read(event)


@router.get("/{event_id}/photo")
def get_field_event_photo(event_id: int, session: Session = Depends(get_db_session)) -> FileResponse:
    event = FieldEventRepository(session).get(event_id)
    if event is None or not event.photo_storage_path:
        raise HTTPException(status_code=404, detail="Field event photo not found.")
    path = resolve_storage_path(event.photo_storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Field event photo file not found.")
    return FileResponse(
        path,
        media_type=event.photo_mime_type or "application/octet-stream",
        filename=event.photo_original_filename or path.name,
    )


@router.patch("/{event_id}", response_model=FieldEventRead)
def update_field_event(
    event_id: int,
    payload: FieldEventUpdate,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> FieldEventRead:
    repository = FieldEventRepository(session)
    event = repository.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Field event not found.")
    values = payload.model_dump(exclude_unset=True)
    plant_unit_ids = values.pop("plant_unit_ids", None)
    quantity = values.get("quantity", event.quantity)
    unit = values.get("unit", event.unit)
    _validate_quantity_unit(quantity, unit)
    event = repository.update(event, values)
    if plant_unit_ids is not None:
        PlantRepository(session).link_event_to_plants(event=event, plant_ids=plant_unit_ids)
    session.commit()
    return _field_event_read(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field_event(
    event_id: int,
    _admin: None = Depends(require_admin_token),
    session: Session = Depends(get_db_session),
) -> None:
    repository = FieldEventRepository(session)
    event = repository.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Field event not found.")
    repository.delete(event)
    session.commit()


def _validate_quantity_unit(quantity: Any, unit: Any) -> None:
    if unit and quantity is None:
        raise HTTPException(status_code=422, detail="unit requires quantity.")


def _event_export_row(event: Any) -> dict[str, Any]:
    return {
        "occurred_at": event.occurred_at.isoformat(),
        "event_type_label": FIELD_EVENT_TYPE_LABELS.get(event.event_type, event.event_type),
        "title": event.title,
        "zone_label": FIELD_ZONE_LABELS.get(event.zone_slug, event.zone_slug) if event.zone_slug else "",
        "tree_reference": event.tree_reference or "",
        "quantity": event.quantity if event.quantity is not None else "",
        "unit": event.unit or "",
        "description": event.description or "",
        "source": event.source,
    }


def _field_event_read(event: Any) -> FieldEventRead:
    read = FieldEventRead.model_validate(event)
    read.plant_unit_ids = [link.plant_unit_id for link in getattr(event, "plant_links", [])]
    if event.photo_storage_path:
        read.photo_url = f"/api/v1/field-events/{event.id}/photo"
    return read
