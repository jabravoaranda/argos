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


def test_api_client_requires_admin_token_for_admin_endpoints() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    try:
        client.get_raw_reports()
    except RuntimeError as exc:
        assert "Admin token is required" in str(exc)
    else:
        raise AssertionError("Expected missing admin token error.")
