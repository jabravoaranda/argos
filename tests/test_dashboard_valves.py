from __future__ import annotations

from argos.dashboard.app import (
    format_valve_state,
    valve_action_from_state,
    valve_phase_from_response,
    valve_phase_label,
)


def test_format_valve_state_uses_boolean_open_fields() -> None:
    assert format_valve_state({"open": True}) == "Open"
    assert format_valve_state({"is_open": False}) == "Closed"


def test_format_valve_state_normalizes_status_fields() -> None:
    assert format_valve_state({"state": "closed"}) == "Closed"
    assert format_valve_state({"status": "OPEN"}) == "Open"


def test_format_valve_state_prefers_boolean_state_fields_over_generic_status() -> None:
    assert format_valve_state({"status": "ok", "open": False}) == "Closed"
    assert format_valve_state({"status": "ok", "relay_active": True}) == "Open"


def test_valve_action_from_state_returns_only_available_action() -> None:
    assert valve_action_from_state({"open": False}) == "open"
    assert valve_action_from_state({"open": True}) == "close"
    assert valve_action_from_state({"state": "moving"}) is None


def test_valve_phase_from_response_uses_explicit_state_names() -> None:
    assert valve_phase_from_response({"state": "closed"}) == "closed"
    assert valve_phase_from_response({"state": "open"}) == "open"
    assert valve_phase_from_response({"state": "moving"}) == "unknown"


def test_valve_phase_label_renders_transitional_states() -> None:
    assert valve_phase_label("sending_open_command") == "Sending open command"
    assert valve_phase_label("opening") == "Opening"
    assert valve_phase_label("closing") == "Closing"
