from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from argos.config.settings import Settings, get_settings
from argos.models.field_event import FieldEvent, FieldEventPhoto
from argos.models.plants import PlantUnit
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
WHATSAPP_DATETIME_RE = re.compile(r"WhatsApp Image (?P<date>\d{4}-\d{2}-\d{2}) at (?P<time>\d{2}\.\d{2}\.\d{2})", re.IGNORECASE)
FILENAME_DATETIME_PATTERNS = (
    re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})[_ -](?P<time>\d{2}[._-]\d{2}[._-]\d{2})"),
    re.compile(r"(?P<date>\d{8})[_-](?P<time>\d{6})"),
)


@dataclass(frozen=True, slots=True)
class FieldEventPhotoInput:
    filename: str
    content_type: str
    data_base64: str


@dataclass(frozen=True, slots=True)
class PlantCodeResolverResult:
    detected_code: str | None
    confidence: float
    resolver: str
    diagnostics: dict[str, str]


class PlantCodeResolver:
    def resolve(self, *, filename: str, content: bytes, candidate_codes: set[str]) -> PlantCodeResolverResult:
        raise NotImplementedError


class FilenamePlantCodeResolver(PlantCodeResolver):
    def resolve(self, *, filename: str, content: bytes, candidate_codes: set[str]) -> PlantCodeResolverResult:
        del content
        normalized_filename = _normalize_code_text(filename)
        exact_matches = [code for code in candidate_codes if re.search(rf"(?<![0-9A-Z]){re.escape(code)}(?![0-9A-Z])", normalized_filename)]
        if len(exact_matches) == 1:
            return PlantCodeResolverResult(exact_matches[0], 0.95, "filename", {"match": "exact"})
        if len(exact_matches) > 1:
            return PlantCodeResolverResult(None, 0.45, "filename", {"match": "ambiguous"})
        loose_matches = [code for code in candidate_codes if code in normalized_filename]
        if len(loose_matches) == 1:
            return PlantCodeResolverResult(loose_matches[0], 0.72, "filename", {"match": "loose"})
        detected_tokens = re.findall(r"(?<![0-9A-Z])([1-9A-C][1-9A-C]#?)(?![0-9A-Z])", normalized_filename)
        unique_tokens = sorted(set(detected_tokens))
        if len(unique_tokens) == 1:
            return PlantCodeResolverResult(unique_tokens[0], 0.6, "filename", {"match": "unresolved_code"})
        if len(unique_tokens) > 1:
            return PlantCodeResolverResult(None, 0.35, "filename", {"match": "ambiguous_code"})
        return PlantCodeResolverResult(None, 0.0, "filename", {"match": "none"})


class QRPlantCodeResolver(PlantCodeResolver):
    def resolve(self, *, filename: str, content: bytes, candidate_codes: set[str]) -> PlantCodeResolverResult:
        del filename
        decoded_values = _decode_qr_values(content)
        for value in decoded_values:
            match = re.fullmatch(r"\s*P:(?P<code>[0-9A-Za-z#]+)\s*", value)
            if not match:
                continue
            detected_code = match.group("code").upper()
            if detected_code in candidate_codes:
                return PlantCodeResolverResult(detected_code, 0.99, "qr", {"match": "plant_code", "payload": value})
            return PlantCodeResolverResult(detected_code, 0.4, "qr", {"match": "unknown_plant_code", "payload": value})
        if decoded_values:
            return PlantCodeResolverResult(None, 0.2, "qr", {"match": "unsupported_payload", "payload": decoded_values[0]})
        return PlantCodeResolverResult(None, 0.0, "qr", {"match": "none"})


class CatalogVisualPlantCodeResolver(PlantCodeResolver):
    def resolve(self, *, filename: str, content: bytes, candidate_codes: set[str]) -> PlantCodeResolverResult:
        del filename
        if not candidate_codes:
            return PlantCodeResolverResult(None, 0.0, "vision", {"match": "empty_catalog"})
        try:
            with Image.open(BytesIO(content)) as image:
                oriented = ImageOps.exif_transpose(image).convert("L")
        except Exception:
            return PlantCodeResolverResult(None, 0.0, "vision", {"match": "unreadable_image"})
        best_code, best_score = _match_catalog_code_visual(oriented, candidate_codes)
        if best_code is None:
            return PlantCodeResolverResult(None, 0.0, "vision", {"match": "none"})
        if best_score >= 0.72:
            return PlantCodeResolverResult(best_code, best_score, "vision", {"match": "catalog_template", "score": f"{best_score:.3f}"})
        return PlantCodeResolverResult(best_code, best_score, "vision", {"match": "low_confidence", "score": f"{best_score:.3f}"})


class CompositePlantCodeResolver(PlantCodeResolver):
    def __init__(self, resolvers: list[PlantCodeResolver] | None = None) -> None:
        self.resolvers = resolvers or [QRPlantCodeResolver(), CatalogVisualPlantCodeResolver(), FilenamePlantCodeResolver()]

    def resolve(self, *, filename: str, content: bytes, candidate_codes: set[str]) -> PlantCodeResolverResult:
        diagnostics: dict[str, str] = {}
        best = PlantCodeResolverResult(None, 0.0, "none", {"match": "none"})
        for resolver in self.resolvers:
            result = resolver.resolve(filename=filename, content=content, candidate_codes=candidate_codes)
            diagnostics[result.resolver] = result.diagnostics.get("match", "")
            if result.detected_code in candidate_codes and result.confidence >= 0.9:
                return PlantCodeResolverResult(result.detected_code, result.confidence, result.resolver, {**result.diagnostics, "pipeline": str(diagnostics)})
            if result.confidence > best.confidence:
                best = result
        return PlantCodeResolverResult(best.detected_code, best.confidence, best.resolver, {**best.diagnostics, "pipeline": str(diagnostics)})


@dataclass(frozen=True, slots=True)
class StagedPlantPhoto:
    filename: str
    content_type: str
    data_base64: str
    sha256: str
    size_bytes: int
    taken_at: datetime | None
    date_source: str
    detected_code: str | None
    confidence: float
    resolver: str
    status: str
    diagnostics: dict[str, str]
    plant_id: int | None
    plant_public_code: str | None
    matrix_position_code: str | None
    species: str | None
    irrigation_sector_id: str | None
    duplicate: bool


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
    taken_at, date_source = capture_datetime_for_photo(content, filename=photo.filename, fallback=None, settings=settings)
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


def stage_plant_photos(
    *,
    session: Session,
    photos: list[FieldEventPhotoInput],
    fallback_date: datetime | None,
    resolver: PlantCodeResolver | None = None,
    settings: Settings | None = None,
) -> list[StagedPlantPhoto]:
    settings = settings or get_settings()
    resolver = resolver or CompositePlantCodeResolver()
    plants = list(session.scalars(select(PlantUnit)).all())
    plants_by_code = {plant.public_code.upper(): plant for plant in plants}
    existing_hashes = set(session.scalars(select(FieldEventPhoto.sha256)).all())
    legacy_hashes = set(session.scalars(select(FieldEvent.photo_sha256).where(FieldEvent.photo_sha256.is_not(None))).all())
    staged: list[StagedPlantPhoto] = []
    seen_hashes: set[str] = set()
    for photo in photos:
        content_type, content = decode_photo(photo)
        checksum = hashlib.sha256(content).hexdigest()
        taken_at, date_source = capture_datetime_for_photo(content, filename=photo.filename, fallback=fallback_date, settings=settings)
        resolver_result = resolver.resolve(filename=photo.filename, content=content, candidate_codes=set(plants_by_code))
        detected_code = resolver_result.detected_code.upper() if resolver_result.detected_code else None
        plant = plants_by_code.get(detected_code or "")
        duplicate = checksum in existing_hashes or checksum in legacy_hashes or checksum in seen_hashes
        status = _stage_status(
            plant=plant,
            duplicate=duplicate,
            confidence=resolver_result.confidence,
            detected_code=detected_code,
            resolver=resolver_result.resolver,
            diagnostics=resolver_result.diagnostics,
        )
        staged.append(
            StagedPlantPhoto(
                filename=photo.filename,
                content_type=content_type,
                data_base64=base64.b64encode(content).decode("ascii"),
                sha256=checksum,
                size_bytes=len(content),
                taken_at=taken_at,
                date_source=date_source,
                detected_code=detected_code,
                confidence=resolver_result.confidence,
                resolver=resolver_result.resolver,
                status=status,
                diagnostics=resolver_result.diagnostics,
                plant_id=plant.id if plant else None,
                plant_public_code=plant.public_code if plant else None,
                matrix_position_code=plant.matrix_position_code if plant else None,
                species=plant.species if plant else None,
                irrigation_sector_id=plant.irrigation_sector_id if plant else None,
                duplicate=duplicate,
            )
        )
        seen_hashes.add(checksum)
    return staged


def add_event_photo_item(
    *,
    event: FieldEvent,
    photo: FieldEventPhotoInput,
    date_source: str,
    taken_at: datetime | None = None,
    detected_code: str | None = None,
    resolver_confidence: float | None = None,
    settings: Settings | None = None,
) -> FieldEventPhoto:
    settings = settings or get_settings()
    content_type, content = decode_photo(photo)
    checksum = hashlib.sha256(content).hexdigest()
    inferred_taken_at, inferred_date_source = capture_datetime_for_photo(content, filename=photo.filename, fallback=None, settings=settings)
    photo_taken_at = _as_utc(taken_at) if taken_at is not None else inferred_taken_at
    storage_path = _photo_storage_path(
        event_id=event.id,
        checksum=checksum,
        extension=ALLOWED_PHOTO_MIME_TYPES[content_type],
        settings=settings,
    )
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)
    item = FieldEventPhoto(
        field_event_id=event.id,
        storage_path=storage_path_for_sql(storage_path, settings=settings),
        mime_type=content_type,
        original_filename=_safe_filename(photo.filename),
        size_bytes=len(content),
        sha256=checksum,
        taken_at=photo_taken_at,
        date_source=date_source if date_source != "unknown" else inferred_date_source,
        detected_code=detected_code,
        resolver_confidence=resolver_confidence,
    )
    return item


def decode_photo(photo: FieldEventPhotoInput) -> tuple[str, bytes]:
    content_type = _normalize_content_type(photo.content_type or mimetypes.guess_type(photo.filename)[0] or "")
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
    return content_type, content


def capture_datetime_for_photo(
    content: bytes,
    *,
    filename: str,
    fallback: datetime | None,
    settings: Settings | None = None,
) -> tuple[datetime | None, str]:
    exif_taken_at = extract_photo_taken_at(content, settings=settings)
    if exif_taken_at is not None:
        return exif_taken_at, "exif"
    filename_taken_at = extract_filename_taken_at(filename, settings=settings)
    if filename_taken_at is not None:
        return filename_taken_at, "filename"
    if fallback is not None:
        return _as_utc(fallback), "batch"
    return None, "unknown"


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


def extract_filename_taken_at(filename: str, *, settings: Settings | None = None) -> datetime | None:
    settings = settings or get_settings()
    match = WHATSAPP_DATETIME_RE.search(filename)
    if match:
        return _local_filename_datetime(match.group("date"), match.group("time").replace(".", ":"), settings=settings)
    for pattern in FILENAME_DATETIME_PATTERNS:
        match = pattern.search(filename)
        if not match:
            continue
        date_text = match.group("date")
        time_text = match.group("time")
        if len(date_text) == 8:
            date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"
        time_text = time_text.replace(".", ":").replace("_", ":").replace("-", ":")
        parsed = _local_filename_datetime(date_text, time_text, settings=settings)
        if parsed is not None:
            return parsed
    return None


def thumbnail_data_url(data_base64: str, content_type: str, *, max_size: tuple[int, int] = (240, 240)) -> str:
    try:
        content = base64.b64decode(data_base64, validate=True)
        with Image.open(BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(max_size)
            output = BytesIO()
            output_format = "JPEG" if _normalize_content_type(content_type) == "image/jpeg" else "PNG"
            image.save(output, format=output_format)
            thumbnail_mime = "image/jpeg" if output_format == "JPEG" else "image/png"
            return f"data:{thumbnail_mime};base64,{base64.b64encode(output.getvalue()).decode('ascii')}"
    except Exception:
        return f"data:{content_type};base64,{data_base64}"


def field_event_photo_root(settings: Settings | None = None) -> Path:
    return data_paths(settings).processed / "field-events" / "photos"


def _photo_storage_path(*, event_id: int, checksum: str, extension: str, settings: Settings) -> Path:
    today = datetime.now(UTC)
    filename = f"field-event-{event_id}-{checksum[:12]}{extension}"
    return field_event_photo_root(settings) / f"{today.year:04d}" / f"{today.month:02d}" / filename


def _normalize_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _stage_status(
    *,
    plant: PlantUnit | None,
    duplicate: bool,
    confidence: float,
    detected_code: str | None,
    resolver: str,
    diagnostics: dict[str, str],
) -> str:
    if duplicate:
        return "duplicate"
    reliable_resolver_match = resolver == "qr" and confidence >= 0.99
    reliable_resolver_match = reliable_resolver_match or (resolver == "vision" and diagnostics.get("match") == "catalog_template")
    reliable_resolver_match = reliable_resolver_match or confidence >= 0.9
    if plant is not None and reliable_resolver_match:
        return "matched"
    if detected_code is not None or confidence > 0:
        return "review"
    return "unassigned"


def _normalize_code_text(value: str) -> str:
    return re.sub(r"[^0-9A-Z#]+", " ", value.upper())


def _decode_qr_values(content: bytes) -> list[str]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    try:
        with Image.open(BytesIO(content)) as image:
            oriented = ImageOps.exif_transpose(image).convert("RGB")
        array = cv2.cvtColor(np.array(oriented), cv2.COLOR_RGB2BGR)
        detector = cv2.QRCodeDetector()
        decoded: list[str] = []
        ok, values, _points, _straight = detector.detectAndDecodeMulti(array)
        if ok and values:
            decoded.extend(value for value in values if value)
        if not decoded:
            value, _points, _straight = detector.detectAndDecode(array)
            if value:
                decoded.append(value)
        return decoded
    except Exception:
        return []


def _match_catalog_code_visual(image: Image.Image, candidate_codes: set[str]) -> tuple[str | None, float]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return None, 0.0
    scale = min(1.0, 1200 / max(image.size))
    if scale < 1:
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    image_array = np.array(ImageOps.autocontrast(image))
    _, thresholded = cv2.threshold(image_array, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    best_code: str | None = None
    best_score = 0.0
    for code in sorted(candidate_codes):
        for template in _code_templates(code):
            template_array = np.array(template)
            if template_array.shape[0] >= thresholded.shape[0] or template_array.shape[1] >= thresholded.shape[1]:
                continue
            result = cv2.matchTemplate(thresholded, template_array, cv2.TM_CCOEFF_NORMED)
            _, max_value, _, _ = cv2.minMaxLoc(result)
            if max_value > best_score:
                best_code = code
                best_score = float(max_value)
    return best_code, best_score


def _code_templates(code: str) -> list[Image.Image]:
    templates: list[Image.Image] = []
    for font_size in (32, 44, 58, 72, 88, 108, 132):
        font = _code_font(font_size)
        text_bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), code, font=font)
        width = text_bbox[2] - text_bbox[0] + 18
        height = text_bbox[3] - text_bbox[1] + 18
        image = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(image)
        draw.text((9 - text_bbox[0], 9 - text_bbox[1]), code, fill=255, font=font)
        templates.append(image)
    return templates


def _code_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _local_filename_datetime(date_text: str, time_text: str, *, settings: Settings) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(f"{date_text}T{time_text}")
    except ValueError:
        return None
    return parsed.replace(tzinfo=ZoneInfo(settings.local_timezone)).astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo(get_settings().local_timezone)).astimezone(UTC)
    return value.astimezone(UTC)


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
