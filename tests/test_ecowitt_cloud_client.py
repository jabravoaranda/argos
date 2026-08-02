from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from argos.config.settings import Settings
from argos.integrations.ecowitt_cloud import (
    EcowittCloudClient,
    EcowittCloudConfigError,
    EcowittCloudCredentials,
    EcowittCloudError,
    format_cloud_mac,
    format_cloud_datetime,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_cloud_client_from_settings_requires_credentials() -> None:
    settings = Settings(argos_admin_token="test-admin-token", ecowitt_ingest_token="test-token", _env_file=None)

    with pytest.raises(EcowittCloudConfigError):
        EcowittCloudClient.from_settings(settings)


def test_format_cloud_mac_adds_colons_for_ecowitt_history_api() -> None:
    assert format_cloud_mac("14080871B1AF") == "14:08:08:71:B1:AF"
    assert format_cloud_mac("14-08-08-71-b1-af") == "14:08:08:71:B1:AF"


def test_cloud_client_from_settings_formats_mac_for_history_api() -> None:
    settings = Settings(
        argos_admin_token="test-admin-token",
        ecowitt_ingest_token="test-token",
        ecowitt_cloud_application_key="app",
        ecowitt_cloud_api_key="api",
        ecowitt_cloud_mac="14080871B1AF",
        _env_file=None,
    )

    client = EcowittCloudClient.from_settings(settings)

    assert client.credentials.mac == "14:08:08:71:B1:AF"


def test_cloud_client_builds_history_request() -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: int) -> FakeResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse(b'{"code": 0, "data": {"outdoor": []}}')

    client = EcowittCloudClient(
        base_url="https://api.ecowitt.net",
        api_version="v3",
        credentials=EcowittCloudCredentials(application_key="app", api_key="api", mac="AABBCCDDEEFF"),
        timeout_seconds=7,
        urlopen_func=fake_urlopen,
    )

    payload = client.get_history(
        start=datetime(2026, 7, 10, 0, 0, 0),
        end=datetime(2026, 7, 10, 1, 0, 0),
        callbacks=("outdoor", "rainfall_piezo"),
    )

    query = parse_qs(urlparse(captured["url"]).query)
    assert payload["code"] == 0
    assert captured["timeout"] == 7
    assert query["application_key"] == ["app"]
    assert query["api_key"] == ["api"]
    assert query["mac"] == ["AABBCCDDEEFF"]
    assert query["start_date"] == ["2026-07-10 00:00:00"]
    assert query["end_date"] == ["2026-07-10 01:00:00"]
    assert query["call_back"] == ["outdoor,rainfall_piezo"]


def test_cloud_client_rejects_api_error_code() -> None:
    def fake_urlopen(request: Any, *, timeout: int) -> FakeResponse:
        return FakeResponse(b'{"code": 10001, "msg": "invalid key"}')

    client = EcowittCloudClient(
        base_url="https://api.ecowitt.net",
        api_version="v3",
        credentials=EcowittCloudCredentials(application_key="app", api_key="api", mac="AABBCCDDEEFF"),
        urlopen_func=fake_urlopen,
    )

    with pytest.raises(EcowittCloudError, match="10001"):
        client.get_history(start=datetime(2026, 7, 10), end=datetime(2026, 7, 11))


def test_cloud_client_rejects_non_json_response() -> None:
    def fake_urlopen(request: Any, *, timeout: int) -> FakeResponse:
        return FakeResponse(b"not json")

    client = EcowittCloudClient(
        base_url="https://api.ecowitt.net",
        api_version="v3",
        credentials=EcowittCloudCredentials(application_key="app", api_key="api", mac="AABBCCDDEEFF"),
        urlopen_func=fake_urlopen,
    )

    with pytest.raises(EcowittCloudError, match="non-JSON"):
        client.get_history(start=datetime(2026, 7, 10), end=datetime(2026, 7, 11))


def test_format_cloud_datetime_uses_ecowitt_expected_format() -> None:
    assert format_cloud_datetime(datetime(2026, 7, 10, 9, 8, 7)) == "2026-07-10 09:08:07"


def test_format_cloud_datetime_converts_aware_values_to_local_time() -> None:
    value = datetime(2026, 7, 10, 9, 8, 7, tzinfo=UTC)

    assert format_cloud_datetime(value, timezone_name="Europe/Madrid") == "2026-07-10 11:08:07"
