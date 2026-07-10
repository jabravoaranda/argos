from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REDACTED_VALUE = "<redacted>"
SENSITIVE_KEY_PARTS = ("passkey", "password", "token", "secret", "key", "authorization", "cookie")


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED_VALUE if is_sensitive_key(str(key)) else redact_sensitive_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_values(item) for item in value)
    return value


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)
