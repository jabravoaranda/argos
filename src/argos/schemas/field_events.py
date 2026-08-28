from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from argos.domain.field_events import FIELD_EVENT_SOURCES, FIELD_EVENT_TYPE_LABELS, FIELD_ZONE_LABELS
from argos.models.plants import FIELD_EVENT_TARGET_TYPES


class FieldEventCatalogItemRead(BaseModel):
    slug: str
    label: str


class FieldEventBase(BaseModel):
    occurred_at: datetime
    event_type: str
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    zone_slug: str | None = None
    tree_reference: str | None = Field(default=None, max_length=255)
    target_type: str | None = None
    target_value: str | None = Field(default=None, max_length=255)
    plant_unit_ids: list[int] = Field(default_factory=list)
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=64)
    source: str = "manual"

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in FIELD_EVENT_TYPE_LABELS:
            raise ValueError("Unknown field event type.")
        return value

    @field_validator("zone_slug")
    @classmethod
    def validate_zone_slug(cls, value: str | None) -> str | None:
        if value is not None and value not in FIELD_ZONE_LABELS:
            raise ValueError("Unknown field zone.")
        return value

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if value not in FIELD_EVENT_SOURCES:
            raise ValueError("Unknown field event source.")
        return value

    @field_validator("target_type")
    @classmethod
    def validate_target_type(cls, value: str | None) -> str | None:
        if value is not None and value not in FIELD_EVENT_TARGET_TYPES:
            raise ValueError("Unknown field event target type.")
        return value

    @field_validator("title", "description", "zone_slug", "tree_reference", "target_type", "target_value", "unit", mode="before")
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def validate_quantity_unit(self) -> "FieldEventBase":
        if self.unit and self.quantity is None:
            raise ValueError("unit requires quantity.")
        return self


class FieldEventPhotoUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1)

    @field_validator("filename", "content_type", "data_base64", mode="before")
    @classmethod
    def strip_required_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class FieldEventCreate(FieldEventBase):
    source: str = "manual"
    photo: FieldEventPhotoUpload | None = None

    @field_validator("source")
    @classmethod
    def validate_manual_source(cls, value: str) -> str:
        if value != "manual":
            raise ValueError("Only manual field events can be created here.")
        return value


class FieldEventUpdate(BaseModel):
    occurred_at: datetime | None = None
    event_type: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    zone_slug: str | None = None
    tree_reference: str | None = Field(default=None, max_length=255)
    target_type: str | None = None
    target_value: str | None = Field(default=None, max_length=255)
    plant_unit_ids: list[int] | None = None
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=64)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str | None) -> str | None:
        if value is not None and value not in FIELD_EVENT_TYPE_LABELS:
            raise ValueError("Unknown field event type.")
        return value

    @field_validator("zone_slug")
    @classmethod
    def validate_zone_slug(cls, value: str | None) -> str | None:
        if value is not None and value not in FIELD_ZONE_LABELS:
            raise ValueError("Unknown field zone.")
        return value

    @field_validator("target_type")
    @classmethod
    def validate_target_type(cls, value: str | None) -> str | None:
        if value is not None and value not in FIELD_EVENT_TARGET_TYPES:
            raise ValueError("Unknown field event target type.")
        return value

    @field_validator("title", "description", "zone_slug", "tree_reference", "target_type", "target_value", "unit", mode="before")
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

class FieldEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    event_type: str
    title: str
    description: str | None
    zone_slug: str | None
    tree_reference: str | None
    target_type: str | None
    target_value: str | None
    plant_unit_ids: list[int] = Field(default_factory=list)
    quantity: float | None
    unit: str | None
    photo_storage_path: str | None
    photo_mime_type: str | None
    photo_original_filename: str | None
    photo_size_bytes: int | None
    photo_sha256: str | None
    photo_taken_at: datetime | None
    photo_url: str | None = None
    source: str
    created_at: datetime
    updated_at: datetime | None


class FieldEventCatalogRead(BaseModel):
    event_types: list[FieldEventCatalogItemRead]
    zones: list[FieldEventCatalogItemRead]
