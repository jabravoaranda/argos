from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from argos.config.settings import Settings, get_settings
from argos.models.field_event import FieldEvent
from argos.services.data_layout import data_paths, storage_path_for_sql

ALLOWED_PHOTO_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_FIELD_EVENT_PHOTO_BYTES = 10 * 1024 * 1024
EXIF_DATETIME_TAGS = (36867, 36868, 306)
EXIF_OFFSET_TAGS = {
    36867: 36881,
    36868: 36882,
    306: 36880,
}


@dataclass(frozen=True, slots=True)
class FieldEventPhotoInput:
    filename: str
    content_type: str
    data_base64: str


def attach_field_event_photo(
    event: FieldEvent,
    photo: FieldEventPhotoInput,
    *,
    settings: Settings | None = None,
) -> FieldEvent:
    settings = settings or get_settings()
    content_type = _normalize_content_type(photo.content_type)
    if content_type not in ALLOWED_PHOTO_MIME_TYPES:
        raise ValueError("La foto debe ser JPG, PNG o WebP.")
    try:
        content = base64.b64decode(photo.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("La foto recibida no es válida.") from exc
    if not content:
        raise ValueError("La foto está vacía.")
    if len(content) > MAX_FIELD_EVENT_PHOTO_BYTES:
        raise ValueError("La foto supera el límite de 10 MB.")

    checksum = hashlib.sha256(content).hexdigest()
    taken_at = extract_photo_taken_at(content, settings=settings)
    storage_path = _photo_storage_path(
        event_id=event.id,
        checksum=checksum,
        extension=ALLOWED_PHOTO_MIME_TYPES[content_type],
        settings=settings,
    )
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)

    event.photo_storage_path = storage_path_for_sql(storage_path, settings=settings)
    event.photo_mime_type = content_type
    event.photo_original_filename = _safe_filename(photo.filename)
    event.photo_size_bytes = len(content)
    event.photo_sha256 = checksum
    event.photo_taken_at = taken_at
    if taken_at is not None:
        event.occurred_at = taken_at
    return event


def extract_photo_taken_at(content: bytes, *, settings: Settings | None = None) -> datetime | None:
    settings = settings or get_settings()
    try:
        with Image.open(BytesIO(content)) as image:
            exif = image.getexif()
    except Exception:
        return None
    if not exif:
        return None
    for tag in EXIF_DATETIME_TAGS:
        raw_value = exif.get(tag)
        if not raw_value:
            continue
        parsed = _parse_exif_datetime(str(raw_value), offset=str(exif.get(EXIF_OFFSET_TAGS[tag]) or ""), settings=settings)
        if parsed is not None:
            return parsed
    return None


def field_event_photo_root(settings: Settings | None = None) -> Path:
    return data_paths(settings).processed / "field-events" / "photos"


def _photo_storage_path(*, event_id: int, checksum: str, extension: str, settings: Settings) -> Path:
    today = datetime.now(UTC)
    filename = f"field-event-{event_id}-{checksum[:12]}{extension}"
    return field_event_photo_root(settings) / f"{today.year:04d}" / f"{today.month:02d}" / filename


def _normalize_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _parse_exif_datetime(value: str, *, offset: str, settings: Settings) -> datetime | None:
    try:
        parsed = datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    offset = offset.strip()
    if re.fullmatch(r"[+-]\d{2}:\d{2}", offset):
        return datetime.fromisoformat(f"{parsed.isoformat()}{offset}").astimezone(UTC)
    return parsed.replace(tzinfo=ZoneInfo(settings.local_timezone)).astimezone(UTC)


def _safe_filename(value: str) -> str:
    filename = Path(value.strip()).name
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", filename)[:255] or "foto"
