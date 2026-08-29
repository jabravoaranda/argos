from __future__ import annotations

from unittest.mock import Mock

from argos.dashboard.app import format_file_size, plantation_cell_label, render_plant_observation_form, selected_plant_from_matrix


def test_plantation_cell_label_distinguishes_plants_empty_and_infrastructure() -> None:
    plant_cell = {
        "plant": {"id": 1, "public_code": "18#", "species_label": "Ciruelo"},
        "displacement_marker": "#",
    }
    empty_cell = {"plant": None, "cell_type": "empty", "position_code": "17"}
    infrastructure_cell = {"plant": None, "cell_type": "infrastructure", "visible_code": "1B", "feature_label": "Bidón"}

    assert plantation_cell_label(plant_cell) == "18#"
    assert plantation_cell_label(empty_cell) == "17\n-"
    assert plantation_cell_label(infrastructure_cell) == "1B"


def test_selected_plant_from_matrix_returns_selected_tree() -> None:
    matrix = {
        "cells": [
            {"plant": {"id": 1, "public_code": "11"}},
            {"plant": {"id": 2, "public_code": "12"}},
        ]
    }

    assert selected_plant_from_matrix(matrix, 2)["public_code"] == "12"
    assert selected_plant_from_matrix(matrix, 3) is None


def test_format_file_size_for_photo_feedback() -> None:
    assert format_file_size(None) == "tamaño desconocido"
    assert format_file_size(512) == "0.5 KB"
    assert format_file_size(2 * 1024 * 1024) == "2.0 MB"


def test_plant_observation_submit_button_is_clickable_without_admin_token(monkeypatch) -> None:
    class FakeContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    submit_calls: list[dict] = []
    monkeypatch.setattr("argos.dashboard.app.st.form", lambda key: FakeContext())
    monkeypatch.setattr("argos.dashboard.app.st.text_input", lambda *args, **kwargs: "Observación 11")
    monkeypatch.setattr("argos.dashboard.app.st.text_area", lambda *args, **kwargs: "")
    monkeypatch.setattr("argos.dashboard.app.st.caption", lambda *args, **kwargs: None)
    monkeypatch.setattr("argos.dashboard.app.st.file_uploader", lambda *args, **kwargs: None)
    monkeypatch.setattr("argos.dashboard.app.st.camera_input", lambda *args, **kwargs: None)

    def fake_submit_button(*args, **kwargs):
        submit_calls.append(kwargs)
        return False

    monkeypatch.setattr("argos.dashboard.app.st.form_submit_button", fake_submit_button)

    render_plant_observation_form(Mock(admin_token=None), {"id": 1, "public_code": "11"})

    assert submit_calls == [{"type": "primary"}]
