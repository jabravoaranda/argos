from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
import requests

from argos.integrations.copernicus import (
    CopernicusAuthError,
    CopernicusCredentials,
    CopernicusRateLimitError,
    CopernicusSatelliteAdapter,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        *,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload or {}
        self.content = content or json.dumps(self.payload).encode("utf-8")
        self.headers = headers or {}
        self.ok = 200 <= status_code < 400

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_adapter(session: FakeSession) -> CopernicusSatelliteAdapter:
    return CopernicusSatelliteAdapter(
        token_url="https://identity.example/token",
        stac_url="https://stac.example/v1",
        catalog_url="https://catalog.example/v1",
        statistics_url="https://statistics.example/v1",
        process_url="https://process.example/v1",
        credentials=CopernicusCredentials(client_id="client", client_secret="secret"),
        timeout_seconds=1,
        session=session,  # type: ignore[arg-type]
    )


def test_copernicus_token_is_reused() -> None:
    session = FakeSession([FakeResponse(200, {"access_token": "token-a", "expires_in": 3600})])
    adapter = make_adapter(session)

    assert adapter.get_token() == "token-a"
    assert adapter.get_token() == "token-a"
    assert len(session.requests) == 1
    assert "secret" in session.requests[0]["data"]["client_secret"]


def test_copernicus_stac_pagination() -> None:
    first_page = {
        "features": [
            {"id": "item-2", "collection": "sentinel-2-l2a", "properties": {"datetime": "2026-01-02T00:00:00Z"}}
        ],
        "links": [{"rel": "next", "href": "https://stac.example/v1/search?page=2"}],
    }
    second_page = {
        "features": [
            {"id": "item-1", "collection": "sentinel-2-l2a", "properties": {"datetime": "2026-01-01T00:00:00Z"}}
        ],
        "links": [],
    }
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "token-a", "expires_in": 3600}),
            FakeResponse(200, first_page),
            FakeResponse(200, second_page),
        ]
    )
    adapter = make_adapter(session)

    items = adapter.search_sentinel2_items(
        geometry={"type": "Polygon", "coordinates": []},
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 3, tzinfo=UTC),
        max_cloud_cover=60,
    )

    assert [item.id for item in items] == ["item-1", "item-2"]
    assert session.requests[1]["json"]["collections"] == ["sentinel-2-l2a"]
    assert session.requests[2]["url"] == "https://stac.example/v1/search?page=2"


def test_copernicus_401_and_403_are_auth_errors() -> None:
    for status_code in (401, 403):
        session = FakeSession(
            [
                FakeResponse(200, {"access_token": "token-a", "expires_in": 3600}),
                FakeResponse(status_code, {}),
            ]
        )
        adapter = make_adapter(session)
        with pytest.raises(CopernicusAuthError):
            adapter.search_sentinel2_items(
                geometry={"type": "Polygon", "coordinates": []},
                start=datetime(2026, 1, 1, tzinfo=UTC),
                end=datetime(2026, 1, 2, tzinfo=UTC),
                max_cloud_cover=60,
            )


def test_copernicus_429_retries_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("argos.integrations.copernicus.time.sleep", lambda _seconds: None)
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "token-a", "expires_in": 3600}),
            FakeResponse(429, {}, headers={"Retry-After": "0"}),
            FakeResponse(429, {}, headers={"Retry-After": "0"}),
            FakeResponse(429, {}, headers={"Retry-After": "0"}),
            FakeResponse(429, {}, headers={"Retry-After": "0"}),
        ]
    )
    adapter = make_adapter(session)

    with pytest.raises(CopernicusRateLimitError):
        adapter.search_sentinel2_items(
            geometry={"type": "Polygon", "coordinates": []},
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
            max_cloud_cover=60,
        )


def test_copernicus_timeout_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("argos.integrations.copernicus.time.sleep", lambda _seconds: None)
    session = FakeSession(
        [
            requests.Timeout(),
            FakeResponse(200, {"access_token": "token-a", "expires_in": 3600}),
        ]
    )
    adapter = make_adapter(session)

    assert adapter.get_token() == "token-a"
    assert len(session.requests) == 2
