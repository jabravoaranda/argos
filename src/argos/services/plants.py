from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from argos.domain.plants import (
    DEFAULT_PLANT_PARCEL_NAME,
    DEFAULT_PLANT_PARCEL_SLUG,
    INFRASTRUCTURE_SYMBOLS,
    MATRIX_DIGITS,
    MATRIX_SIZE,
    PLANT_MATRIX_SYMBOLS,
    matrix_position_code,
    parse_matrix_position_code,
)
from argos.models.plants import PlantMatrixCell, PlantParcel, PlantUnit
from argos.repositories.plants import PlantRepository


class PlantImportError(ValueError):
    """Raised when a plantation matrix import file is inconsistent."""


@dataclass(frozen=True, slots=True)
class PlantMatrixImportResult:
    parcel_slug: str
    cells_seen: int
    cells_upserted: int
    plants_created: int
    plants_updated: int
    infrastructure_cells: int
    empty_cells: int


def ensure_base_matrix(
    *,
    session: Session,
    parcel_slug: str = DEFAULT_PLANT_PARCEL_SLUG,
    parcel_name: str = DEFAULT_PLANT_PARCEL_NAME,
) -> PlantParcel:
    repository = PlantRepository(session)
    parcel = repository.upsert_parcel(slug=parcel_slug, name=parcel_name)
    for row in range(1, MATRIX_SIZE + 1):
        for column in range(1, MATRIX_SIZE + 1):
            repository.upsert_matrix_cell(
                parcel_id=parcel.id,
                matrix_row=row,
                matrix_column=column,
                values={
                    "matrix_position_code": matrix_position_code(row, column),
                    "cell_type": "empty",
                    "visible_code": None,
                    "species_code": None,
                    "feature_label": None,
                    "displacement_marker": None,
                    "notes": None,
                },
            )
    return parcel


def import_plantation_matrix_csv(
    *,
    session: Session,
    path: Path,
    parcel_slug: str = DEFAULT_PLANT_PARCEL_SLUG,
    parcel_name: str = DEFAULT_PLANT_PARCEL_NAME,
) -> PlantMatrixImportResult:
    parcel = ensure_base_matrix(session=session, parcel_slug=parcel_slug, parcel_name=parcel_name)
    repository = PlantRepository(session)
    rows = _read_matrix_rows(path)
    cells_upserted = 0
    plants_created = 0
    plants_updated = 0
    infrastructure_cells = 0
    for row in rows:
        matrix_row, matrix_column = parse_matrix_position_code(row["cell_position"])
        symbol = row["symbol"].strip().upper()
        visible_code = row["visible_code"].strip()
        displacement_marker = _displacement_marker(visible_code)
        visible_code = visible_code.upper()
        cell_type = _cell_type_for_symbol(symbol)
        feature_label = INFRASTRUCTURE_SYMBOLS.get(symbol) if cell_type == "infrastructure" else None
        species = PLANT_MATRIX_SYMBOLS.get(symbol)
        repository.upsert_matrix_cell(
            parcel_id=parcel.id,
            matrix_row=matrix_row,
            matrix_column=matrix_column,
            values={
                "matrix_position_code": matrix_position_code(matrix_row, matrix_column),
                "cell_type": cell_type,
                "visible_code": visible_code,
                "species_code": symbol or None,
                "feature_label": feature_label,
                "displacement_marker": displacement_marker,
                "notes": row.get("notes") or None,
            },
        )
        cells_upserted += 1
        if cell_type == "infrastructure":
            infrastructure_cells += 1
            continue
        if species is None:
            raise PlantImportError(f"Unknown plant symbol {symbol!r} at {row['cell_position']}.")
        plant, created = repository.upsert_plant_by_public_code(
            public_code=visible_code,
            values={
                "species": species,
                "variety": _optional_text(row.get("variety")),
                "rootstock": _optional_text(row.get("rootstock")),
                "parcel_id": parcel.id,
                "matrix_row": matrix_row,
                "matrix_column": matrix_column,
                "matrix_position_code": matrix_position_code(matrix_row, matrix_column),
                "planted_on": _optional_date(row.get("planted_on")),
                "planted_on_precision": row.get("planted_on_precision") or "unknown",
                "status": row.get("status") or "active",
                "irrigation_sector_id": _optional_text(row.get("irrigation_sector_id")),
                "irrigation_line_id": None,
                "latitude": _optional_float(row.get("latitude")),
                "longitude": _optional_float(row.get("longitude")),
                "notes": _optional_text(row.get("notes")),
            },
        )
        if created:
            plants_created += 1
        else:
            plants_updated += 1
        if plant.id is None:
            raise PlantImportError(f"Could not persist plant {visible_code}.")
    empty_cells = MATRIX_SIZE * MATRIX_SIZE - cells_upserted
    return PlantMatrixImportResult(
        parcel_slug=parcel.slug,
        cells_seen=len(rows),
        cells_upserted=cells_upserted,
        plants_created=plants_created,
        plants_updated=plants_updated,
        infrastructure_cells=infrastructure_cells,
        empty_cells=empty_cells,
    )


def plantation_matrix_layout(*, session: Session, parcel_slug: str = DEFAULT_PLANT_PARCEL_SLUG) -> dict[str, Any]:
    repository = PlantRepository(session)
    parcel = repository.get_parcel_by_slug(parcel_slug)
    if parcel is None:
        return _empty_layout(parcel_slug=parcel_slug, parcel_name=DEFAULT_PLANT_PARCEL_NAME)
    cells = {(cell.matrix_row, cell.matrix_column): cell for cell in repository.list_matrix_cells(parcel_id=parcel.id)}
    plants = {(plant.matrix_row, plant.matrix_column): plant for plant in repository.list_plants(parcel_slug=parcel.slug)}
    return {
        "parcel": _parcel_dict(parcel),
        "row_labels": list(MATRIX_DIGITS),
        "column_labels": list(MATRIX_DIGITS),
        "cells": [
            _cell_dict(row=row, column=column, cell=cells.get((row, column)), plant=plants.get((row, column)))
            for row in range(1, MATRIX_SIZE + 1)
            for column in range(1, MATRIX_SIZE + 1)
        ],
    }


def _empty_layout(*, parcel_slug: str, parcel_name: str) -> dict[str, Any]:
    return {
        "parcel": {"slug": parcel_slug, "name": parcel_name, "matrix_rows": MATRIX_SIZE, "matrix_columns": MATRIX_SIZE},
        "row_labels": list(MATRIX_DIGITS),
        "column_labels": list(MATRIX_DIGITS),
        "cells": [
            _cell_dict(row=row, column=column, cell=None, plant=None)
            for row in range(1, MATRIX_SIZE + 1)
            for column in range(1, MATRIX_SIZE + 1)
        ],
    }


def _cell_dict(*, row: int, column: int, cell: PlantMatrixCell | None, plant: PlantUnit | None) -> dict[str, Any]:
    code = matrix_position_code(row, column)
    cell_type = cell.cell_type if cell is not None else "empty"
    return {
        "row": row,
        "column": column,
        "position_code": code,
        "cell_type": cell_type,
        "visible_code": cell.visible_code if cell is not None else None,
        "species_code": cell.species_code if cell is not None else None,
        "feature_label": cell.feature_label if cell is not None else None,
        "displacement_marker": cell.displacement_marker if cell is not None else None,
        "plant": plant,
    }


def _parcel_dict(parcel: PlantParcel) -> dict[str, Any]:
    return {
        "id": parcel.id,
        "slug": parcel.slug,
        "name": parcel.name,
        "matrix_rows": parcel.matrix_rows,
        "matrix_columns": parcel.matrix_columns,
    }


def _read_matrix_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise PlantImportError(f"Matrix import file does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"cell_position", "visible_code", "symbol"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise PlantImportError(f"Matrix import is missing required columns: {', '.join(sorted(missing))}.")
        return [row for row in reader if row.get("cell_position") and row.get("visible_code") and row.get("symbol")]


def _cell_type_for_symbol(symbol: str) -> str:
    if symbol in PLANT_MATRIX_SYMBOLS:
        return "plant"
    if symbol in INFRASTRUCTURE_SYMBOLS:
        return "infrastructure"
    raise PlantImportError(f"Unknown matrix symbol {symbol!r}.")


def _displacement_marker(visible_code: str) -> str | None:
    if visible_code.endswith("#"):
        return "#"
    if visible_code.endswith("b"):
        return "b"
    return None


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(value: str | None) -> float | None:
    text = _optional_text(value)
    return None if text is None else float(text.replace(",", "."))


def _optional_date(value: str | None) -> date | None:
    text = _optional_text(value)
    return None if text is None else date.fromisoformat(text)
