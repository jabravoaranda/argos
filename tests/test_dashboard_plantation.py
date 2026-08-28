from __future__ import annotations

from argos.dashboard.app import plantation_cell_label, selected_plant_from_matrix


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
