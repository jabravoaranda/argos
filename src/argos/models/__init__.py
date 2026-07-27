"""SQLAlchemy ORM models."""

from argos.models.ecowitt import (
    DailyStatistic,
    DataGap,
    EcowittCloudRawReport,
    EcowittRawReport,
    Gateway,
    GatewayAlias,
    IngestionEvent,
    Station,
    UnknownField,
    WeatherObservation,
    WeeklyStatistic,
)
from argos.models.aemet import AemetSyncRun, WeatherDailyObservation, WeatherStation
from argos.models.satellite import (
    SatelliteAsset,
    SatelliteMetric,
    SatelliteObservation,
    SatelliteSource,
    SatelliteZone,
)

__all__ = [
    "DailyStatistic",
    "DataGap",
    "EcowittCloudRawReport",
    "EcowittRawReport",
    "Gateway",
    "GatewayAlias",
    "IngestionEvent",
    "Station",
    "UnknownField",
    "WeatherObservation",
    "WeeklyStatistic",
    "AemetSyncRun",
    "WeatherDailyObservation",
    "WeatherStation",
    "SatelliteAsset",
    "SatelliteMetric",
    "SatelliteObservation",
    "SatelliteSource",
    "SatelliteZone",
]
