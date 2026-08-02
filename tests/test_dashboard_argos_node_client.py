from __future__ import annotations

from typing import Any
from urllib.error import HTTPError

import pytest

from argos.dashboard.argos_node_client import ArgosNodeClient, ArgosNodeError


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_argos_node_client_builds_valve_url() -> None:
    client = ArgosNodeClient(base_url="http://10.194.83.1/")

    assert client._build_url("/valves/1") == "http://10.194.83.1/valves/1"


def test_argos_node_client_gets_valve_state(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse(b'{"open": true}')

    monkeypatch.setattr("argos.dashboard.argos_node_client.urlopen", fake_urlopen)

    client = ArgosNodeClient(base_url="http://10.194.83.1", timeout_seconds=2)

    assert client.get_valve_1() == {"open": True}
    request, timeout = requests[0]
    assert request.full_url == "http://10.194.83.1/valves/1"
    assert request.get_method() == "GET"
    assert timeout == 2


def test_argos_node_client_gets_status(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse(b'{"flowmeter": {"implemented": true}}')

    monkeypatch.setattr("argos.dashboard.argos_node_client.urlopen", fake_urlopen)

    client = ArgosNodeClient(base_url="http://10.194.83.1", timeout_seconds=2)

    assert client.get_status() == {"flowmeter": {"implemented": True}}
    request, timeout = requests[0]
    assert request.full_url == "http://10.194.83.1/status"
    assert request.get_method() == "GET"
    assert timeout == 2


def test_argos_node_client_posts_open_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requests.append(request)
        return FakeResponse(b"{}")

    monkeypatch.setattr("argos.dashboard.argos_node_client.urlopen", fake_urlopen)

    client = ArgosNodeClient(base_url="http://10.194.83.1")

    assert client.open_valve_1() == {}
    assert client.close_valve_1() == {}
    assert [request.full_url for request in requests] == [
        "http://10.194.83.1/valves/1/open",
        "http://10.194.83.1/valves/1/close",
    ]
    assert [request.get_method() for request in requests] == ["POST", "POST"]


def test_argos_node_client_posts_generic_valve_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requests.append(request)
        return FakeResponse(b"{}")

    monkeypatch.setattr("argos.dashboard.argos_node_client.urlopen", fake_urlopen)

    client = ArgosNodeClient(base_url="http://10.194.83.1")

    assert client.open_valve(2) == {}
    assert client.close_valve(2) == {}
    assert [request.full_url for request in requests] == [
        "http://10.194.83.1/valves/2/open",
        "http://10.194.83.1/valves/2/close",
    ]


def test_argos_node_client_posts_flowmeter_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        requests.append(request)
        return FakeResponse(b"{}")

    monkeypatch.setattr("argos.dashboard.argos_node_client.urlopen", fake_urlopen)

    client = ArgosNodeClient(base_url="http://10.194.83.1")

    assert client.reset_flowmeter_total() == {}
    assert client.reset_flowmeter_session() == {}
    assert client.reset_flowmeter_hydrological_year() == {}
    assert [request.full_url for request in requests] == [
        "http://10.194.83.1/flowmeter/reset-total",
        "http://10.194.83.1/flowmeter/reset-session",
        "http://10.194.83.1/flowmeter/reset-hydrological-year",
    ]


def test_argos_node_client_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        raise HTTPError(request.full_url, 500, "Server error", hdrs=None, fp=None)

    monkeypatch.setattr("argos.dashboard.argos_node_client.urlopen", fake_urlopen)

    client = ArgosNodeClient(base_url="http://10.194.83.1")

    with pytest.raises(ArgosNodeError, match="HTTP 500"):
        client.get_valve_1()
