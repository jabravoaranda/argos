from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.integrations.aemet.client import AemetClient, AemetResponseError
from argos.main import create_app
from argos.models.aemet import WeatherDailyObservation
from argos.services.aemet_import import AemetImportService
from argos.services.aemet_normalizer import normalize_aemet_daily_record


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def aemet_record(**updates: Any) -> dict[str, Any]:
    record = {
        "fecha": "2026-07-01",
        "indicativo": "6127X",
        "nombre": "ALORA",
        "provincia": "MALAGA",
        "tmed": "24,5",
        "prec": "1,2",
        "tmin": "18,1",
        "tmax": "31,0",
        "velmedia": "2,5",
        "racha": "8,3",
        "dir": "22",
        "sol": "11,4",
        "presMax": "1015,2",
        "presMin": "1008,1",
        "hrMedia": "55",
        "hrMin": "33",
        "hrMax": "82",
    }
    record.update(updates)
    return record


def test_aemet_client_valid_response() -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"datos": "https://datos.example.test/daily.json"}),
            FakeResponse(200, [aemet_record()]),
        ]
    )
    client = AemetClient(base_url="https://opendata.example.test", api_key="secret", session=session, backoff_seconds=0)

    records = client.daily_climatology(start=date(2026, 7, 1), end=date(2026, 7, 1))

    assert records == [aemet_record()]
    assert session.calls[0]["params"] == {"api_key": "secret"}
    assert session.calls[1]["params"] is None


def test_aemet_client_rejects_response_without_datos() -> None:
    client = AemetClient(
        base_url="https://opendata.example.test",
        api_key="secret",
        session=FakeSession([FakeResponse(200, {"estado": 200})]),
        backoff_seconds=0,
    )

    with pytest.raises(AemetResponseError, match="datos"):
        client.daily_climatology(start=date(2026, 7, 1), end=date(2026, 7, 1))


def test_aemet_client_retries_rate_limit_and_temporary_5xx() -> None:
    session = FakeSession(
        [
            FakeResponse(429, {}),
            FakeResponse(503, {}),
            FakeResponse(200, {"datos": "https://datos.example.test/daily.json"}),
            FakeResponse(200, []),
        ]
    )
    client = AemetClient(
        base_url="https://opendata.example.test",
        api_key="secret",
        session=session,
        max_retries=3,
        backoff_seconds=0,
    )

    assert client.daily_climatology(start=date(2026, 7, 1), end=date(2026, 7, 1)) == []
    assert len(session.calls) == 4


def test_aemet_client_raises_after_temporary_5xx_retries() -> None:
    client = AemetClient(
        base_url="https://opendata.example.test",
        api_key="secret",
        session=FakeSession([FakeResponse(500, {}), FakeResponse(502, {})]),
        max_retries=1,
        backoff_seconds=0,
    )

    with pytest.raises(AemetResponseError, match="HTTP 502"):
        client.daily_climatology(start=date(2026, 7, 1), end=date(2026, 7, 1))


def test_aemet_normalizer_handles_comma_decimals_missing_values_and_traces() -> None:
    normalized = normalize_aemet_daily_record(aemet_record(prec="Ip", sol="", presMin=None))

    assert normalized.observation_date == date(2026, 7, 1)
    assert normalized.temperature_mean_c == 24.5
    assert normalized.precipitation_mm is None
    assert normalized.precipitation_trace is True
    assert normalized.sunshine_hours is None
    assert normalized.pressure_min_hpa is None
    assert normalized.raw_payload_json["prec"] == "Ip"


class FakeAemetClient:
    def __init__(self, blocks: list[list[dict[str, Any]]]) -> None:
        self.blocks = blocks
        self.calls: list[tuple[date, date, str]] = []

    def daily_climatology(self, *, start: date, end: date, station_id: str | None = None) -> list[dict[str, Any]]:
        self.calls.append((start, end, station_id or ""))
        return self.blocks.pop(0)

    def station_metadata(self, *, station_id: str | None = None) -> dict[str, Any]:
        return {
            "indicativo": station_id,
            "nombre": "Álora",
            "provincia": "Málaga",
            "latitud": "365031N",
            "longitud": "044223W",
            "altitud": "150",
        }


def test_aemet_service_upserts_duplicates_corrections_empty_range_and_idempotency(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    first_client = FakeAemetClient([[aemet_record()], []])
    with get_sessionmaker()() as session:
        first = AemetImportService(session=session, client=first_client).backfill(
            station_id="6127X",
            start=date(2026, 7, 1),
            end=date(2026, 7, 2),
            block_days=1,
        )
    assert first.records_received == 1
    assert first.inserted == 1
    assert first.skipped == 0

    second_client = FakeAemetClient([[aemet_record()]])
    with get_sessionmaker()() as session:
        second = AemetImportService(session=session, client=second_client).backfill(
            station_id="6127X",
            start=date(2026, 7, 1),
            end=date(2026, 7, 1),
        )
    assert second.inserted == 0
    assert second.updated == 0
    assert second.skipped == 1

    corrected_client = FakeAemetClient([[aemet_record(tmax="32,0")]])
    with get_sessionmaker()() as session:
        corrected = AemetImportService(session=session, client=corrected_client).backfill(
            station_id="6127X",
            start=date(2026, 7, 1),
            end=date(2026, 7, 1),
        )
        observations = session.scalars(select(WeatherDailyObservation)).all()
    assert corrected.updated == 1
    assert len(observations) == 1
    assert observations[0].temperature_max_c == 32.0

    client = TestClient(create_app())
    stations = client.get("/api/v1/weather/stations", params={"provider": "aemet"}).json()
    assert stations[0]["external_id"] == "6127X"
    assert stations[0]["latitude"] == pytest.approx(36.841944444444444)
    daily = client.get("/api/v1/weather/aemet/observations", params={"from": "2026-07-01", "to": "2026-07-02"}).json()
    assert len(daily) == 1
    assert daily[0]["raw_payload_json"]["tmax"] == "32,0"
    latest = client.get("/api/v1/weather/aemet/sync/latest", params={"station": "6127X"}).json()
    assert latest["records_received"] == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_aemet_admin_sync_endpoint_imports_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("AEMET_API_KEY", "test-aemet-key")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    fake_client = FakeAemetClient([[aemet_record()]])
    monkeypatch.setattr("argos.api.weather.AemetClient.from_settings", lambda settings: fake_client)

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/weather/aemet/backfill",
        params={"station": "6127X", "from": "2026-07-01", "to": "2026-07-01"},
        headers={"X-ARGOS-ADMIN-TOKEN": "test-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["station_external_id"] == "6127X"
    assert payload["inserted"] == 1
    assert payload["records_received"] == 1

    get_settings.cache_clear()
    reset_database_caches()


def test_aemet_observations_accept_long_dashboard_range(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())

    fake_client = FakeAemetClient([[aemet_record(fecha="2008-08-21"), aemet_record(fecha="2025-10-14")]])
    with get_sessionmaker()() as session:
        AemetImportService(session=session, client=fake_client).backfill(
            station_id="6127X",
            start=date(2008, 8, 21),
            end=date(2025, 10, 14),
        )

    client = TestClient(create_app())
    response = client.get(
        "/api/v1/weather/aemet/observations",
        params={"station": "6127X", "from": "2008-08-21", "to": "2025-10-14", "limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    assert response.json()[0]["observation_date"] == "2025-10-14"

    get_settings.cache_clear()
    reset_database_caches()


def test_aemet_admin_csv_endpoint_imports_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())
    csv_path = tmp_path / "6127X.csv"
    csv_path.write_text(
        "fecha,indicativo,nombre,provincia,altitud,tmed,prec,tmin,tmax\n"
        '2025-04-28,6127X,ÁLORA,MALAGA,172,"17,7","0,0","13,5","21,9"\n',
        encoding="utf-8",
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/weather/aemet/import-csv",
        params={"station": "6127X", "path": str(csv_path)},
        headers={"X-ARGOS-ADMIN-TOKEN": "test-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["inserted"] == 1
    daily = client.get("/api/v1/weather/aemet/observations", params={"station": "6127X"}).json()
    assert daily[0]["observation_date"] == "2025-04-28"
    assert daily[0]["temperature_mean_c"] == 17.7

    get_settings.cache_clear()
    reset_database_caches()
