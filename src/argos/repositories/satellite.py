from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from argos.models.satellite import SatelliteAsset, SatelliteMetric, SatelliteObservation, SatelliteSource, SatelliteZone
from argos.services.satellite_indices import SENTINEL_2_COLLECTION, SENTINEL_2_SOURCE_CODE


class SatelliteRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_sentinel2_source(self) -> SatelliteSource:
        source = self.session.scalar(select(SatelliteSource).where(SatelliteSource.code == SENTINEL_2_SOURCE_CODE))
        if source is None:
            source = SatelliteSource(
                code=SENTINEL_2_SOURCE_CODE,
                name="Sentinel-2 Level-2A",
                provider="Copernicus Data Space Ecosystem",
                collection=SENTINEL_2_COLLECTION,
                spatial_resolution_m=10.0,
                enabled=True,
            )
            self.session.add(source)
            self.session.flush()
        return source

    def get_or_create_zone(
        self,
        *,
        name: str,
        geometry_geojson: dict[str, Any],
        geometry_hash: str,
        area_m2: float | None,
    ) -> SatelliteZone:
        zone = self.session.scalar(select(SatelliteZone).where(SatelliteZone.geometry_hash == geometry_hash))
        if zone is None:
            zone = SatelliteZone(
                name=name,
                geometry_geojson=geometry_geojson,
                geometry_hash=geometry_hash,
                crs="EPSG:4326",
                area_m2=area_m2,
                enabled=True,
            )
            self.session.add(zone)
            self.session.flush()
            return zone
        zone.name = name or zone.name
        zone.geometry_geojson = geometry_geojson
        zone.area_m2 = area_m2
        zone.enabled = True
        return zone

    def sources(self) -> list[SatelliteSource]:
        return list(self.session.scalars(select(SatelliteSource).order_by(SatelliteSource.code)).all())

    def zones(self, *, enabled_only: bool = False) -> list[SatelliteZone]:
        statement = select(SatelliteZone).order_by(SatelliteZone.name, SatelliteZone.id)
        if enabled_only:
            statement = statement.where(SatelliteZone.enabled.is_(True))
        return list(self.session.scalars(statement).all())

    def observation_count(self, *, zone_id: int | None = None, quality_status: str | None = None) -> int:
        statement = select(func.count(SatelliteObservation.id))
        if zone_id is not None:
            statement = statement.where(SatelliteObservation.zone_id == zone_id)
        if quality_status is not None:
            statement = statement.where(SatelliteObservation.quality_status == quality_status)
        return int(self.session.scalar(statement) or 0)

    def observation_bounds(
        self,
        *,
        zone_id: int | None = None,
        quality_status: str | None = None,
    ) -> tuple[datetime | None, datetime | None]:
        statement = select(
            func.min(SatelliteObservation.acquisition_time),
            func.max(SatelliteObservation.acquisition_time),
        )
        if zone_id is not None:
            statement = statement.where(SatelliteObservation.zone_id == zone_id)
        if quality_status is not None:
            statement = statement.where(SatelliteObservation.quality_status == quality_status)
        row = self.session.execute(statement).one()
        return row[0], row[1]

    def latest_observation_timestamps(self, *, zone_id: int | None = None) -> tuple[datetime, datetime | None, datetime] | None:
        statement = (
            select(
                SatelliteObservation.acquisition_time,
                SatelliteObservation.updated_at,
                SatelliteObservation.created_at,
            )
            .order_by(desc(SatelliteObservation.acquisition_time), desc(SatelliteObservation.id))
            .limit(1)
        )
        if zone_id is not None:
            statement = statement.where(SatelliteObservation.zone_id == zone_id)
        row = self.session.execute(statement).one_or_none()
        if row is None:
            return None
        return row[0], row[1], row[2]

    def observation_by_external_key(
        self,
        *,
        source_id: int,
        zone_id: int,
        external_item_id: str,
        processing_version: str,
    ) -> SatelliteObservation | None:
        return self.session.scalar(
            select(SatelliteObservation).where(
                SatelliteObservation.source_id == source_id,
                SatelliteObservation.zone_id == zone_id,
                SatelliteObservation.external_item_id == external_item_id,
                SatelliteObservation.processing_version == processing_version,
            )
        )

    def upsert_observation(
        self,
        *,
        source_id: int,
        zone_id: int,
        external_item_id: str,
        acquisition_time: datetime,
        interval_start: datetime | None,
        interval_end: datetime | None,
        processing_time: datetime | None,
        platform: str | None,
        collection: str,
        product_type: str | None,
        cloud_cover_metadata: float | None,
        valid_pixel_fraction: float | None,
        invalid_pixel_fraction: float | None,
        quality_status: str,
        processing_version: str,
        geometry_hash: str,
        raw_metadata_json: dict[str, Any] | None,
        force: bool = False,
    ) -> tuple[SatelliteObservation, bool]:
        observation = self.observation_by_external_key(
            source_id=source_id,
            zone_id=zone_id,
            external_item_id=external_item_id,
            processing_version=processing_version,
        )
        created = observation is None
        if observation is None:
            observation = SatelliteObservation(
                source_id=source_id,
                zone_id=zone_id,
                external_item_id=external_item_id,
                acquisition_time=acquisition_time,
                collection=collection,
                quality_status=quality_status,
                processing_version=processing_version,
                geometry_hash=geometry_hash,
            )
            self.session.add(observation)
        elif not force:
            return observation, False

        observation.acquisition_time = acquisition_time
        observation.interval_start = interval_start
        observation.interval_end = interval_end
        observation.processing_time = processing_time
        observation.platform = platform
        observation.collection = collection
        observation.product_type = product_type
        observation.cloud_cover_metadata = cloud_cover_metadata
        observation.valid_pixel_fraction = valid_pixel_fraction
        observation.invalid_pixel_fraction = invalid_pixel_fraction
        observation.quality_status = quality_status
        observation.processing_version = processing_version
        observation.geometry_hash = geometry_hash
        observation.raw_metadata_json = raw_metadata_json
        self.session.flush()
        return observation, created

    def replace_metrics(self, observation: SatelliteObservation, metrics: dict[str, dict[str, Any]]) -> None:
        existing = {metric.metric_code: metric for metric in observation.metrics}
        for metric_code, values in metrics.items():
            metric = existing.get(metric_code)
            if metric is None:
                metric = SatelliteMetric(observation_id=observation.id, metric_code=metric_code)
                self.session.add(metric)
            metric.mean = values.get("mean")
            metric.median = values.get("median")
            metric.minimum = values.get("minimum")
            metric.maximum = values.get("maximum")
            metric.standard_deviation = values.get("standard_deviation")
            metric.percentile_10 = values.get("percentile_10")
            metric.percentile_25 = values.get("percentile_25")
            metric.percentile_75 = values.get("percentile_75")
            metric.percentile_90 = values.get("percentile_90")
            metric.sample_count = values.get("sample_count")
            metric.no_data_count = values.get("no_data_count")
            metric.valid_pixel_count = values.get("valid_pixel_count")
            metric.unit = "dimensionless"
        self.session.flush()

    def upsert_asset(
        self,
        *,
        observation_id: int,
        asset_type: str,
        storage_path: str,
        mime_type: str,
        checksum_sha256: str,
        size_bytes: int,
    ) -> SatelliteAsset:
        asset = self.session.scalar(
            select(SatelliteAsset).where(
                SatelliteAsset.observation_id == observation_id,
                SatelliteAsset.asset_type == asset_type,
            )
        )
        if asset is None:
            asset = SatelliteAsset(observation_id=observation_id, asset_type=asset_type)
            self.session.add(asset)
        asset.storage_path = storage_path
        asset.mime_type = mime_type
        asset.checksum_sha256 = checksum_sha256
        asset.size_bytes = size_bytes
        self.session.flush()
        return asset

    def latest_observation(self, *, zone_id: int | None = None) -> SatelliteObservation | None:
        statement = (
            select(SatelliteObservation)
            .options(
                joinedload(SatelliteObservation.zone),
                joinedload(SatelliteObservation.source),
                joinedload(SatelliteObservation.metrics),
                joinedload(SatelliteObservation.assets),
            )
            .order_by(desc(SatelliteObservation.acquisition_time), desc(SatelliteObservation.id))
            .limit(1)
        )
        if zone_id is not None:
            statement = statement.where(SatelliteObservation.zone_id == zone_id)
        return self.session.scalars(statement).unique().first()

    def observations(
        self,
        *,
        zone_id: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        quality_status: str | None = None,
    ) -> list[SatelliteObservation]:
        statement = (
            select(SatelliteObservation)
            .options(
                joinedload(SatelliteObservation.zone),
                joinedload(SatelliteObservation.source),
                joinedload(SatelliteObservation.metrics),
                joinedload(SatelliteObservation.assets),
            )
            .order_by(SatelliteObservation.acquisition_time, SatelliteObservation.id)
        )
        if zone_id is not None:
            statement = statement.where(SatelliteObservation.zone_id == zone_id)
        if start is not None:
            statement = statement.where(SatelliteObservation.acquisition_time >= start)
        if end is not None:
            statement = statement.where(SatelliteObservation.acquisition_time <= end)
        if quality_status is not None:
            statement = statement.where(SatelliteObservation.quality_status == quality_status)
        return list(self.session.scalars(statement).unique().all())

    def observation(self, observation_id: int) -> SatelliteObservation | None:
        return self.session.scalars(
            select(SatelliteObservation)
            .options(
                joinedload(SatelliteObservation.zone),
                joinedload(SatelliteObservation.source),
                joinedload(SatelliteObservation.metrics),
                joinedload(SatelliteObservation.assets),
            )
            .where(SatelliteObservation.id == observation_id)
        ).unique().first()

    def asset(self, asset_id: int) -> SatelliteAsset | None:
        return self.session.get(SatelliteAsset, asset_id)

    def latest_acquisition_time(self, *, zone_id: int) -> datetime | None:
        return self.session.scalar(
            select(SatelliteObservation.acquisition_time)
            .where(SatelliteObservation.zone_id == zone_id)
            .order_by(desc(SatelliteObservation.acquisition_time))
            .limit(1)
        )
