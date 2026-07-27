from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class SatelliteGeometryError(ValueError):
    """Raised when an AOI geometry cannot be used for satellite ingestion."""


def load_aoi_geojson(value: str | None) -> dict[str, Any]:
    if not value or not value.strip():
        raise SatelliteGeometryError("Satellite AOI geometry is not defined.")
    try:
        geometry = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SatelliteGeometryError("Satellite AOI must be valid GeoJSON.") from exc
    return validate_polygon_geojson(geometry)


def validate_polygon_geojson(geometry: dict[str, Any]) -> dict[str, Any]:
    if geometry.get("type") == "Feature":
        geometry = geometry.get("geometry") or {}
    if geometry.get("type") != "Polygon":
        raise SatelliteGeometryError("Satellite AOI must be a GeoJSON Polygon in EPSG:4326.")

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise SatelliteGeometryError("Satellite AOI polygon must include coordinates.")

    exterior = coordinates[0]
    if not isinstance(exterior, list) or len(exterior) < 4:
        raise SatelliteGeometryError("Satellite AOI polygon exterior ring must contain at least four positions.")

    positions = [_validate_position(position) for position in exterior]
    if positions[0] != positions[-1]:
        raise SatelliteGeometryError("Satellite AOI polygon exterior ring must be closed.")
    if len(set(positions[:-1])) < 3:
        raise SatelliteGeometryError("Satellite AOI polygon must contain at least three distinct points.")
    if _ring_area_degrees2(positions) == 0:
        raise SatelliteGeometryError("Satellite AOI polygon area must be greater than zero.")

    return {"type": "Polygon", "coordinates": [[list(position) for position in positions]]}


def geometry_hash(geometry: dict[str, Any]) -> str:
    canonical = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def estimate_polygon_area_m2(geometry: dict[str, Any]) -> float:
    coordinates = geometry["coordinates"][0]
    points = [(float(lon), float(lat)) for lon, lat, *_ in coordinates]
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
    lon = float(position[0])
    lat = float(position[1])
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise SatelliteGeometryError("Satellite AOI coordinates must be WGS84 lon/lat values.")
    return (lon, lat)


def _ring_area_degrees2(points: list[tuple[float, float]]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        area += x1 * y2 - x2 * y1
    return area
