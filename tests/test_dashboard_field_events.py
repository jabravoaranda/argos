from __future__ import annotations

import base64
from datetime import date, time

import pytest

from argos.dashboard.app import (
    field_event_form_payload,
    field_event_quantity_label,
    field_event_row_html,
    field_events_csv,
    parse_optional_float,
    uploaded_photo_payload,
)


EVENT_TYPE_LABELS = {"irrigation": "Riego"}
ZONE_LABELS = {"olivos_pequenos": "Olivos pequeños"}


def test_field_event_form_payload_builds_manual_event() -> None:
    payload = field_event_form_payload(
        event_date=date(2026, 8, 1),
        event_time=time(10, 30),
        event_type="irrigation",
        title=" Riego norte ",
        description="  una hora ",
        zone_slug="olivos_pequenos",
        tree_reference=" fila 2 ",
        quantity_text="12,5",
        unit=" m3 ",
    )

    assert payload["event_type"] == "irrigation"
    assert payload["title"] == "Riego norte"
    assert payload["description"] == "una hora"
    assert payload["zone_slug"] == "olivos_pequenos"
    assert payload["tree_reference"] == "fila 2"
    assert payload["quantity"] == 12.5
    assert payload["unit"] == "m3"
    assert payload["source"] == "manual"


def test_field_event_form_payload_rejects_unit_without_quantity() -> None:
    with pytest.raises(ValueError, match="unidad requiere"):
        field_event_form_payload(
            event_date=date(2026, 8, 1),
            event_time=time(10, 30),
            event_type="irrigation",
            title="Riego",
            description="",
            zone_slug="",
            tree_reference="",
            quantity_text="",
            unit="m3",
        )


def test_field_event_row_and_csv_use_spanish_labels() -> None:
    row = {
        "occurred_at": "2026-08-01T08:30:00Z",
        "event_type": "irrigation",
        "title": "Riego norte",
        "description": None,
        "zone_slug": "olivos_pequenos",
        "tree_reference": None,
        "quantity": 12.5,
        "unit": "m3",
        "source": "manual",
    }

    html = field_event_row_html(row, event_type_labels=EVENT_TYPE_LABELS, zone_labels=ZONE_LABELS)
    csv_bytes = field_events_csv([row], event_type_labels=EVENT_TYPE_LABELS, zone_labels=ZONE_LABELS)

    assert "Riego" in html
    assert "Olivos pequeños" in html
    assert "12.5 m3" in html
    assert "Fecha y hora,Tipo,Título,Zona" in csv_bytes.decode("utf-8-sig")
    assert "Riego norte" in csv_bytes.decode("utf-8-sig")


def test_field_event_quantity_and_float_helpers() -> None:
    assert parse_optional_float("1,25") == 1.25
    assert parse_optional_float("") is None
    assert field_event_quantity_label(None, None) == "—"
    assert field_event_quantity_label(2, "kg") == "2 kg"


def test_uploaded_photo_payload_encodes_file() -> None:
    class FakeUpload:
        name = "arbol.jpg"
        type = "image/jpeg"

        def getvalue(self) -> bytes:
            return b"photo-bytes"

    payload = uploaded_photo_payload(FakeUpload())

    assert payload == {
        "filename": "arbol.jpg",
        "content_type": "image/jpeg",
        "data_base64": base64.b64encode(b"photo-bytes").decode("ascii"),
    }
