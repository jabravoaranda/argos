from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from argos.api.external_errors import ExternalApiError
from argos.config.settings import Settings, get_settings


read_bearer = HTTPBearer(auto_error=False, scheme_name="ExternalReadBearer")
write_bearer = HTTPBearer(auto_error=False, scheme_name="ExternalWriteBearer")


@dataclass(frozen=True, slots=True)
class ExternalPrincipal:
    token_fingerprint: str
    scope: str


def require_external_read(
    credentials: HTTPAuthorizationCredentials | None = Depends(read_bearer),
    settings: Settings = Depends(get_settings),
) -> ExternalPrincipal:
    configured = [settings.argos_external_api_read_token, settings.argos_external_api_write_token]
    return _authenticate(credentials, configured=configured, known=configured, scope="read")


def require_external_write(
    credentials: HTTPAuthorizationCredentials | None = Depends(write_bearer),
    settings: Settings = Depends(get_settings),
) -> ExternalPrincipal:
    return _authenticate(
        credentials,
        configured=[settings.argos_external_api_write_token],
        known=[settings.argos_external_api_read_token, settings.argos_external_api_write_token],
        scope="write",
    )


def _authenticate(
    credentials: HTTPAuthorizationCredentials | None,
    *,
    configured: list[str | None],
    known: list[str | None],
    scope: str,
) -> ExternalPrincipal:
    available = [token for token in configured if token]
    if not available:
        raise ExternalApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="external_api_not_configured",
            message="External API authentication is not configured.",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ExternalApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="missing_bearer_token",
            message="A Bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not any(hmac.compare_digest(credentials.credentials, token) for token in available):
        known_tokens = [token for token in known if token]
        if any(hmac.compare_digest(credentials.credentials, token) for token in known_tokens):
            raise ExternalApiError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="insufficient_scope",
                message=f"The Bearer token does not grant {scope} access.",
            )
        raise ExternalApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_bearer_token",
            message="The Bearer token is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    fingerprint = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    return ExternalPrincipal(token_fingerprint=fingerprint, scope=scope)
