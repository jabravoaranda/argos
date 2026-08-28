from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from typing import Literal

from argos.config.settings import Settings, get_settings


IrrigationSectorId = Literal["I", "II", "III", "IV"]
IRRIGATION_SECTOR_IDS: tuple[IrrigationSectorId, ...] = ("I", "II", "III", "IV")
VALID_IRRIGATION_EV_IDS = frozenset(range(1, 9))


class ArgosIrrigationConfigError(ValueError):
    """Raised when irrigation sector configuration is incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class IrrigationSectorValveMapping:
    sector_id: IrrigationSectorId
    sector_name: str
    ev_id: int

    @property
    def technical_id(self) -> str:
        return f"EV{self.ev_id}"


def irrigation_sector_mappings(settings: Settings | None = None) -> tuple[IrrigationSectorValveMapping, ...]:
    settings = settings or get_settings()
    return tuple(
        IrrigationSectorValveMapping(
            sector_id=sector_id,
            sector_name=f"Sector {sector_id}",
            ev_id=_configured_ev_id(settings, sector_id),
        )
        for sector_id in IRRIGATION_SECTOR_IDS
    )


def get_ev_for_sector(sector_id: IrrigationSectorId, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    if sector_id not in IRRIGATION_SECTOR_IDS:
        raise ArgosIrrigationConfigError(f"Unknown irrigation sector: {sector_id}.")
    return _configured_ev_id(settings, sector_id)


def get_main_irrigation_ev(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    configured = settings.argos_irrigation_main_ev
    if configured not in VALID_IRRIGATION_EV_IDS:
        raise ArgosIrrigationConfigError("ARGOS_IRRIGATION_MAIN_EV must be an integer EV id between 1 and 8.")
    return configured


def active_sectors_for_ev_ids(open_ev_ids: Iterable[int], settings: Settings | None = None) -> tuple[IrrigationSectorId, ...]:
    open_ev_id_set = set(open_ev_ids)
    if not open_ev_id_set:
        return ()
    return tuple(mapping.sector_id for mapping in irrigation_sector_mappings(settings) if mapping.ev_id in open_ev_id_set)


def _configured_ev_id(settings: Settings, sector_id: IrrigationSectorId) -> int:
    attribute_name = f"argos_irrigation_sector_{sector_id.lower()}_ev"
    configured = getattr(settings, attribute_name)
    env_name = f"ARGOS_IRRIGATION_SECTOR_{sector_id}_EV"
    if configured is None:
        raise ArgosIrrigationConfigError(f"{env_name} must be configured before operating irrigation sector {sector_id}.")
    if configured not in VALID_IRRIGATION_EV_IDS:
        raise ArgosIrrigationConfigError(f"{env_name} must be an integer EV id between 1 and 8.")
    return configured
