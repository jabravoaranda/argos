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
from argos.models.argos_node import ArgosNodeFlowmeterMinute, ArgosNodeFlowmeterResetEvent, ArgosNodeFlowmeterSession
from argos.models.field_event import FieldEvent
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
    "ArgosNodeFlowmeterMinute",
    "ArgosNodeFlowmeterResetEvent",
    "ArgosNodeFlowmeterSession",
    "FieldEvent",
    "SatelliteAsset",
    "SatelliteMetric",
    "SatelliteObservation",
    "SatelliteSource",
    "SatelliteZone",
]
