from __future__ import annotations

import json

import pytest

from argos.services.satellite_geometry import (
    SatelliteGeometryError,
    estimate_polygon_area_m2,
    geometry_hash,
    parse_aois_json,
    validate_polygon_geojson,
)


VALID_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-3.7, 37.1], [-3.699, 37.1], [-3.699, 37.101], [-3.7, 37.101], [-3.7, 37.1]]],
}


def test_validate_polygon_geojson_validates_closed_wgs84_polygon() -> None:
    geometry = validate_polygon_geojson(VALID_POLYGON)

    assert geometry["type"] == "Polygon"
    assert geometry["coordinates"][0][0] == geometry["coordinates"][0][-1]
    assert geometry_hash(geometry) == geometry_hash(geometry)
    assert estimate_polygon_area_m2(geometry) > 0


def test_parse_aois_json_rejects_missing_geometry() -> None:
    with pytest.raises(SatelliteGeometryError, match="not defined"):
        parse_aois_json("")


def test_validate_polygon_geojson_rejects_open_polygon() -> None:
    invalid = {
        "type": "Polygon",
        "coordinates": [[[-3.7, 37.1], [-3.699, 37.1], [-3.699, 37.101], [-3.7, 37.101]]],
    }

    with pytest.raises(SatelliteGeometryError, match="closed"):
        validate_polygon_geojson(invalid)


def test_parse_aois_json_accepts_multiple_polygons() -> None:
    aois = parse_aois_json(
        json.dumps(
            {
                "olivos_pequenos": {"name": "Olivos pequenos", "geometry": VALID_POLYGON},
                "olivos_grandes": {"name": "Olivos grandes", "geometry": VALID_POLYGON},
            }
        )
    )

    assert list(aois) == ["olivos_pequenos", "olivos_grandes"]
    assert aois["olivos_pequenos"].name == "Olivos pequenos"
    assert aois["olivos_grandes"].area_m2 > 0


def test_parse_aois_json_rejects_invalid_slug() -> None:
    with pytest.raises(SatelliteGeometryError, match="slug"):
        parse_aois_json(json.dumps({"Olivos pequenos": {"name": "Olivos pequenos", "geometry": VALID_POLYGON}}))
