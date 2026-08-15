from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy import func
from sqlalchemy.orm import Session

from argos.models.aemet import AemetSyncRun, WeatherDailyObservation, WeatherStation
from argos.services.aemet_normalizer import NormalizedAemetDailyObservation


class AemetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_station(
        self,
        *,
        external_id: str,
        name: str = "Álora",
        municipality: str | None = "Álora",
        province: str | None = "Málaga",
        latitude: float | None = None,
        longitude: float | None = None,
        altitude_m: float | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> WeatherStation:
        station = self.station_by_provider_external(provider="aemet", external_id=external_id)
        if station is None:
            station = WeatherStation(provider="aemet", external_id=external_id, name=name)
            self.session.add(station)
        station.name = name or station.name
        station.municipality = municipality
        station.province = province
        station.latitude = latitude
        station.longitude = longitude
        station.altitude_m = altitude_m
        station.metadata_json = metadata_json
        station.enabled = True
        self.session.flush()
        return station

    def station_by_provider_external(self, *, provider: str, external_id: str) -> WeatherStation | None:
        return self.session.scalar(
            select(WeatherStation).where(
                WeatherStation.provider == provider,
                WeatherStation.external_id == external_id,
            )
        )

    def stations(self, *, provider: str | None = None, limit: int = 100) -> list[WeatherStation]:
        statement = select(WeatherStation).order_by(WeatherStation.provider, WeatherStation.external_id).limit(limit)
        if provider is not None:
            statement = statement.where(WeatherStation.provider == provider)
        return list(self.session.scalars(statement).all())

    def daily_observations(
        self,
        *,
        station_id: int,
        start: date | None,
        end: date | None,
        limit: int,
        offset: int = 0,
    ) -> list[WeatherDailyObservation]:
        statement = (
            select(WeatherDailyObservation)
            .where(WeatherDailyObservation.station_id == station_id)
            .order_by(WeatherDailyObservation.observation_date, WeatherDailyObservation.id)
            .offset(offset)
            .limit(limit)
        )
        if start is not None:
            statement = statement.where(WeatherDailyObservation.observation_date >= start)
        if end is not None:
            statement = statement.where(WeatherDailyObservation.observation_date <= end)
        return list(self.session.scalars(statement).all())

    def upsert_daily_observation(
        self,
        *,
        station_id: int,
        normalized: NormalizedAemetDailyObservation,
        ingestion_run_id: int | None = None,
        ingestion_item_id: int | None = None,
    ) -> tuple[WeatherDailyObservation, str]:
        observation = self.session.scalar(
            select(WeatherDailyObservation).where(
                WeatherDailyObservation.station_id == station_id,
                WeatherDailyObservation.observation_date == normalized.observation_date,
            )
        )
        created = observation is None
        if observation is None:
            observation = WeatherDailyObservation(
                station_id=station_id,
                observation_date=normalized.observation_date,
                raw_payload_json={},
            )
            self.session.add(observation)

        changed = _apply_daily_observation(observation, normalized)
        if ingestion_run_id is not None:
            observation.ingestion_run_id = ingestion_run_id
        if ingestion_item_id is not None:
            observation.ingestion_item_id = ingestion_item_id
        self.session.flush()
        if created:
            return observation, "inserted"
        if changed:
            observation.updated_at = datetime.now(UTC)
            return observation, "updated"
        return observation, "skipped"

    def create_sync_run(
        self,
        *,
        station_id: int | None,
        station_external_id: str,
        mode: str,
        requested_start: date,
        requested_end: date,
        ingestion_run_id: int | None = None,
    ) -> AemetSyncRun:
        run = AemetSyncRun(
            station_id=station_id,
            station_external_id=station_external_id,
            mode=mode,
            requested_start=requested_start,
            requested_end=requested_end,
            status="running",
            started_at=datetime.now(UTC),
            intervals_json=[],
            errors_json=[],
            ingestion_run_id=ingestion_run_id,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def latest_sync_run(self, *, station_external_id: str | None = None) -> AemetSyncRun | None:
        statement = select(AemetSyncRun).order_by(desc(AemetSyncRun.started_at), desc(AemetSyncRun.id)).limit(1)
        if station_external_id is not None:
            statement = statement.where(AemetSyncRun.station_external_id == station_external_id)
        return self.session.scalar(statement)

    def observation_date_bounds(self, *, station_id: int) -> tuple[date | None, date | None]:
        return (
            self.session.scalar(
                select(func.min(WeatherDailyObservation.observation_date)).where(
                    WeatherDailyObservation.station_id == station_id
                )
            ),
            self.session.scalar(
                select(func.max(WeatherDailyObservation.observation_date)).where(
                    WeatherDailyObservation.station_id == station_id
                )
            ),
        )


def _apply_daily_observation(
    observation: WeatherDailyObservation,
    normalized: NormalizedAemetDailyObservation,
) -> bool:
    values = {
        "temperature_mean_c": normalized.temperature_mean_c,
        "temperature_min_c": normalized.temperature_min_c,
        "temperature_max_c": normalized.temperature_max_c,
        "precipitation_mm": normalized.precipitation_mm,
        "precipitation_trace": normalized.precipitation_trace,
        "wind_speed_mean_ms": normalized.wind_speed_mean_ms,
        "wind_gust_ms": normalized.wind_gust_ms,
        "wind_gust_direction": normalized.wind_gust_direction,
        "sunshine_hours": normalized.sunshine_hours,
        "pressure_max_hpa": normalized.pressure_max_hpa,
        "pressure_min_hpa": normalized.pressure_min_hpa,
        "humidity_mean_pct": normalized.humidity_mean_pct,
        "humidity_min_pct": normalized.humidity_min_pct,
        "humidity_max_pct": normalized.humidity_max_pct,
        "quality_flag": normalized.quality_flag,
        "raw_payload_json": normalized.raw_payload_json,
    }
    changed = False
    for key, value in values.items():
        if getattr(observation, key) != value:
            setattr(observation, key, value)
            changed = True
    return changed
