from dataclasses import dataclass

from argos.dashboard.pages.aemet import format_aemet_import_result, resolve_aemet_range, result_to_dict


def test_resolve_aemet_range_clamps_overlapping_global_range() -> None:
    resolved = resolve_aemet_range(
        start_date="2024-01-01",
        end_date="2026-12-31",
        bounds={"first_date": "2024-06-01", "last_date": "2026-09-19"},
    )

    assert resolved == ("2024-06-01", "2026-09-19", True)


def test_resolve_aemet_range_uses_recent_available_year_when_ranges_do_not_overlap() -> None:
    resolved = resolve_aemet_range(
        start_date="2020-01-01",
        end_date="2020-12-31",
        bounds={"first_date": "2023-01-01", "last_date": "2026-09-19"},
    )

    assert resolved == ("2025-09-19", "2026-09-19", False)


def test_resolve_aemet_range_preserves_selection_without_available_bounds() -> None:
    resolved = resolve_aemet_range(
        start_date="2026-01-01",
        end_date="2026-02-01",
        bounds={"first_date": None, "last_date": None},
    )

    assert resolved == ("2026-01-01", "2026-02-01", True)


def test_format_aemet_import_result_summarizes_counts_and_errors() -> None:
    result = {
        "status": "completed",
        "records_received": 12,
        "inserted": 8,
        "updated": 2,
        "skipped": 2,
        "errors": ["bad row"],
    }

    assert format_aemet_import_result(result) == (
        "AEMET completed: 12 recibidos, 8 insertados, 2 actualizados, 2 omitidos, 1 errores."
    )


def test_result_to_dict_keeps_import_service_contract() -> None:
    @dataclass
    class ImportResult:
        status: str = "completed"
        records_received: int = 3
        inserted: int = 1
        updated: int = 1
        skipped: int = 1
        errors: tuple[str, ...] = ()

    assert result_to_dict(ImportResult()) == {
        "status": "completed",
        "records_received": 3,
        "inserted": 1,
        "updated": 1,
        "skipped": 1,
        "errors": (),
    }
