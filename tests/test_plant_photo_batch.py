from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import qrcode
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from argos.config.settings import get_settings
from argos.database.base import Base
from argos.database.session import get_engine, get_sessionmaker, reset_database_caches
from argos.main import create_app
from argos.models import FieldEvent, FieldEventPhoto, FieldEventPlantUnit
from argos.services.field_event_photos import (
    CatalogVisualPlantCodeResolver,
    FieldEventPhotoInput,
    FilenamePlantCodeResolver,
    QRPlantCodeResolver,
    extract_filename_taken_at,
    stage_plant_photos,
    thumbnail_data_url,
)
from argos.services.plants import import_plantation_matrix_csv

ADMIN_HEADERS = {"X-ARGOS-ADMIN-TOKEN": "test-admin-token"}


def test_filename_resolver_reports_valid_and_invalid_codes() -> None:
    resolver = FilenamePlantCodeResolver()

    valid = resolver.resolve(filename="seguimiento 11 higuera.jpg", content=b"", candidate_codes={"11"})
    invalid = resolver.resolve(filename="seguimiento DD desconocido.jpg", content=b"", candidate_codes={"11"})

    assert valid.detected_code == "11"
    assert valid.confidence >= 0.9
    assert invalid.detected_code is None


def test_whatsapp_filename_date_fallback(monkeypatch) -> None:
    monkeypatch.setenv("ARGOS_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    get_settings.cache_clear()

    taken_at = extract_filename_taken_at("WhatsApp Image 2026-08-01 at 11.30.15.jpeg")

    assert taken_at == datetime(2026, 8, 1, 9, 30, 15, tzinfo=UTC)
    get_settings.cache_clear()


def test_thumbnail_applies_exif_orientation() -> None:
    expected_sizes = {1: (80, 40), 3: (80, 40), 6: (40, 80), 8: (40, 80)}
    for orientation, expected_size in expected_sizes.items():
        data_url = thumbnail_data_url(base64.b64encode(oriented_jpeg_bytes(orientation)).decode("ascii"), "image/jpeg")
        _header, encoded = data_url.split(",", 1)
        with Image.open(BytesIO(base64.b64decode(encoded))) as preview:
            assert preview.size == expected_size


def test_qr_resolver_matches_valid_plant_code() -> None:
    result = QRPlantCodeResolver().resolve(filename="foto.jpg", content=qr_png_bytes("P:C2"), candidate_codes={"C2"})

    assert result.detected_code == "C2"
    assert result.resolver == "qr"
    assert result.diagnostics["match"] == "plant_code"
    assert result.confidence >= 0.99


def test_qr_resolver_reports_unknown_and_corrupt_codes() -> None:
    unknown = QRPlantCodeResolver().resolve(filename="foto.jpg", content=qr_png_bytes("P:DD"), candidate_codes={"C2"})
    corrupt = QRPlantCodeResolver().resolve(filename="foto.jpg", content=b"not an image", candidate_codes={"C2"})

    assert unknown.detected_code == "DD"
    assert unknown.confidence < 0.9
    assert corrupt.detected_code is None
    assert corrupt.confidence == 0


def test_visual_resolver_matches_catalog_code_c2() -> None:
    result = CatalogVisualPlantCodeResolver().resolve(filename="historica.jpg", content=handwritten_label_jpeg("C2"), candidate_codes={"11", "C2"})

    assert result.detected_code == "C2"
    assert result.resolver == "vision"
    assert result.confidence >= 0.72


def test_visual_resolver_does_not_emit_code_outside_catalog() -> None:
    result = CatalogVisualPlantCodeResolver().resolve(filename="historica.jpg", content=handwritten_label_jpeg("C2"), candidate_codes={"11"})

    assert result.detected_code != "C2"
    assert result.confidence < 0.9


def test_stage_plant_photos_statuses_and_duplicates(monkeypatch, tmp_path) -> None:
    client = prepared_client(monkeypatch, tmp_path)
    del client
    with get_sessionmaker()() as session:
        photo = photo_input("arbol 11.jpg")
        first = stage_plant_photos(session=session, photos=[photo], fallback_date=datetime(2026, 8, 1, tzinfo=UTC))
        assert first[0].status == "matched"
        assert first[0].plant_public_code == "11"
        assert first[0].date_source == "batch"

        event = FieldEvent(
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            event_type="observation",
            title="Foto previa",
            source="manual",
        )
        session.add(event)
        session.flush()
        session.add(
            FieldEventPhoto(
                field_event_id=event.id,
                storage_path="processed/field-events/photos/existing.jpg",
                mime_type="image/jpeg",
                original_filename="existing.jpg",
                size_bytes=1,
                sha256=first[0].sha256,
                date_source="batch",
            )
        )
        session.flush()

        staged = stage_plant_photos(
            session=session,
            photos=[photo, photo_input("arbol 1C.jpg", color="black"), photo_input("sin-codigo.jpg", color="blue")],
            fallback_date=datetime(2026, 8, 1, tzinfo=UTC),
        )

        assert [item.status for item in staged] == ["duplicate", "review", "unassigned"]


def test_stage_plant_photos_matches_c2_visual_fixture(monkeypatch, tmp_path) -> None:
    client = prepared_client(monkeypatch, tmp_path)
    del client
    with get_sessionmaker()() as session:
        staged = stage_plant_photos(
            session=session,
            photos=[photo_input_from_bytes("tablilla.jpg", handwritten_label_jpeg("C2"))],
            fallback_date=datetime(2026, 8, 1, tzinfo=UTC),
        )

    assert staged[0].status == "matched"
    assert staged[0].resolver == "vision"
    assert staged[0].detected_code == "C2"
    assert staged[0].plant_public_code == "C2"


def test_confirm_photo_batch_creates_grouped_event_and_links_plant(monkeypatch, tmp_path) -> None:
    client = prepared_client(monkeypatch, tmp_path)
    photo_a = photo_payload("arbol 11 a.jpg", color="white")
    photo_b = photo_payload("arbol 11 b.jpg", color="black")
    stage_response = client.post(
        "/api/v1/plants/photos/stage",
        json={"fallback_taken_at": "2026-08-01T00:00:00Z", "photos": [photo_a, photo_b]},
        headers=ADMIN_HEADERS,
    )
    assert stage_response.status_code == 200
    items = stage_response.json()["items"]
    assert [item["status"] for item in items] == ["matched", "matched"]
    assert items[0]["resolver"] in {"filename", "vision", "qr"}
    assert "diagnostic" in items[0]
    confirm_items = [
        {**item, "data_base64": source["data_base64"]}
        for item, source in zip(items, [photo_a, photo_b], strict=False)
    ]

    confirm_response = client.post(
        "/api/v1/plants/photos/confirm",
        json={"fallback_taken_at": "2026-08-01T00:00:00Z", "items": confirm_items},
        headers=ADMIN_HEADERS,
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["created_events"] == 1
    assert confirm_response.json()["imported_photos"] == 2
    with get_sessionmaker()() as session:
        assert session.scalar(select(FieldEvent)).title == "Seguimiento fotográfico 11"
        assert session.scalar(select(FieldEventPhoto.taken_at)) == datetime(2026, 8, 1)
        assert session.query(FieldEventPhoto).count() == 2
        assert session.query(FieldEventPlantUnit).count() == 1


def prepared_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("ECOWITT_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ARGOS_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'argos.db'}")
    monkeypatch.setenv("ARGOS_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    reset_database_caches()
    Base.metadata.create_all(get_engine())
    with get_sessionmaker()() as session:
        import_plantation_matrix_csv(session=session, path=Path("docs/reference/plantation_matrix_12x12.csv"))
        session.commit()
    return TestClient(create_app())


def photo_input(filename: str, *, color: str = "white") -> FieldEventPhotoInput:
    payload = photo_payload(filename, color=color)
    return FieldEventPhotoInput(**payload)


def photo_input_from_bytes(filename: str, content: bytes, *, content_type: str = "image/jpeg") -> FieldEventPhotoInput:
    return FieldEventPhotoInput(filename=filename, content_type=content_type, data_base64=base64.b64encode(content).decode("ascii"))


def photo_payload(filename: str, *, color: str = "white") -> dict:
    return {"filename": filename, "content_type": "image/jpeg", "data_base64": base64.b64encode(jpeg_bytes(color=color)).decode("ascii")}


def jpeg_bytes(*, color: str = "white") -> bytes:
    image = Image.new("RGB", (1, 1), color=color)
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def oriented_jpeg_bytes(orientation: int) -> bytes:
    image = Image.new("RGB", (80, 40), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 20, 39), fill="black")
    exif = image.getexif()
    exif[274] = orientation
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def qr_png_bytes(payload: str) -> bytes:
    image = qrcode.make(payload)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def handwritten_label_jpeg(code: str) -> bytes:
    image = Image.new("RGB", (640, 420), "#7f8b6a")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((170, 120, 470, 300), radius=8, fill="#f7f3df", outline="#2f2f2f", width=4)
    font = _test_code_font(112)
    draw.text((250, 148), code, fill="#111111", font=font)
    output = BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


def _test_code_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()
