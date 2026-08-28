from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, reset_database_caches
from argos.main import create_app
from argos.services.plants import import_plantation_matrix_csv


ADMIN_HEADERS = {"X-ARGOS-ADMIN-TOKEN": "test-admin-token"}


def test_plants_api_lists_filters_matrix_and_history(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ARGOS_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())
    with get_engine().begin() as connection:
        from sqlalchemy.orm import Session

        with Session(bind=connection) as session:
            import_plantation_matrix_csv(session=session, path=Path("docs/reference/plantation_matrix_12x12.csv"))
            session.flush()

    client = TestClient(create_app())

    catalog = client.get("/api/v1/plants/catalog")
    assert catalog.status_code == 200
    assert "active" in [item["slug"] for item in catalog.json()["statuses"]]

    matrix = client.get("/api/v1/plants/matrix", params={"parcel_slug": "tomillar"})
    assert matrix.status_code == 200
    cells = matrix.json()["cells"]
    assert len(cells) == 144
    assert next(cell for cell in cells if cell["position_code"] == "17")["cell_type"] == "empty"
    assert next(cell for cell in cells if cell["visible_code"] == "18#")["displacement_marker"] == "#"

    filtered = client.get("/api/v1/plants", params={"species": "fig"})
    assert filtered.status_code == 200
    assert [plant["public_code"] for plant in filtered.json()] == ["11"]

    plant = filtered.json()[0]
    event = client.post(
        "/api/v1/field-events",
        headers=ADMIN_HEADERS,
        json={
            "occurred_at": "2026-08-28T10:00:00Z",
            "event_type": "observation",
            "title": "Revisión higuera",
            "tree_reference": plant["public_code"],
            "target_type": "plant",
            "target_value": plant["public_code"],
            "plant_unit_ids": [plant["id"]],
            "source": "manual",
        },
    )
    assert event.status_code == 201
    assert event.json()["plant_unit_ids"] == [plant["id"]]

    history = client.get(f"/api/v1/plants/{plant['id']}/history")
    assert history.status_code == 200
    assert [row["title"] for row in history.json()] == ["Revisión higuera"]

    get_settings.cache_clear()
    reset_database_caches()
