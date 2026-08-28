from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from argos.database.base import Base
from argos.domain.plants import matrix_position_code, parse_matrix_position_code
from argos.models import FieldEvent, FieldEventPlantUnit, PlantMatrixCell, PlantParcel, PlantUnit
from argos.repositories.plants import PlantRepository
from argos.services.plants import ensure_base_matrix, import_plantation_matrix_csv, plantation_matrix_layout


MATRIX_CSV = Path("docs/reference/plantation_matrix_12x12.csv")


def test_matrix_coordinates_use_base_12_digits() -> None:
    assert matrix_position_code(1, 1) == "11"
    assert matrix_position_code(12, 12) == "CC"
    assert parse_matrix_position_code("AC") == (10, 12)

    with pytest.raises(ValueError):
        parse_matrix_position_code("10")


def test_plant_constraints_reject_duplicate_public_code_and_position() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        parcel = PlantParcel(slug="tomillar", name="Finca tomillar")
        session.add(parcel)
        session.flush()
        session.add_all(
            [
                PlantUnit(public_code="11", species="fig", parcel_id=parcel.id, matrix_row=1, matrix_column=1, matrix_position_code="11"),
                PlantUnit(public_code="11", species="olive", parcel_id=parcel.id, matrix_row=1, matrix_column=2, matrix_position_code="12"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        parcel = PlantParcel(slug="tomillar", name="Finca tomillar")
        session.add(parcel)
        session.flush()
        session.add_all(
            [
                PlantUnit(public_code="11", species="fig", parcel_id=parcel.id, matrix_row=1, matrix_column=1, matrix_position_code="11"),
                PlantUnit(public_code="12", species="olive", parcel_id=parcel.id, matrix_row=1, matrix_column=1, matrix_position_code="11"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_import_matrix_csv_is_idempotent_and_preserves_empty_cells() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = import_plantation_matrix_csv(session=session, path=MATRIX_CSV)
        second = import_plantation_matrix_csv(session=session, path=MATRIX_CSV)
        session.commit()

        assert first.plants_created > 0
        assert second.plants_created == 0
        assert second.plants_updated == first.plants_created
        assert session.scalar(select(PlantMatrixCell).where(PlantMatrixCell.matrix_position_code == "17")).cell_type == "empty"
        assert session.scalar(select(PlantMatrixCell).where(PlantMatrixCell.visible_code == "1B")).cell_type == "infrastructure"
        assert session.scalar(select(PlantUnit).where(PlantUnit.public_code == "2B#")).species == "mango"


def test_matrix_layout_returns_all_144_cells_and_attached_plants() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        ensure_base_matrix(session=session)
        layout = plantation_matrix_layout(session=session)

        assert len(layout["cells"]) == 144
        assert layout["cells"][0]["position_code"] == "11"
        assert layout["cells"][-1]["position_code"] == "CC"


def test_plant_history_is_chronological_and_uses_many_to_many_link() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        parcel = PlantRepository(session).upsert_parcel(slug="tomillar", name="Finca tomillar")
        plant, _created = PlantRepository(session).upsert_plant_by_public_code(
            public_code="11",
            values={
                "species": "fig",
                "parcel_id": parcel.id,
                "matrix_row": 1,
                "matrix_column": 1,
                "matrix_position_code": "11",
                "planted_on_precision": "unknown",
                "status": "active",
                "irrigation_sector_id": "I",
                "irrigation_line_id": None,
                "planted_on": None,
                "variety": None,
                "rootstock": None,
                "latitude": None,
                "longitude": None,
                "notes": None,
            },
        )
        old = FieldEvent(occurred_at=datetime(2026, 8, 1, tzinfo=UTC), event_type="observation", title="Viejo")
        new = FieldEvent(occurred_at=datetime(2026, 8, 2, tzinfo=UTC), event_type="pruning", title="Nuevo")
        session.add_all([old, new])
        session.flush()
        session.add_all(
            [
                FieldEventPlantUnit(field_event_id=old.id, plant_unit_id=plant.id),
                FieldEventPlantUnit(field_event_id=new.id, plant_unit_id=plant.id),
            ]
        )
        session.flush()

        history = PlantRepository(session).plant_history(plant_id=plant.id)

        assert [event.title for event in history] == ["Nuevo", "Viejo"]
