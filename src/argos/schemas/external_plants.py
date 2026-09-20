from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from argos.schemas.plants import PlantUnitRead


ExternalSource = Literal["api", "chatgpt"]
STRUCTURED_FIELD_DESCRIPTION = "List of semantically separated agronomic statements. Omit or send [] when empty."


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
    visual_observations: list[str] = Field(
        default_factory=list,
        description="Directly observed visual facts; no diagnoses or inferences.",
    )
    interpretation: list[str] = Field(
        default_factory=list,
        description="Agronomic interpretation derived from observations.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Suggested actions that have not necessarily been performed.",
    )
    actions_taken: list[str] = Field(
        default_factory=list,
        description="Actions that were actually carried out.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Limits of the observation or interpretation.",
    )
    source: ExternalSource = "api"
    metadata: dict[str, object] | None = None

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a UTC offset.")
        return value

    @field_validator("visual_observations", "interpretation", "recommendations", "actions_taken", "limitations", mode="before")
    @classmethod
    def normalize_lines(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError(STRUCTURED_FIELD_DESCRIPTION)
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Entries must be text.")
            stripped = item.strip()
            if stripped:
                normalized.append(stripped)
        return normalized


class ExternalObservationRead(BaseModel):
    id: int
    plant_code: str
    observed_at: datetime
    event_type: str
    title: str
    note: str | None
    visual_observations: list[str]
    interpretation: list[str]
    recommendations: list[str]
    actions_taken: list[str]
    limitations: list[str]
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
    visual_observations: list[str]
    interpretation: list[str]
    recommendations: list[str]
    actions_taken: list[str]
    limitations: list[str]
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
