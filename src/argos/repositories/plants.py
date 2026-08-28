from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import asc, desc, or_, select
from sqlalchemy.orm import Session, selectinload

from argos.models.field_event import FieldEvent
from argos.models.plants import FieldEventPlantUnit, PlantIrrigationLine, PlantMatrixCell, PlantParcel, PlantUnit


class PlantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_parcel_by_slug(self, slug: str) -> PlantParcel | None:
        return self.session.scalar(select(PlantParcel).where(PlantParcel.slug == slug))

    def upsert_parcel(self, *, slug: str, name: str, matrix_rows: int = 12, matrix_columns: int = 12) -> PlantParcel:
        parcel = self.get_parcel_by_slug(slug)
        if parcel is None:
            parcel = PlantParcel(slug=slug, name=name, matrix_rows=matrix_rows, matrix_columns=matrix_columns)
            self.session.add(parcel)
        else:
            parcel.name = name
            parcel.matrix_rows = matrix_rows
            parcel.matrix_columns = matrix_columns
        self.session.flush()
        return parcel

    def list_parcels(self) -> list[PlantParcel]:
        return list(self.session.scalars(select(PlantParcel).order_by(PlantParcel.name)).all())

    def get_irrigation_line(self, *, parcel_id: int, slug: str) -> PlantIrrigationLine | None:
        return self.session.scalar(
            select(PlantIrrigationLine).where(
                PlantIrrigationLine.parcel_id == parcel_id,
                PlantIrrigationLine.slug == slug,
            )
        )

    def upsert_irrigation_line(
        self,
        *,
        parcel_id: int,
        slug: str,
        name: str,
        sector_id: str | None,
    ) -> PlantIrrigationLine:
        line = self.get_irrigation_line(parcel_id=parcel_id, slug=slug)
        if line is None:
            line = PlantIrrigationLine(parcel_id=parcel_id, slug=slug, name=name, sector_id=sector_id)
            self.session.add(line)
        else:
            line.name = name
            line.sector_id = sector_id
        self.session.flush()
        return line

    def upsert_matrix_cell(self, *, parcel_id: int, matrix_row: int, matrix_column: int, values: dict[str, Any]) -> PlantMatrixCell:
        cell = self.session.scalar(
            select(PlantMatrixCell).where(
                PlantMatrixCell.parcel_id == parcel_id,
                PlantMatrixCell.matrix_row == matrix_row,
                PlantMatrixCell.matrix_column == matrix_column,
            )
        )
        if cell is None:
            cell = PlantMatrixCell(parcel_id=parcel_id, matrix_row=matrix_row, matrix_column=matrix_column, **values)
            self.session.add(cell)
        else:
            for key, value in values.items():
                setattr(cell, key, value)
        self.session.flush()
        return cell

    def list_matrix_cells(self, *, parcel_id: int) -> list[PlantMatrixCell]:
        statement = (
            select(PlantMatrixCell)
            .where(PlantMatrixCell.parcel_id == parcel_id)
            .order_by(PlantMatrixCell.matrix_row, PlantMatrixCell.matrix_column)
        )
        return list(self.session.scalars(statement).all())

    def get_plant(self, plant_id: int) -> PlantUnit | None:
        return self.session.get(PlantUnit, plant_id)

    def get_plant_by_public_code(self, public_code: str) -> PlantUnit | None:
        return self.session.scalar(select(PlantUnit).where(PlantUnit.public_code == public_code))

    def upsert_plant_by_public_code(self, *, public_code: str, values: dict[str, Any]) -> tuple[PlantUnit, bool]:
        plant = self.get_plant_by_public_code(public_code)
        created = plant is None
        if plant is None:
            plant = PlantUnit(public_code=public_code, **values)
            self.session.add(plant)
        else:
            for key, value in values.items():
                setattr(plant, key, value)
        self.session.flush()
        return plant, created

    def list_plants(
        self,
        *,
        parcel_slug: str | None = None,
        status: str | None = None,
        species: str | None = None,
        irrigation_sector_id: str | None = None,
        search: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[PlantUnit]:
        statement = select(PlantUnit).options(selectinload(PlantUnit.parcel), selectinload(PlantUnit.irrigation_line))
        if parcel_slug is not None:
            statement = statement.join(PlantParcel).where(PlantParcel.slug == parcel_slug)
        if status is not None:
            statement = statement.where(PlantUnit.status == status)
        if species is not None:
            statement = statement.where(PlantUnit.species == species)
        if irrigation_sector_id is not None:
            statement = statement.where(PlantUnit.irrigation_sector_id == irrigation_sector_id)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(or_(PlantUnit.public_code.ilike(pattern), PlantUnit.notes.ilike(pattern)))
        statement = statement.order_by(PlantUnit.parcel_id, PlantUnit.matrix_row, PlantUnit.matrix_column).limit(limit).offset(offset)
        return list(self.session.scalars(statement).all())

    def link_event_to_plants(self, *, event: FieldEvent, plant_ids: Iterable[int]) -> None:
        self.session.query(FieldEventPlantUnit).filter(FieldEventPlantUnit.field_event_id == event.id).delete(
            synchronize_session=False
        )
        for plant_id in dict.fromkeys(plant_ids):
            self.session.add(FieldEventPlantUnit(field_event_id=event.id, plant_unit_id=plant_id))
        self.session.flush()

    def plant_history(self, *, plant_id: int, limit: int = 100) -> list[FieldEvent]:
        statement = (
            select(FieldEvent)
            .join(FieldEventPlantUnit, FieldEventPlantUnit.field_event_id == FieldEvent.id)
            .where(FieldEventPlantUnit.plant_unit_id == plant_id)
            .order_by(desc(FieldEvent.occurred_at), desc(FieldEvent.id))
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def estimated_irrigation_by_sector(self, *, sector_id: str) -> list[tuple[Any, float]]:
        from argos.models.argos_node import ArgosIrrigationSectorMinuteAttribution

        statement = (
            select(
                ArgosIrrigationSectorMinuteAttribution.window_start_utc,
                ArgosIrrigationSectorMinuteAttribution.volume_l,
            )
            .where(ArgosIrrigationSectorMinuteAttribution.sector_id == sector_id)
            .order_by(asc(ArgosIrrigationSectorMinuteAttribution.window_start_utc))
        )
        return [(window_start_utc, volume_l) for window_start_utc, volume_l in self.session.execute(statement).all()]
