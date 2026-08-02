from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogItem:
    slug: str
    label: str


FIELD_EVENT_TYPES: tuple[CatalogItem, ...] = (
    CatalogItem("tillage", "Arado/laboreo"),
    CatalogItem("irrigation", "Riego"),
    CatalogItem("pruning", "Poda"),
    CatalogItem("fertilization", "Abonado"),
    CatalogItem("treatment", "Tratamiento"),
    CatalogItem("harvest", "Recogida de frutos"),
    CatalogItem("planting", "Plantación/siembra"),
    CatalogItem("maintenance", "Mantenimiento"),
    CatalogItem("incident", "Incidencia"),
    CatalogItem("observation", "Observación"),
    CatalogItem("other", "Otro"),
)

FIELD_ZONES: tuple[CatalogItem, ...] = (
    CatalogItem("olivos_pequenos", "Olivos pequeños"),
    CatalogItem("olivos_grandes", "Olivos grandes"),
    CatalogItem("casa", "Zona de la casa"),
    CatalogItem("arqueta", "Zona de la arqueta"),
    CatalogItem("otra", "Otra zona"),
)

FIELD_EVENT_SOURCES: tuple[str, ...] = ("manual", "irrigation_system", "imported")

FIELD_EVENT_TYPE_LABELS = {item.slug: item.label for item in FIELD_EVENT_TYPES}
FIELD_ZONE_LABELS = {item.slug: item.label for item in FIELD_ZONES}
