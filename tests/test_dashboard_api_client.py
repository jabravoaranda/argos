from __future__ import annotations

from typing import Any

from argos.dashboard.api_client import ArgosApiClient


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


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
                "aoi_slug": "olivos_pequenos",
                "metric": "ndvi",
            },
        )
        == "http://localhost:8080/api/v1/satellite/export.json?from=2026-06-01T00%3A00%3A00Z&to=2026-07-01T23%3A59%3A59Z&quality_status=valid&zone_id=1&aoi_slug=olivos_pequenos&metric=ndvi"
    )


def test_api_client_builds_field_event_export_url() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    assert (
        client.get_field_events_export_csv_url(
            start="2026-07-01T00:00:00Z",
            end="2026-08-01T23:59:59Z",
            event_type="irrigation",
            zone_slug="olivos_pequenos",
            search="goteo",
        )
        == "http://localhost:8080/api/v1/field-events/export.csv?from=2026-07-01T00%3A00%3A00Z&to=2026-08-01T23%3A59%3A59Z&event_type=irrigation&zone_slug=olivos_pequenos&search=goteo"
    )


def test_api_client_sends_field_event_json(monkeypatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse(b'{"id": 1, "title": "Riego"}')

    monkeypatch.setattr("argos.dashboard.api_client.urlopen", fake_urlopen)
    client = ArgosApiClient(base_url="http://localhost:8080", admin_token="admin", timeout_seconds=3)

    result = client.create_field_event({"title": "Riego"})

    request, timeout = requests[0]
    assert result["id"] == 1
    assert request.full_url == "http://localhost:8080/api/v1/field-events"
    assert request.get_method() == "POST"
    assert request.data == b'{"title": "Riego"}'
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["X-argos-admin-token"] == "admin"
    assert timeout == 3


def test_api_client_sends_ecowitt_cloud_backfill_admin_request(monkeypatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse(b'{"imported_count": 1, "duplicate_count": 0, "warning_count": 0, "warnings": []}')

    monkeypatch.setattr("argos.dashboard.api_client.urlopen", fake_urlopen)
    client = ArgosApiClient(base_url="http://localhost:8080", admin_token="admin", timeout_seconds=9)

    result = client.backfill_ecowitt_cloud(
        gateway_identifier="GW2000A",
        start="2026-07-10T12:00:00Z",
        end="2026-07-10T13:00:00Z",
    )

    request, timeout = requests[0]
    assert result["imported_count"] == 1
    assert request.full_url == (
        "http://localhost:8080/api/v1/weather/ecowitt-cloud/backfill?"
        "gateway_identifier=GW2000A&from=2026-07-10T12%3A00%3A00Z&to=2026-07-10T13%3A00%3A00Z"
    )
    assert request.get_method() == "POST"
    assert request.headers["X-argos-admin-token"] == "admin"
    assert timeout == 9


def test_api_client_sends_analytics_json(monkeypatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse(b'{"correlation": 1.0}')

    monkeypatch.setattr("argos.dashboard.api_client.urlopen", fake_urlopen)
    client = ArgosApiClient(base_url="http://localhost:8080", timeout_seconds=4)

    result = client.analytics_correlation({"variable_x": "ecowitt.outdoor_temperature"})

    request, timeout = requests[0]
    assert result["correlation"] == 1.0
    assert request.full_url == "http://localhost:8080/api/v1/analytics/correlation"
    assert request.get_method() == "POST"
    assert request.data == b'{"variable_x": "ecowitt.outdoor_temperature"}'
    assert request.headers["Content-type"] == "application/json"
    assert timeout == 4


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


def test_api_client_requires_admin_token_for_field_event_writes() -> None:
    client = ArgosApiClient(base_url="http://localhost:8080")

    try:
        client.create_field_event({"title": "Riego"})
    except RuntimeError as exc:
        assert "Admin token is required" in str(exc)
    else:
        raise AssertionError("Expected missing admin token error.")
