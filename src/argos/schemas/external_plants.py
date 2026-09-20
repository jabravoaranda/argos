from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from argos.schemas.plants import PlantUnitRead


ExternalSource = Literal["api", "chatgpt"]


class ExternalErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object] | list[dict[str, object]] | None = None


class ExternalErrorResponse(BaseModel):
    error: ExternalErrorDetail


class ExternalObservationCreate(BaseModel):
    observed_at: datetime
    title: str | None = Field(default=None, min_length=1, max_length=255)
    note: str | None = None
    source: ExternalSource = "api"
    metadata: dict[str, object] | None = None

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a UTC offset.")
        return value


class ExternalObservationRead(BaseModel):
    id: int
    plant_code: str
    observed_at: datetime
    event_type: str
    title: str
    note: str | None
    source: str
    metadata: dict[str, object] | None
    photo_count: int
    created_at: datetime


class ExternalPhotoRead(BaseModel):
    id: int
    field_event_id: int
    plant_code: str
    observed_at: datetime
    note: str | None
    source: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    taken_at: datetime | None
    date_source: str
    metadata: dict[str, object] | None
    content_url: str
    created_at: datetime


class ExternalPlantRead(PlantUnitRead):
    pass
