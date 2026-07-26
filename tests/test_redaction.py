from __future__ import annotations

from argos.utils.redaction import REDACTED_VALUE, is_sensitive_key, redact_sensitive_values


def test_redact_sensitive_values_recursively() -> None:
    payload = {
        "PASSKEY": "secret",
        "stationtype": "GW2000A_V3.3.2",
        "nested": {
            "api_token": "secret-token",
            "values": [{"cookie": "session"}, {"temperature": 35.1}],
        },
    }

    redacted = redact_sensitive_values(payload)

    assert redacted == {
        "PASSKEY": REDACTED_VALUE,
        "stationtype": "GW2000A_V3.3.2",
        "nested": {
            "api_token": REDACTED_VALUE,
            "values": [{"cookie": REDACTED_VALUE}, {"temperature": 35.1}],
        },
    }
    assert payload["PASSKEY"] == "secret"


def test_sensitive_key_matching_is_case_insensitive_and_partial() -> None:
    assert is_sensitive_key("X-ARGOS-ADMIN-TOKEN") is True
    assert is_sensitive_key("Authorization") is True
    assert is_sensitive_key("stationtype") is False
