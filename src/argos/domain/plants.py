from __future__ import annotations

from dataclasses import dataclass

from argos.models.plants import IRRIGATION_SECTOR_IDS, PLANT_STATUSES


MATRIX_DIGITS: tuple[str, ...] = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "A", "B", "C")
MATRIX_SIZE = 12
DEFAULT_PLANT_PARCEL_SLUG = "tomillar"
DEFAULT_PLANT_PARCEL_NAME = "Finca tomillar"


@dataclass(frozen=True, slots=True)
class CatalogItem:
    slug: str
    label: str


PLANT_STATUS_LABELS = {
    "active": "Activo",
    "incident": "Incidencia",
    "removed": "Baja",
    "replaced": "Sustituido",
}

PLANT_SPECIES_LABELS = {
    "fig": "Higuera",
    "olive": "Olivo",
    "persimmon": "Caqui",
    "loquat": "Níspero",
    "peach": "Melocotonero",
    "plum": "Ciruelo",
    "female_pistachio": "Pistacho hembra",
    "male_pistachio": "Pistacho macho",
    "walnut": "Nogal",
    "unknown": "Especie sin confirmar",
}

PLANT_MATRIX_SYMBOLS = {
    "H": "fig",
    "O": "olive",
    "CQ": "persimmon",
    "N": "loquat",
    "ME": "peach",
    "CIR": "plum",
    "PH": "female_pistachio",
    "PM": "male_pistachio",
    "NG": "walnut",
    "M": "unknown",
}

INFRASTRUCTURE_SYMBOLS = {
    "B": "Bidón",
    "R": "Rampa",
}

PLANT_STATUS_CATALOG = tuple(CatalogItem(slug=status, label=PLANT_STATUS_LABELS[status]) for status in PLANT_STATUSES)
PLANT_SPECIES_CATALOG = tuple(
    CatalogItem(slug=slug, label=label) for slug, label in sorted(PLANT_SPECIES_LABELS.items(), key=lambda item: item[1])
)
IRRIGATION_SECTOR_CATALOG = tuple(CatalogItem(slug=sector_id, label=f"Sector {sector_id}") for sector_id in IRRIGATION_SECTOR_IDS)


def matrix_position_code(row: int, column: int) -> str:
    return f"{matrix_digit(row)}{matrix_digit(column)}"


def matrix_digit(value: int) -> str:
    if value < 1 or value > MATRIX_SIZE:
        raise ValueError("Matrix coordinates must be between 1 and 12.")
    return MATRIX_DIGITS[value - 1]


def parse_matrix_position_code(value: str) -> tuple[int, int]:
    normalized = value.strip().upper()
    if len(normalized) != 2:
        raise ValueError("Matrix position must use two coordinates from 1 to C.")
    try:
        return MATRIX_DIGITS.index(normalized[0]) + 1, MATRIX_DIGITS.index(normalized[1]) + 1
    except ValueError as exc:
        raise ValueError("Matrix position must use coordinates from 1 to C.") from exc
