from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any


class SatelliteGeometryError(ValueError):
    """Raised when an AOI geometry cannot be used for satellite ingestion."""


AOI_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ConfiguredAOI:
    slug: str
    name: str
    geometry: dict[str, Any]
    geometry_hash: str
    area_m2: float


def get_configured_aois(settings: Any) -> dict[str, ConfiguredAOI]:
    if settings.argos_satellite_aois_json:
        return parse_aois_json(settings.argos_satellite_aois_json)
    return {}


def parse_aois_json(value: str | None) -> dict[str, ConfiguredAOI]:
    if not value or not value.strip():
        raise SatelliteGeometryError("Satellite AOIs JSON is not defined.")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SatelliteGeometryError("Satellite AOIs must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise SatelliteGeometryError("Satellite AOIs JSON root must be an object keyed by aoi_slug.")
    if not payload:
        raise SatelliteGeometryError("Satellite AOIs JSON must define at least one AOI.")

    aois: dict[str, ConfiguredAOI] = {}
    for slug, item in payload.items():
        if not isinstance(slug, str) or not AOI_SLUG_PATTERN.fullmatch(slug):
            raise SatelliteGeometryError(f"Satellite AOI slug {slug!r} must match ^[a-z0-9][a-z0-9_]*$.")
        if slug in aois:
            raise SatelliteGeometryError(f"Duplicate Satellite AOI slug {slug!r}.")
        if not isinstance(item, dict):
            raise SatelliteGeometryError(f"Satellite AOI {slug!r} must be an object.")
        name = item.get("name")
        geometry = item.get("geometry")
        if not isinstance(name, str) or not name.strip():
            raise SatelliteGeometryError(f"Satellite AOI {slug!r} must define a non-empty name.")
        if not isinstance(geometry, dict):
            raise SatelliteGeometryError(f"Satellite AOI {slug!r} must define a GeoJSON geometry.")
        aois[slug] = configured_aoi(slug=slug, name=name.strip(), geometry=geometry)
    return aois


def configured_aoi(*, slug: str, name: str, geometry: dict[str, Any]) -> ConfiguredAOI:
    normalized_geometry = validate_aoi_geometry(geometry)
    return ConfiguredAOI(
        slug=slug,
        name=name,
        geometry=normalized_geometry,
        geometry_hash=geometry_hash(normalized_geometry),
        area_m2=estimate_geometry_area_m2(normalized_geometry),
    )


def validate_polygon_geojson(geometry: dict[str, Any]) -> dict[str, Any]:
    return validate_aoi_geometry(geometry)


def validate_aoi_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    if geometry.get("type") == "Feature":
        geometry = geometry.get("geometry") or {}
    geometry_type = geometry.get("type")
    if geometry_type == "Polygon":
        return {"type": "Polygon", "coordinates": _validate_polygon_coordinates(geometry.get("coordinates"))}
    if geometry_type == "MultiPolygon":
        polygons = geometry.get("coordinates")
        if not isinstance(polygons, list) or not polygons:
            raise SatelliteGeometryError("Satellite AOI MultiPolygon must include coordinates.")
        return {
            "type": "MultiPolygon",
            "coordinates": [_validate_polygon_coordinates(polygon) for polygon in polygons],
        }
    raise SatelliteGeometryError("Satellite AOI must be a GeoJSON Polygon or MultiPolygon in EPSG:4326.")


def _validate_polygon_coordinates(coordinates: Any) -> list[list[list[float]]]:
    if not isinstance(coordinates, list) or not coordinates:
        raise SatelliteGeometryError("Satellite AOI polygon must include coordinates.")

    rings = []
    for ring_index, ring in enumerate(coordinates):
        if not isinstance(ring, list) or len(ring) < 4:
            raise SatelliteGeometryError("Satellite AOI polygon rings must contain at least four positions.")

        positions = [_validate_position(position) for position in ring]
        if positions[0] != positions[-1]:
            raise SatelliteGeometryError("Satellite AOI polygon rings must be closed.")
        if ring_index == 0 and len(set(positions[:-1])) < 3:
            raise SatelliteGeometryError("Satellite AOI polygon must contain at least three distinct points.")
        rings.append([list(position) for position in positions])
    if _ring_area_degrees2([tuple(position) for position in rings[0]]) == 0:
        raise SatelliteGeometryError("Satellite AOI polygon area must be greater than zero.")
    return rings


def geometry_hash(geometry: dict[str, Any]) -> str:
    canonical = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def estimate_polygon_area_m2(geometry: dict[str, Any]) -> float:
    return estimate_geometry_area_m2(geometry)


def estimate_geometry_area_m2(geometry: dict[str, Any]) -> float:
    if geometry["type"] == "Polygon":
        return _estimate_polygon_coordinates_area_m2(geometry["coordinates"])
    return sum(_estimate_polygon_coordinates_area_m2(polygon) for polygon in geometry["coordinates"])


def _estimate_polygon_coordinates_area_m2(coordinates: list[list[list[float]]]) -> float:
    points = [(float(lon), float(lat)) for lon, lat, *_ in coordinates[0]]
    mean_lat = math.radians(sum(lat for _, lat in points[:-1]) / (len(points) - 1))
    meters_per_degree_lat = 111_132.92
    meters_per_degree_lon = 111_412.84 * math.cos(mean_lat)
    projected = [(lon * meters_per_degree_lon, lat * meters_per_degree_lat) for lon, lat in points]
    area = 0.0
    for (x1, y1), (x2, y2) in zip(projected, projected[1:]):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _validate_position(position: Any) -> tuple[float, float]:
    if not isinstance(position, list | tuple) or len(position) < 2:
        raise SatelliteGeometryError("Satellite AOI polygon positions must be lon/lat coordinate arrays.")
    try:
        lon = float(position[0])
        lat = float(position[1])
    except (TypeError, ValueError) as exc:
        raise SatelliteGeometryError("Satellite AOI coordinates must be numeric lon/lat values.") from exc
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise SatelliteGeometryError("Satellite AOI coordinates must be WGS84 lon/lat values.")
    return (lon, lat)


def _ring_area_degrees2(points: list[tuple[float, float]]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        area += x1 * y2 - x2 * y1
    return area
