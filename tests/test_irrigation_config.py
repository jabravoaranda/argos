from __future__ import annotations

import pytest

from argos.config.irrigation import (
    ArgosIrrigationConfigError,
    active_sectors_for_ev_ids,
    get_ev_for_sector,
    get_main_irrigation_ev,
    irrigation_sector_mappings,
)
from argos.config.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def configure_current_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_IRRIGATION_MAIN_EV", "8")
    monkeypatch.setenv("ARGOS_IRRIGATION_SECTOR_I_EV", "7")
    monkeypatch.setenv("ARGOS_IRRIGATION_SECTOR_II_EV", "6")
    monkeypatch.setenv("ARGOS_IRRIGATION_SECTOR_III_EV", "6")
    monkeypatch.setenv("ARGOS_IRRIGATION_SECTOR_IV_EV", "6")
    get_settings.cache_clear()


def test_irrigation_sector_mapping_loads_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_current_mapping(monkeypatch)

    mappings = irrigation_sector_mappings()

    assert [(mapping.sector_id, mapping.ev_id) for mapping in mappings] == [
        ("I", 7),
        ("II", 6),
        ("III", 6),
        ("IV", 6),
    ]
    assert get_ev_for_sector("I") == 7
    assert get_ev_for_sector("II") == 6
    assert get_ev_for_sector("III") == 6
    assert get_ev_for_sector("IV") == 6
    assert get_main_irrigation_ev() == 8


def test_irrigation_sector_mapping_allows_multiple_sectors_per_ev(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_current_mapping(monkeypatch)

    assert active_sectors_for_ev_ids((6,)) == ("II", "III", "IV")
    assert active_sectors_for_ev_ids((6, 7)) == ("I", "II", "III", "IV")


def test_irrigation_sector_mapping_changes_with_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_current_mapping(monkeypatch)
    assert get_ev_for_sector("III") == 6

    monkeypatch.setenv("ARGOS_IRRIGATION_SECTOR_III_EV", "8")
    get_settings.cache_clear()

    assert get_ev_for_sector("III") == 8
    assert active_sectors_for_ev_ids((8,)) == ("III",)


def test_irrigation_sector_mapping_fails_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        argos_admin_token="admin",
        ecowitt_ingest_token="ingest",
        argos_irrigation_sector_i_ev=7,
        argos_irrigation_sector_ii_ev=6,
        argos_irrigation_sector_iii_ev=6,
        argos_irrigation_sector_iv_ev=None,
    )

    with pytest.raises(ArgosIrrigationConfigError, match="ARGOS_IRRIGATION_SECTOR_IV_EV"):
        get_ev_for_sector("IV", settings)


def test_irrigation_sector_mapping_fails_when_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        argos_admin_token="admin",
        ecowitt_ingest_token="ingest",
        argos_irrigation_sector_i_ev=99,
        argos_irrigation_sector_ii_ev=6,
        argos_irrigation_sector_iii_ev=6,
        argos_irrigation_sector_iv_ev=6,
    )

    with pytest.raises(ArgosIrrigationConfigError, match="between 1 and 8"):
        get_ev_for_sector("I", settings)


def test_main_irrigation_ev_fails_when_invalid() -> None:
    settings = Settings(
        _env_file=None,
        argos_admin_token="admin",
        ecowitt_ingest_token="ingest",
        argos_irrigation_main_ev=99,
        argos_irrigation_sector_i_ev=7,
        argos_irrigation_sector_ii_ev=6,
        argos_irrigation_sector_iii_ev=6,
        argos_irrigation_sector_iv_ev=6,
    )

    with pytest.raises(ArgosIrrigationConfigError, match="ARGOS_IRRIGATION_MAIN_EV"):
        get_main_irrigation_ev(settings)
