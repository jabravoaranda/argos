from __future__ import annotations

from fastapi.testclient import TestClient

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, reset_database_caches
from argos.main import create_app


ADMIN_HEADERS = {"X-ARGOS-ADMIN-TOKEN": "test-admin-token"}


def test_field_events_crud_filters_and_export(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ARGOS_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())
    client = TestClient(create_app())

    first = create_event(
        client,
        occurred_at="2026-07-31T08:00:00Z",
        event_type="irrigation",
        title="Riego sector norte",
        description="Riego de apoyo",
        zone_slug="olivos_pequenos",
        quantity=12.5,
        unit="m3",
    )
    second = create_event(
        client,
        occurred_at="2026-08-01T09:30:00Z",
        event_type="pruning",
        title="Poda correctiva",
        zone_slug="olivos_grandes",
    )

    list_response = client.get("/api/v1/field-events")
    assert list_response.status_code == 200
    rows = list_response.json()
    assert [row["id"] for row in rows] == [second["id"], first["id"]]

    type_response = client.get("/api/v1/field-events", params={"event_type": "irrigation"})
    assert [row["title"] for row in type_response.json()] == ["Riego sector norte"]

    zone_response = client.get("/api/v1/field-events", params={"zone_slug": "olivos_grandes"})
    assert [row["title"] for row in zone_response.json()] == ["Poda correctiva"]

    date_response = client.get(
        "/api/v1/field-events",
        params={"from": "2026-08-01T00:00:00Z", "to": "2026-08-01T23:59:59Z"},
    )
    assert [row["title"] for row in date_response.json()] == ["Poda correctiva"]

    search_response = client.get("/api/v1/field-events", params={"search": "apoyo"})
    assert [row["title"] for row in search_response.json()] == ["Riego sector norte"]

    detail_response = client.get(f"/api/v1/field-events/{first['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["title"] == "Riego sector norte"

    update_response = client.patch(
        f"/api/v1/field-events/{first['id']}",
        json={"title": "Riego goteo norte", "quantity": 13.0},
        headers=ADMIN_HEADERS,
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Riego goteo norte"
    assert update_response.json()["quantity"] == 13.0

    csv_response = client.get("/api/v1/field-events/export.csv", params={"event_type": "irrigation"})
    assert csv_response.status_code == 200
    assert "Fecha y hora,Tipo,Título,Zona" in csv_response.text
    assert "Riego goteo norte" in csv_response.text
    assert "Olivos pequeños" in csv_response.text

    delete_response = client.delete(f"/api/v1/field-events/{second['id']}", headers=ADMIN_HEADERS)
    assert delete_response.status_code == 204
    assert client.get(f"/api/v1/field-events/{second['id']}").status_code == 404

    get_settings.cache_clear()
    reset_database_caches()


def test_field_events_validate_required_fields_and_quantity_unit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ARGOS_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())
    client = TestClient(create_app())

    missing_title = client.post(
        "/api/v1/field-events",
        json={"occurred_at": "2026-08-01T09:30:00Z", "event_type": "irrigation", "title": ""},
        headers=ADMIN_HEADERS,
    )
    unit_without_quantity = client.post(
        "/api/v1/field-events",
        json={
            "occurred_at": "2026-08-01T09:30:00Z",
            "event_type": "irrigation",
            "title": "Riego",
            "unit": "m3",
        },
        headers=ADMIN_HEADERS,
    )
    invalid_type = client.post(
        "/api/v1/field-events",
        json={"occurred_at": "2026-08-01T09:30:00Z", "event_type": "foo", "title": "Evento"},
        headers=ADMIN_HEADERS,
    )

    assert missing_title.status_code == 422
    assert unit_without_quantity.status_code == 422
    assert invalid_type.status_code == 422

    get_settings.cache_clear()
    reset_database_caches()


def create_event(client: TestClient, **payload):
    response = client.post("/api/v1/field-events", json={"source": "manual", **payload}, headers=ADMIN_HEADERS)
    assert response.status_code == 201
    return response.json()
