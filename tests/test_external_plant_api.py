from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.main import create_app
from argos.models.field_event import ExternalApiRequest, FieldEvent, FieldEventPhoto
from argos.models.plants import FieldEventPlantUnit
from argos.services.plants import import_plantation_matrix_csv


READ_HEADERS = {"Authorization": "Bearer test-read-token"}
WRITE_HEADERS = {"Authorization": "Bearer test-write-token"}


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ARGOS_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("ARGOS_EXTERNAL_API_READ_TOKEN", "test-read-token")
    monkeypatch.setenv("ARGOS_EXTERNAL_API_WRITE_TOKEN", "test-write-token")
    monkeypatch.setenv("ARGOS_DAILY_SYNC_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ARGOS_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())
    with get_sessionmaker()() as session:
        import_plantation_matrix_csv(session=session, path=Path("docs/reference/plantation_matrix_12x12.csv"))
        session.commit()
    return TestClient(create_app())


def _jpeg_bytes(color: tuple[int, int, int] = (54, 123, 72)) -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), color=color).save(output, format="JPEG")
    return output.getvalue()


def test_external_api_requires_scoped_bearer_tokens(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    missing = client.get("/api/v1/external/plants/11")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "missing_bearer_token"

    invalid = client.get("/api/v1/external/plants/11", headers={"Authorization": "Bearer invalid"})
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "invalid_bearer_token"

    readable_with_write_scope = client.get("/api/v1/external/plants/11", headers=WRITE_HEADERS)
    assert readable_with_write_scope.status_code == 200
    assert readable_with_write_scope.json()["public_code"] == "11"

    denied_write = client.post(
        "/api/v1/external/plants/11/observations",
        headers={**READ_HEADERS, "Idempotency-Key": "read-cannot-write"},
        json={"observed_at": "2026-09-20T10:00:00+02:00", "note": "No debe guardarse"},
    )
    assert denied_write.status_code == 403
    assert denied_write.json()["error"]["code"] == "insufficient_scope"

    get_settings.cache_clear()
    reset_database_caches()


def test_external_observation_is_idempotent_and_visible_in_normal_history(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    headers = {**WRITE_HEADERS, "Idempotency-Key": "observation-20260920-1"}
    payload = {
        "observed_at": "2026-09-20T10:15:00+02:00",
        "title": "Revisión desde cliente autorizado",
        "note": "Sin síntomas nuevos.",
        "visual_observations": ["Follaje mayoritariamente verde."],
        "interpretation": ["Estado vegetativo razonable."],
        "recommendations": ["Revisar humedad del suelo."],
        "actions_taken": ["Riego de 250 L."],
        "limitations": ["Sin medida simultánea de humedad."],
        "source": "api",
        "metadata": {"client_version": "1.2.0"},
    }

    created = client.post("/api/v1/external/plants/11/observations", headers=headers, json=payload)
    assert created.status_code == 201
    assert created.json()["plant_code"] == "11"
    assert created.json()["source"] == "api"
    assert created.json()["metadata"] == {"client_version": "1.2.0"}
    assert created.json()["visual_observations"] == ["Follaje mayoritariamente verde."]
    assert created.json()["recommendations"] == ["Revisar humedad del suelo."]
    assert created.json()["actions_taken"] == ["Riego de 250 L."]

    replayed = client.post("/api/v1/external/plants/11/observations", headers=headers, json=payload)
    assert replayed.status_code == 201
    assert replayed.headers["Idempotency-Replayed"] == "true"
    assert replayed.json() == created.json()

    conflict = client.post(
        "/api/v1/external/plants/11/observations",
        headers=headers,
        json={**payload, "note": "Contenido diferente."},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"

    plant = client.get("/api/v1/external/plants/11", headers=READ_HEADERS).json()
    history = client.get(f"/api/v1/plants/{plant['id']}/history")
    assert history.status_code == 200
    assert [(item["title"], item["source"]) for item in history.json()] == [
        ("Revisión desde cliente autorizado", "api")
    ]
    assert history.json()[0]["interpretation"] == ["Estado vegetativo razonable."]
    assert history.json()[0]["recommendations"] == ["Revisar humedad del suelo."]
    assert history.json()[0]["actions_taken"] == ["Riego de 250 L."]

    with get_sessionmaker()() as session:
        assert len(list(session.scalars(select(FieldEvent)).all())) == 1
        event = session.scalar(select(FieldEvent))
        assert event is not None
        assert event.visual_observations == ["Follaje mayoritariamente verde."]
        assert event.recommendations == ["Revisar humedad del suelo."]
        assert event.actions_taken == ["Riego de 250 L."]
        records = list(session.scalars(select(ExternalApiRequest)).all())
        assert len(records) == 1
        assert records[0].token_fingerprint != "test-write-token"
        assert records[0].resource_id == created.json()["id"]

    get_settings.cache_clear()
    reset_database_caches()


def test_external_photo_uses_shared_storage_and_can_be_listed_and_downloaded(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    content = _jpeg_bytes()
    headers = {**WRITE_HEADERS, "Idempotency-Key": "photo-20260920-1"}
    data = {
        "observed_at": "2026-09-20T10:30:00+02:00",
        "note": "Vista general de la copa.",
        "visual_observations": '["Se observan brotes basales"]',
        "interpretation": '["Los brotes podrían proceder del portainjerto"]',
        "recommendations": '["Comprobar el origen de los brotes"]',
        "actions_taken": "[]",
        "limitations": '["Evaluación realizada exclusivamente a partir de la fotografía"]',
        "source": "chatgpt",
        "metadata": '{"conversation_id":"external-42"}',
    }
    files = {"photo": ("plant-11.jpg", content, "image/jpeg")}

    created = client.post("/api/v1/external/plants/11/photos", headers=headers, data=data, files=files)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["plant_code"] == "11"
    assert body["source"] == "chatgpt"
    assert body["metadata"] == {"conversation_id": "external-42"}
    assert body["observed_at"] == "2026-09-20T08:30:00Z"
    assert body["visual_observations"] == ["Se observan brotes basales"]
    assert body["interpretation"] == ["Los brotes podrían proceder del portainjerto"]
    assert body["recommendations"] == ["Comprobar el origen de los brotes"]
    assert body["actions_taken"] == []
    assert body["limitations"] == ["Evaluación realizada exclusivamente a partir de la fotografía"]

    replayed = client.post("/api/v1/external/plants/11/photos", headers=headers, data=data, files=files)
    assert replayed.status_code == 201
    assert replayed.headers["Idempotency-Replayed"] == "true"
    assert replayed.json() == body

    photos = client.get("/api/v1/external/plants/11/photos", headers=READ_HEADERS)
    assert photos.status_code == 200
    assert photos.json() == [body]

    downloaded = client.get(body["content_url"], headers=READ_HEADERS)
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert downloaded.headers["content-type"] == "image/jpeg"

    observations = client.get("/api/v1/external/plants/11/observations", headers=READ_HEADERS)
    assert observations.status_code == 200
    assert observations.json()[0]["photo_count"] == 1
    assert observations.json()[0]["visual_observations"] == ["Se observan brotes basales"]

    plant = client.get("/api/v1/external/plants/11", headers=READ_HEADERS).json()
    history = client.get(f"/api/v1/plants/{plant['id']}/history").json()
    assert history[0]["source"] == "chatgpt"
    assert history[0]["photo_url"].endswith(f"/{body['field_event_id']}/photo")

    with get_sessionmaker()() as session:
        event = session.get(FieldEvent, body["field_event_id"])
        photo = session.get(FieldEventPhoto, body["id"])
        assert event is not None and photo is not None
        assert event.photo_storage_path == photo.storage_path
        assert event.photo_sha256 == photo.sha256
        assert event.source == "chatgpt"
        assert event.actions_taken == []
        assert resolve_path_exists(photo.storage_path)

    web_content = _jpeg_bytes((80, 90, 160))
    web_created = client.post(
        "/api/v1/field-events",
        headers={"X-ARGOS-ADMIN-TOKEN": "test-admin-token"},
        json={
            "occurred_at": "2026-09-20T09:00:00Z",
            "event_type": "observation",
            "title": "Seguimiento desde la web",
            "plant_unit_ids": [plant["id"]],
            "tree_reference": "11",
            "target_type": "plant",
            "target_value": "11",
            "source": "web",
            "photo": {
                "filename": "web-plant-11.jpg",
                "content_type": "image/jpeg",
                "data_base64": base64.b64encode(web_content).decode("ascii"),
            },
        },
    )
    assert web_created.status_code == 201, web_created.text
    with get_sessionmaker()() as session:
        event_ids = {body["field_event_id"], web_created.json()["id"]}
        stored_photos = list(session.scalars(select(FieldEventPhoto).where(FieldEventPhoto.field_event_id.in_(event_ids))).all())
        links = list(session.scalars(select(FieldEventPlantUnit).where(FieldEventPlantUnit.field_event_id.in_(event_ids))).all())
        assert len(stored_photos) == 2
        assert len(links) == 2
        assert {item.plant_unit_id for item in links} == {plant["id"]}
        assert all(resolve_path_exists(item.storage_path) for item in stored_photos)

    invalid = client.post(
        "/api/v1/external/plants/11/photos",
        headers={**WRITE_HEADERS, "Idempotency-Key": "invalid-photo"},
        data={**data, "source": "api"},
        files={"photo": ("not-an-image.jpg", b"not an image", "image/jpeg")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_photo"

    unsupported = client.post(
        "/api/v1/external/plants/11/photos",
        headers={**WRITE_HEADERS, "Idempotency-Key": "unsupported-photo"},
        data={**data, "source": "api"},
        files={"photo": ("photo.gif", b"GIF89a", "image/gif")},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "unsupported_photo_format"

    get_settings.cache_clear()
    reset_database_caches()


def test_external_observation_structured_fields_accept_empty_and_omitted_values(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    omitted = client.post(
        "/api/v1/external/plants/11/observations",
        headers={**WRITE_HEADERS, "Idempotency-Key": "structured-omitted"},
        json={
            "observed_at": "2026-09-20T12:00:00+02:00",
            "title": "Observación antigua compatible",
            "note": "Solo texto libre.",
            "source": "api",
        },
    )
    assert omitted.status_code == 201, omitted.text
    assert omitted.json()["visual_observations"] == []
    assert omitted.json()["interpretation"] == []
    assert omitted.json()["recommendations"] == []
    assert omitted.json()["actions_taken"] == []
    assert omitted.json()["limitations"] == []

    empty = client.post(
        "/api/v1/external/plants/11/observations",
        headers={**WRITE_HEADERS, "Idempotency-Key": "structured-empty"},
        json={
            "observed_at": "2026-09-20T12:05:00+02:00",
            "note": "Arrays vacíos explícitos.",
            "visual_observations": [],
            "interpretation": [],
            "recommendations": [],
            "actions_taken": [],
            "limitations": [],
            "source": "chatgpt",
        },
    )
    assert empty.status_code == 201, empty.text
    assert empty.json()["source"] == "chatgpt"
    assert empty.json()["actions_taken"] == []

    listed = client.get("/api/v1/external/plants/11/observations", headers=READ_HEADERS)
    assert listed.status_code == 200
    assert [item["actions_taken"] for item in listed.json()] == [[], []]

    get_settings.cache_clear()
    reset_database_caches()


def test_external_structured_idempotency_conflicts_when_analysis_changes(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    headers = {**WRITE_HEADERS, "Idempotency-Key": "structured-conflict"}
    payload = {
        "observed_at": "2026-09-20T13:00:00+02:00",
        "note": "Seguimiento.",
        "recommendations": ["Revisar humedad."],
        "actions_taken": [],
        "source": "api",
    }

    created = client.post("/api/v1/external/plants/11/observations", headers=headers, json=payload)
    assert created.status_code == 201

    changed = client.post(
        "/api/v1/external/plants/11/observations",
        headers=headers,
        json={**payload, "actions_taken": ["Riego realizado."]},
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_key_conflict"

    get_settings.cache_clear()
    reset_database_caches()


def resolve_path_exists(storage_path: str) -> bool:
    from argos.services.data_layout import resolve_storage_path

    return resolve_storage_path(storage_path).is_file()
