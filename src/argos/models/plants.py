from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from argos.database.base import Base


PLANT_STATUSES = ("active", "incident", "removed", "replaced")
PLANTING_DATE_PRECISIONS = ("exact", "year_month", "year", "unknown")
IRRIGATION_SECTOR_IDS = ("I", "II", "III", "IV")
FIELD_EVENT_TARGET_TYPES = ("parcel", "sector", "row", "plant", "multiple_plants", "free_text")
PLANT_MATRIX_CELL_TYPES = ("empty", "plant", "infrastructure")


class PlantParcel(Base):
    __tablename__ = "plant_parcels"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_plant_parcels_slug"),
        CheckConstraint("matrix_rows = 12", name="ck_plant_parcels_matrix_rows_12"),
        CheckConstraint("matrix_columns = 12", name="ck_plant_parcels_matrix_columns_12"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    matrix_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    matrix_columns: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    plants: Mapped[list["PlantUnit"]] = relationship(back_populates="parcel")
    irrigation_lines: Mapped[list["PlantIrrigationLine"]] = relationship(back_populates="parcel")


class PlantIrrigationLine(Base):
    __tablename__ = "plant_irrigation_lines"
    __table_args__ = (
        UniqueConstraint("parcel_id", "slug", name="uq_plant_irrigation_lines_parcel_slug"),
        CheckConstraint(
            "sector_id IS NULL OR sector_id IN ('I', 'II', 'III', 'IV')",
            name="ck_plant_irrigation_lines_sector_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("plant_parcels.id"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector_id: Mapped[str | None] = mapped_column(String(8), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    parcel: Mapped[PlantParcel] = relationship(back_populates="irrigation_lines")
    plants: Mapped[list["PlantUnit"]] = relationship(back_populates="irrigation_line")


class PlantMatrixCell(Base):
    __tablename__ = "plant_matrix_cells"
    __table_args__ = (
        UniqueConstraint("parcel_id", "matrix_row", "matrix_column", name="uq_plant_matrix_cells_parcel_position"),
        CheckConstraint("matrix_row BETWEEN 1 AND 12", name="ck_plant_matrix_cells_matrix_row"),
        CheckConstraint("matrix_column BETWEEN 1 AND 12", name="ck_plant_matrix_cells_matrix_column"),
        CheckConstraint(
            "cell_type IN ('empty', 'plant', 'infrastructure')",
            name="ck_plant_matrix_cells_cell_type",
        ),
        CheckConstraint(
            "displacement_marker IS NULL OR displacement_marker IN ('#', 'b')",
            name="ck_plant_matrix_cells_displacement_marker",
        ),
        Index("ix_plant_matrix_cells_parcel_type", "parcel_id", "cell_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("plant_parcels.id"), nullable=False, index=True)
    matrix_row: Mapped[int] = mapped_column(Integer, nullable=False)
    matrix_column: Mapped[int] = mapped_column(Integer, nullable=False)
    matrix_position_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    cell_type: Mapped[str] = mapped_column(String(32), nullable=False, default="empty", server_default="empty")
    visible_code: Mapped[str | None] = mapped_column(String(100))
    species_code: Mapped[str | None] = mapped_column(String(16))
    feature_label: Mapped[str | None] = mapped_column(String(100))
    displacement_marker: Mapped[str | None] = mapped_column(String(1))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    parcel: Mapped[PlantParcel] = relationship()


class PlantUnit(Base):
    __tablename__ = "plant_units"
    __table_args__ = (
        UniqueConstraint("public_code", name="uq_plant_units_public_code"),
        UniqueConstraint("parcel_id", "matrix_row", "matrix_column", name="uq_plant_units_parcel_matrix_position"),
        CheckConstraint("matrix_row BETWEEN 1 AND 12", name="ck_plant_units_matrix_row"),
        CheckConstraint("matrix_column BETWEEN 1 AND 12", name="ck_plant_units_matrix_column"),
        CheckConstraint(
            "status IN ('active', 'incident', 'removed', 'replaced')",
            name="ck_plant_units_status",
        ),
        CheckConstraint(
            "planted_on_precision IN ('exact', 'year_month', 'year', 'unknown')",
            name="ck_plant_units_planted_on_precision",
        ),
        CheckConstraint(
            "irrigation_sector_id IS NULL OR irrigation_sector_id IN ('I', 'II', 'III', 'IV')",
            name="ck_plant_units_irrigation_sector_id",
        ),
        Index("ix_plant_units_parcel_status", "parcel_id", "status"),
        Index("ix_plant_units_parcel_sector", "parcel_id", "irrigation_sector_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    species: Mapped[str] = mapped_column(String(100), nullable=False)
    variety: Mapped[str | None] = mapped_column(String(100))
    rootstock: Mapped[str | None] = mapped_column(String(100))
    parcel_id: Mapped[int] = mapped_column(ForeignKey("plant_parcels.id"), nullable=False, index=True)
    matrix_row: Mapped[int] = mapped_column(Integer, nullable=False)
    matrix_column: Mapped[int] = mapped_column(Integer, nullable=False)
    matrix_position_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    planted_on: Mapped[date | None] = mapped_column()
    planted_on_precision: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", server_default="unknown")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    irrigation_sector_id: Mapped[str | None] = mapped_column(String(8), index=True)
    irrigation_line_id: Mapped[int | None] = mapped_column(ForeignKey("plant_irrigation_lines.id"), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    parcel: Mapped[PlantParcel] = relationship(back_populates="plants")
    irrigation_line: Mapped[PlantIrrigationLine | None] = relationship(back_populates="plants")
    field_event_links: Mapped[list["FieldEventPlantUnit"]] = relationship(
        back_populates="plant",
        cascade="all, delete-orphan",
    )


class FieldEventPlantUnit(Base):
    __tablename__ = "field_event_plant_units"
    __table_args__ = (UniqueConstraint("field_event_id", "plant_unit_id", name="uq_field_event_plant_units_event_plant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field_event_id: Mapped[int] = mapped_column(ForeignKey("field_events.id"), nullable=False, index=True)
    plant_unit_id: Mapped[int] = mapped_column(ForeignKey("plant_units.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    plant: Mapped[PlantUnit] = relationship(back_populates="field_event_links")
