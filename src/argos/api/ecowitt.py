from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from argos.config.settings import Settings, get_settings
from argos.database.session import get_db_session
from argos.services.ecowitt_capture import capture_ecowitt_payload
from argos.utils.redaction import REDACTED_VALUE, is_sensitive_key

router = APIRouter(prefix="/api/v1/ecowitt", tags=["ecowitt"])


@router.post("/upload/{token}")
async def upload_ecowitt_report(
    token: str,
    request: Request,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not hmac.compare_digest(token, settings.ecowitt_ingest_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid ingestion token.")

    captured_request = await _extract_payload(request)
    payload = captured_request.payload
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty Ecowitt payload.")

    result = capture_ecowitt_payload(
        session=session,
        payload=payload,
        raw_body_text=captured_request.raw_body_text,
        http_method=request.method,
        source_ip=request.client.host if request.client else None,
        content_type=request.headers.get("content-type"),
        headers=_safe_headers(request.headers),
        query_string=request.url.query or None,
    )
    return {
        "status": "ok",
        "duplicate": result.duplicate,
        "raw_report_id": result.raw_report_id,
        "observation_id": result.observation_id,
        "payload_key_count": len(result.payload_keys),
        "payload_keys": result.payload_keys,
        "warnings": result.warnings,
        "unknown_field_count": result.unknown_field_count,
    }


class CapturedRequest:
    def __init__(self, payload: dict[str, Any], raw_body_text: str | None) -> None:
        self.payload = payload
        self.raw_body_text = raw_body_text


async def _extract_payload(request: Request) -> CapturedRequest:
    payload: dict[str, Any] = dict(request.query_params)
    body = await request.body()
    if not body:
        return CapturedRequest(payload=payload, raw_body_text=None)

    raw_body_text = body.decode("utf-8", errors="replace")
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            parsed_json = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload.") from exc
        if not isinstance(parsed_json, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ecowitt payload must be an object.")
        payload.update(parsed_json)
        return CapturedRequest(payload=payload, raw_body_text=raw_body_text)

    parsed_form = dict(parse_qsl(raw_body_text, keep_blank_values=True))
    payload.update(parsed_form)
    return CapturedRequest(payload=payload, raw_body_text=raw_body_text)


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: (REDACTED_VALUE if is_sensitive_key(key) else value) for key, value in headers.items()}
