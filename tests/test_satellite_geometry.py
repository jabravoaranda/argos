from __future__ import annotations

import json

import pytest

from argos.services.satellite_geometry import (
    SatelliteGeometryError,
    estimate_polygon_area_m2,
    geometry_hash,
    load_aoi_geojson,
)


VALID_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-3.7, 37.1], [-3.699, 37.1], [-3.699, 37.101], [-3.7, 37.101], [-3.7, 37.1]]],
}


def test_load_aoi_geojson_validates_closed_wgs84_polygon() -> None:
    geometry = load_aoi_geojson(json.dumps(VALID_POLYGON))

    assert geometry["type"] == "Polygon"
    assert geometry["coordinates"][0][0] == geometry["coordinates"][0][-1]
    assert geometry_hash(geometry) == geometry_hash(geometry)
    assert estimate_polygon_area_m2(geometry) > 0


def test_load_aoi_geojson_rejects_missing_geometry() -> None:
    with pytest.raises(SatelliteGeometryError, match="not defined"):
        load_aoi_geojson("")


def test_load_aoi_geojson_rejects_open_polygon() -> None:
    invalid = {
        "type": "Polygon",
        "coordinates": [[[-3.7, 37.1], [-3.699, 37.1], [-3.699, 37.101], [-3.7, 37.101]]],
    }

    with pytest.raises(SatelliteGeometryError, match="closed"):
        load_aoi_geojson(json.dumps(invalid))
