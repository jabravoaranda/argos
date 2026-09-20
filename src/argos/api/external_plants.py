from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from argos.api.external_auth import ExternalPrincipal, require_external_read, require_external_write
from argos.api.external_errors import ExternalApiError
from argos.database.session import get_db_session
from argos.models.field_event import ExternalApiRequest, FieldEvent, FieldEventPhoto
from argos.models.plants import FieldEventPlantUnit, PlantUnit
from argos.repositories.field_events import FieldEventRepository
from argos.repositories.plants import PlantRepository
from argos.schemas.external_plants import (
    ExternalErrorResponse,
    ExternalObservationCreate,
    ExternalObservationRead,
    ExternalPhotoRead,
    ExternalPlantRead,
)
from argos.schemas.plants import plant_unit_read
from argos.services.data_layout import resolve_storage_path
from argos.services.field_event_photos import FieldEventPhotoInput, add_event_photo_item, decode_photo


router = APIRouter(prefix="/api/v1/external/plants", tags=["external-plant-tracking"])
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ExternalErrorResponse},
    403: {"model": ExternalErrorResponse},
    404: {"model": ExternalErrorResponse},
    409: {"model": ExternalErrorResponse},
    422: {"model": ExternalErrorResponse},
    503: {"model": ExternalErrorResponse},
    500: {"model": ExternalErrorResponse},
}


@router.get("/{plant_code}", response_model=ExternalPlantRead, responses=ERROR_RESPONSES)
def get_external_plant(
    plant_code: str,
    _principal: ExternalPrincipal = Depends(require_external_read),
    session: Session = Depends(get_db_session),
) -> ExternalPlantRead:
    plant = _plant_or_404(session, plant_code)
    return ExternalPlantRead.model_validate(plant_unit_read(plant))


@router.get(
    "/{plant_code}/observations",
    response_model=list[ExternalObservationRead],
    responses=ERROR_RESPONSES,
)
def list_external_observations(
    plant_code: str,
    limit: int = Query(default=100, ge=1, le=500),
    _principal: ExternalPrincipal = Depends(require_external_read),
    session: Session = Depends(get_db_session),
) -> list[ExternalObservationRead]:
    plant = _plant_or_404(session, plant_code)
    events = PlantRepository(session).plant_history(plant_id=plant.id, limit=limit)
    return [_observation_read(event, plant.public_code) for event in events]


@router.post(
    "/{plant_code}/observations",
    response_model=ExternalObservationRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_external_observation(
    plant_code: str,
    payload: ExternalObservationCreate,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: ExternalPrincipal = Depends(require_external_write),
    session: Session = Depends(get_db_session),
) -> ExternalObservationRead:
    key = _idempotency_key(idempotency_key)
    plant = _plant_or_404(session, plant_code)
    operation = "create_observation"
    request_hash = _request_hash({"plant_code": plant.public_code, **payload.model_dump(mode="json")})
    replay = _idempotency_replay(session, principal, key, operation, request_hash)
    if replay is not None:
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = replay.response_status
        return ExternalObservationRead.model_validate(replay.response_payload)

    event = FieldEventRepository(session).create(
        {
            "occurred_at": payload.observed_at.astimezone(UTC),
            "event_type": "observation",
            "title": payload.title or f"Observación externa {plant.public_code}",
            "description": payload.note,
            "tree_reference": plant.public_code,
            "target_type": "plant",
            "target_value": plant.public_code,
            "source": payload.source,
            "metadata_json": payload.metadata,
        }
    )
    PlantRepository(session).link_event_to_plants(event=event, plant_ids=[plant.id])
    result = _observation_read(event, plant.public_code)
    _record_request(session, principal, key, operation, request_hash, payload.source, result, event.id)
    session.commit()
    return result


@router.post(
    "/{plant_code}/photos",
    response_model=ExternalPhotoRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
async def create_external_photo(
    plant_code: str,
    response: Response,
    photo: Annotated[UploadFile, File(description="Original JPG, PNG or WebP file")],
    observed_at: Annotated[datetime, Form(description="Observation time with UTC offset")],
    note: Annotated[str | None, Form()] = None,
    source: Annotated[Literal["api", "chatgpt"], Form()] = "api",
    metadata: Annotated[str | None, Form(description="Optional JSON object")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: ExternalPrincipal = Depends(require_external_write),
    session: Session = Depends(get_db_session),
) -> ExternalPhotoRead:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ExternalApiError(status_code=422, code="invalid_observed_at", message="observed_at must include a UTC offset.")
    key = _idempotency_key(idempotency_key)
    plant = _plant_or_404(session, plant_code)
    metadata_value = _metadata_object(metadata)
    content = await photo.read()
    filename = photo.filename or "photo"
    photo_input = FieldEventPhotoInput(
        filename=filename,
        content_type=photo.content_type or "",
        data_base64=base64.b64encode(content).decode("ascii"),
    )
    try:
        content_type, validated_content = decode_photo(photo_input)
    except ValueError as exc:
        code = "unsupported_photo_format" if "JPG, PNG o WebP" in str(exc) else "invalid_photo"
        raise ExternalApiError(status_code=422, code=code, message=str(exc)) from exc
    try:
        with Image.open(BytesIO(validated_content)) as image:
            image.verify()
    except Exception as exc:
        raise ExternalApiError(
            status_code=422,
            code="invalid_photo",
            message="The uploaded file is not a valid JPG, PNG or WebP image.",
        ) from exc
    checksum = hashlib.sha256(validated_content).hexdigest()
    operation = "create_photo"
    request_hash = _request_hash(
        {
            "plant_code": plant.public_code,
            "observed_at": observed_at.isoformat(),
            "note": note,
            "source": source,
            "metadata": metadata_value,
            "filename": filename,
            "content_type": content_type,
            "sha256": checksum,
        }
    )
    replay = _idempotency_replay(session, principal, key, operation, request_hash)
    if replay is not None:
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = replay.response_status
        return ExternalPhotoRead.model_validate(replay.response_payload)
    if session.scalar(select(FieldEventPhoto.id).where(FieldEventPhoto.sha256 == checksum)) is not None:
        raise ExternalApiError(
            status_code=409,
            code="duplicate_photo",
            message="This photo is already stored in ARGOS. Retry with the original Idempotency-Key to replay its response.",
            details={"sha256": checksum},
        )
    if session.scalar(select(FieldEvent.id).where(FieldEvent.photo_sha256 == checksum)) is not None:
        raise ExternalApiError(
            status_code=409,
            code="duplicate_photo",
            message="This photo is already stored in ARGOS. Retry with the original Idempotency-Key to replay its response.",
            details={"sha256": checksum},
        )

    event = FieldEventRepository(session).create(
        {
            "occurred_at": observed_at.astimezone(UTC),
            "event_type": "observation",
            "title": f"Seguimiento fotográfico {plant.public_code}",
            "description": note,
            "tree_reference": plant.public_code,
            "target_type": "plant",
            "target_value": plant.public_code,
            "source": source,
            "metadata_json": metadata_value,
        }
    )
    PlantRepository(session).link_event_to_plants(event=event, plant_ids=[plant.id])
    photo_item = add_event_photo_item(
        event=event,
        photo=photo_input,
        date_source="unknown",
        metadata=metadata_value,
    )
    session.add(photo_item)
    event.photo_storage_path = photo_item.storage_path
    event.photo_mime_type = photo_item.mime_type
    event.photo_original_filename = photo_item.original_filename
    event.photo_size_bytes = photo_item.size_bytes
    event.photo_sha256 = photo_item.sha256
    event.photo_taken_at = photo_item.taken_at
    event.occurred_at = observed_at.astimezone(UTC)
    session.flush()
    result = _photo_read(photo_item, event, plant.public_code)
    _record_request(session, principal, key, operation, request_hash, source, result, event.id)
    session.commit()
    return result


@router.get("/{plant_code}/photos", response_model=list[ExternalPhotoRead], responses=ERROR_RESPONSES)
def list_external_photos(
    plant_code: str,
    limit: int = Query(default=100, ge=1, le=500),
    _principal: ExternalPrincipal = Depends(require_external_read),
    session: Session = Depends(get_db_session),
) -> list[ExternalPhotoRead]:
    plant = _plant_or_404(session, plant_code)
    statement = (
        select(FieldEventPhoto, FieldEvent)
        .join(FieldEvent, FieldEvent.id == FieldEventPhoto.field_event_id)
        .join(FieldEventPlantUnit, FieldEventPlantUnit.field_event_id == FieldEvent.id)
        .where(FieldEventPlantUnit.plant_unit_id == plant.id)
        .order_by(FieldEvent.occurred_at.desc(), FieldEventPhoto.id.desc())
        .limit(limit)
    )
    return [_photo_read(photo, event, plant.public_code) for photo, event in session.execute(statement).all()]


@router.get("/{plant_code}/photos/{photo_id}/content", responses=ERROR_RESPONSES)
def get_external_photo_content(
    plant_code: str,
    photo_id: int,
    _principal: ExternalPrincipal = Depends(require_external_read),
    session: Session = Depends(get_db_session),
) -> FileResponse:
    plant = _plant_or_404(session, plant_code)
    statement = (
        select(FieldEventPhoto)
        .join(FieldEventPlantUnit, FieldEventPlantUnit.field_event_id == FieldEventPhoto.field_event_id)
        .where(FieldEventPhoto.id == photo_id, FieldEventPlantUnit.plant_unit_id == plant.id)
    )
    photo = session.scalar(statement)
    if photo is None:
        raise ExternalApiError(status_code=404, code="photo_not_found", message="Photo not found for this plant.")
    path = resolve_storage_path(photo.storage_path)
    if not path.is_file():
        raise ExternalApiError(status_code=404, code="photo_file_not_found", message="The photo record exists but its file is missing.")
    return FileResponse(path, media_type=photo.mime_type, filename=photo.original_filename)


def _plant_or_404(session: Session, plant_code: str) -> PlantUnit:
    normalized = plant_code.strip()
    plant = PlantRepository(session).get_plant_by_public_code(normalized)
    if plant is None:
        raise ExternalApiError(
            status_code=404,
            code="plant_not_found",
            message="Plant not found.",
            details={"plant_code": normalized},
        )
    return plant


def _idempotency_key(value: str | None) -> str:
    key = (value or "").strip()
    if not key or len(key) > 255:
        raise ExternalApiError(
            status_code=422,
            code="invalid_idempotency_key",
            message="Idempotency-Key is required and must contain at most 255 characters.",
        )
    return key


def _request_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _idempotency_replay(
    session: Session,
    principal: ExternalPrincipal,
    key: str,
    operation: str,
    request_hash: str,
) -> ExternalApiRequest | None:
    record = session.scalar(
        select(ExternalApiRequest).where(
            ExternalApiRequest.token_fingerprint == principal.token_fingerprint,
            ExternalApiRequest.idempotency_key == key,
        )
    )
    if record is None:
        return None
    if record.operation != operation or record.request_hash != request_hash:
        raise ExternalApiError(
            status_code=409,
            code="idempotency_key_conflict",
            message="The Idempotency-Key has already been used with a different request.",
        )
    return record


def _record_request(
    session: Session,
    principal: ExternalPrincipal,
    key: str,
    operation: str,
    request_hash: str,
    source: str,
    result: ExternalObservationRead | ExternalPhotoRead,
    resource_id: int,
) -> None:
    session.add(
        ExternalApiRequest(
            token_fingerprint=principal.token_fingerprint,
            idempotency_key=key,
            operation=operation,
            request_hash=request_hash,
            source=source,
            response_status=status.HTTP_201_CREATED,
            response_payload=result.model_dump(mode="json"),
            resource_type="field_event",
            resource_id=resource_id,
        )
    )


def _metadata_object(value: str | None) -> dict[str, object] | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ExternalApiError(status_code=422, code="invalid_metadata", message="metadata must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ExternalApiError(status_code=422, code="invalid_metadata", message="metadata must be a JSON object.")
    return parsed


def _observation_read(event: FieldEvent, plant_code: str) -> ExternalObservationRead:
    return ExternalObservationRead(
        id=event.id,
        plant_code=plant_code,
        observed_at=_as_utc(event.occurred_at),
        event_type=event.event_type,
        title=event.title,
        note=event.description,
        source=event.source,
        metadata=event.metadata_json,
        photo_count=len(event.photos),
        created_at=event.created_at,
    )


def _photo_read(photo: FieldEventPhoto, event: FieldEvent, plant_code: str) -> ExternalPhotoRead:
    return ExternalPhotoRead(
        id=photo.id,
        field_event_id=event.id,
        plant_code=plant_code,
        observed_at=_as_utc(event.occurred_at),
        note=event.description,
        source=event.source,
        original_filename=photo.original_filename,
        mime_type=photo.mime_type,
        size_bytes=photo.size_bytes,
        sha256=photo.sha256,
        taken_at=_as_utc(photo.taken_at) if photo.taken_at is not None else None,
        date_source=photo.date_source,
        metadata=photo.metadata_json,
        content_url=f"/api/v1/external/plants/{plant_code}/photos/{photo.id}/content",
        created_at=photo.created_at,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
