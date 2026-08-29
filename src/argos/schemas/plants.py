from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from argos.domain.plants import (
    IRRIGATION_SECTOR_CATALOG,
    MATRIX_DIGITS,
    PLANT_SPECIES_CATALOG,
    PLANT_SPECIES_LABELS,
    PLANT_STATUS_CATALOG,
    PLANT_STATUS_LABELS,
    parse_matrix_position_code,
)
from argos.models.plants import IRRIGATION_SECTOR_IDS, PLANTING_DATE_PRECISIONS, PLANT_STATUSES


class PlantCatalogItemRead(BaseModel):
    slug: str
    label: str


class PlantCatalogRead(BaseModel):
    statuses: list[PlantCatalogItemRead]
    species: list[PlantCatalogItemRead]
    irrigation_sectors: list[PlantCatalogItemRead]
    matrix_digits: list[str]

    @classmethod
    def current(cls) -> "PlantCatalogRead":
        return cls(
            statuses=[PlantCatalogItemRead(slug=item.slug, label=item.label) for item in PLANT_STATUS_CATALOG],
            species=[PlantCatalogItemRead(slug=item.slug, label=item.label) for item in PLANT_SPECIES_CATALOG],
            irrigation_sectors=[PlantCatalogItemRead(slug=item.slug, label=item.label) for item in IRRIGATION_SECTOR_CATALOG],
            matrix_digits=list(MATRIX_DIGITS),
        )


class PlantParcelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    slug: str
    name: str
    matrix_rows: int
    matrix_columns: int


class PlantUnitBase(BaseModel):
    public_code: str = Field(min_length=1, max_length=100)
    species: str = Field(min_length=1, max_length=100)
    variety: str | None = Field(default=None, max_length=100)
    rootstock: str | None = Field(default=None, max_length=100)
    parcel_slug: str = Field(default="tomillar", max_length=100)
    matrix_position_code: str = Field(min_length=2, max_length=2)
    planted_on: date | None = None
    planted_on_precision: str = "unknown"
    status: str = "active"
    irrigation_sector_id: str | None = None
    irrigation_line_slug: str | None = Field(default=None, max_length=100)
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None

    @field_validator("public_code", "species", "parcel_slug", "matrix_position_code", mode="before")
    @classmethod
    def strip_required_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("variety", "rootstock", "irrigation_sector_id", "irrigation_line_slug", "notes", mode="before")
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("matrix_position_code")
    @classmethod
    def validate_position(cls, value: str) -> str:
        parse_matrix_position_code(value)
        return value.upper()

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in PLANT_STATUSES:
            raise ValueError("Unknown plant status.")
        return value

    @field_validator("planted_on_precision")
    @classmethod
    def validate_precision(cls, value: str) -> str:
        if value not in PLANTING_DATE_PRECISIONS:
            raise ValueError("Unknown planting date precision.")
        return value

    @field_validator("irrigation_sector_id")
    @classmethod
    def validate_sector(cls, value: str | None) -> str | None:
        if value is not None and value not in IRRIGATION_SECTOR_IDS:
            raise ValueError("Unknown irrigation sector.")
        return value


class PlantUnitCreate(PlantUnitBase):
    pass


class PlantUnitUpdate(BaseModel):
    species: str | None = Field(default=None, min_length=1, max_length=100)
    variety: str | None = Field(default=None, max_length=100)
    rootstock: str | None = Field(default=None, max_length=100)
    planted_on: date | None = None
    planted_on_precision: str | None = None
    status: str | None = None
    irrigation_sector_id: str | None = None
    irrigation_line_slug: str | None = Field(default=None, max_length=100)
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None


class PlantUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    public_code: str
    species: str
    species_label: str
    variety: str | None
    rootstock: str | None
    parcel_slug: str
    parcel_name: str
    matrix_row: int
    matrix_column: int
    matrix_position_code: str
    planted_on: date | None
    planted_on_precision: str
    status: str
    status_label: str
    irrigation_sector_id: str | None
    irrigation_line_slug: str | None
    latitude: float | None
    longitude: float | None
    notes: str | None
    created_at: datetime
    updated_at: datetime | None


class PlantMatrixCellRead(BaseModel):
    row: int
    column: int
    position_code: str
    cell_type: str
    visible_code: str | None
    species_code: str | None
    feature_label: str | None
    displacement_marker: str | None
    plant: PlantUnitRead | None


class PlantMatrixRead(BaseModel):
    parcel: PlantParcelRead
    row_labels: list[str]
    column_labels: list[str]
    cells: list[PlantMatrixCellRead]


class PlantPhotoUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1)


class PlantPhotoStageRequest(BaseModel):
    photos: list[PlantPhotoUpload] = Field(min_length=1, max_length=100)
    fallback_taken_at: datetime | None = None


class PlantPhotoStageItemRead(BaseModel):
    index: int
    filename: str
    content_type: str
    sha256: str
    size_bytes: int
    taken_at: datetime | None
    date_source: str
    detected_code: str | None
    confidence: float
    resolver: str
    status: str
    diagnostic: dict[str, str]
    diagnostics: dict[str, str]
    plant_id: int | None
    plant_public_code: str | None
    matrix_position_code: str | None
    species: str | None
    species_label: str | None
    irrigation_sector_id: str | None
    duplicate: bool
    thumbnail_data_url: str


class PlantPhotoStageRead(BaseModel):
    items: list[PlantPhotoStageItemRead]


class PlantPhotoConfirmItem(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    plant_id: int | None = None
    taken_at: datetime | None = None
    date_source: str
    detected_code: str | None = Field(default=None, max_length=100)
    confidence: float | None = None
    status: str


class PlantPhotoConfirmRequest(BaseModel):
    items: list[PlantPhotoConfirmItem] = Field(min_length=1, max_length=100)
    fallback_taken_at: datetime | None = None


class PlantPhotoConfirmRead(BaseModel):
    created_events: int
    imported_photos: int
    skipped_duplicates: int
    skipped_unassigned: int
    event_ids: list[int]


def plant_unit_read(plant: Any) -> PlantUnitRead:
    return PlantUnitRead(
        id=plant.id,
        public_code=plant.public_code,
        species=plant.species,
        species_label=PLANT_SPECIES_LABELS.get(plant.species, plant.species),
        variety=plant.variety,
        rootstock=plant.rootstock,
        parcel_slug=plant.parcel.slug,
        parcel_name=plant.parcel.name,
        matrix_row=plant.matrix_row,
        matrix_column=plant.matrix_column,
        matrix_position_code=plant.matrix_position_code,
        planted_on=plant.planted_on,
        planted_on_precision=plant.planted_on_precision,
        status=plant.status,
        status_label=PLANT_STATUS_LABELS.get(plant.status, plant.status),
        irrigation_sector_id=plant.irrigation_sector_id,
        irrigation_line_slug=plant.irrigation_line.slug if plant.irrigation_line else None,
        latitude=plant.latitude,
        longitude=plant.longitude,
        notes=plant.notes,
        created_at=plant.created_at,
        updated_at=plant.updated_at,
    )
