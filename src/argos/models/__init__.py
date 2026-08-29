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
from argos.models.argos_node import (
    ArgosIrrigationSectorMinuteAttribution,
    ArgosNodeFlowmeterMinute,
    ArgosNodeFlowmeterResetEvent,
    ArgosNodeFlowmeterSession,
)
from argos.models.field_event import FieldEvent, FieldEventPhoto
from argos.models.ingestion import DataSource, IngestionItem, IngestionRun, SourceArtifact, SyncCursor
from argos.models.plants import FieldEventPlantUnit, PlantIrrigationLine, PlantMatrixCell, PlantParcel, PlantUnit
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
    "ArgosIrrigationSectorMinuteAttribution",
    "ArgosNodeFlowmeterResetEvent",
    "ArgosNodeFlowmeterSession",
    "FieldEvent",
    "FieldEventPhoto",
    "FieldEventPlantUnit",
    "PlantIrrigationLine",
    "PlantMatrixCell",
    "PlantParcel",
    "PlantUnit",
    "DataSource",
    "IngestionItem",
    "IngestionRun",
    "SourceArtifact",
    "SyncCursor",
    "SatelliteAsset",
    "SatelliteMetric",
    "SatelliteObservation",
    "SatelliteSource",
    "SatelliteZone",
]
