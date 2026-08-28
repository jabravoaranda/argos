from __future__ import annotations

from threading import Event
from typing import Any

from fastapi.testclient import TestClient

from argos import main as main_module


class FakeSettings:
    app_env = "development"
    argos_node_url = "http://192.168.1.40"
    argos_node_poll_interval_seconds = 5.0
    argos_irrigation_main_ev = 8
    argos_irrigation_sector_i_ev = 7
    argos_irrigation_sector_ii_ev = 6
    argos_irrigation_sector_iii_ev = 6
    argos_irrigation_sector_iv_ev = 6


class FakeThread:
    instances: list["FakeThread"] = []

    def __init__(self, *, target: Any, kwargs: dict[str, Any], name: str, daemon: bool) -> None:
        self.target = target
        self.kwargs = kwargs
        self.name = name
        self.daemon = daemon
        self.started = False
        self.joined = False
        self.join_timeout: float | None = None
        FakeThread.instances.append(self)

    def start(self) -> None:
        self.started = True

    def join(self, timeout: float | None = None) -> None:
        self.joined = True
        self.join_timeout = timeout


def test_create_app_starts_flowmeter_worker_when_node_url_is_configured(monkeypatch) -> None:
    FakeThread.instances.clear()
    monkeypatch.setattr(main_module, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(main_module, "Thread", FakeThread)

    with TestClient(main_module.create_app()) as client:
        assert client.get("/live").json() == {"status": "ok"}
        worker = FakeThread.instances[0]
        assert worker.started is True
        assert worker.name == "argos-node-flowmeter-capture"
        assert worker.daemon is True
        assert worker.kwargs["node_url"] == "http://192.168.1.40"
        assert isinstance(worker.kwargs["stop_event"], Event)
        assert worker.kwargs["stop_event"].is_set() is False

    assert worker.kwargs["stop_event"].is_set() is True
    assert worker.joined is True
