from __future__ import annotations

from argos.dashboard.api_client import ArgosApiClient


def test_api_client_builds_urls_with_query_params() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080/")

    assert (
        client._build_url("/api/v1/weather/observations", params={"from": "2026-07-10T00:00:00Z", "to": None})
        == "http://localhost:8080/api/v1/weather/observations?from=2026-07-10T00%3A00%3A00Z"
    )


def test_api_client_builds_urls_without_query_params() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    assert client._build_url("/api/v1/weather/latest", params=None) == "http://localhost:8080/api/v1/weather/latest"


def test_api_client_builds_station_identity_urls() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    assert client._build_url("/api/v1/weather/station", params=None) == "http://localhost:8080/api/v1/weather/station"
    assert (
        client._build_url("/api/v1/weather/station/hardware", params=None)
        == "http://localhost:8080/api/v1/weather/station/hardware"
    )


def test_api_client_builds_aemet_urls() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    assert (
        client._build_url(
            "/api/v1/weather/aemet/observations",
            params={"station": "6127X", "from": "2026-01-01", "to": "2026-01-31", "limit": 1000, "offset": 0},
        )
        == "http://localhost:8080/api/v1/weather/aemet/observations?station=6127X&from=2026-01-01&to=2026-01-31&limit=1000&offset=0"
    )


def test_api_client_builds_satellite_export_urls() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    assert (
        client._build_url(
            "/api/v1/satellite/export.json",
            params={
                "from": "2026-06-01T00:00:00Z",
                "to": "2026-07-01T23:59:59Z",
                "quality_status": "valid",
                "zone_id": 1,
                "metric": "ndvi",
            },
        )
        == "http://localhost:8080/api/v1/satellite/export.json?from=2026-06-01T00%3A00%3A00Z&to=2026-07-01T23%3A59%3A59Z&quality_status=valid&zone_id=1&metric=ndvi"
    )


def test_api_client_requires_admin_token_for_admin_endpoints() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    try:
        client.get_raw_reports()
    except RuntimeError as exc:
        assert "Admin token is required" in str(exc)
    else:
        raise AssertionError("Expected missing admin token error.")


def test_api_client_requires_admin_token_for_aemet_imports() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    try:
        client.import_aemet_csv(station="6127X", path="6127X.csv")
    except RuntimeError as exc:
        assert "Admin token is required" in str(exc)
    else:
        raise AssertionError("Expected missing admin token error.")


def test_api_client_requires_admin_token_for_satellite_updates() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    try:
        client.update_satellite()
    except RuntimeError as exc:
        assert "Admin token is required" in str(exc)
    else:
        raise AssertionError("Expected missing admin token error.")
