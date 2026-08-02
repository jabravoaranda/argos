from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from argos.config.settings import Settings, get_settings
from argos.integrations.copernicus import CopernicusError, CopernicusSatelliteAdapter, StacItem
from argos.repositories.satellite import SatelliteRepository
from argos.services.satellite_geometry import (
    ConfiguredAOI,
    SatelliteGeometryError,
    get_configured_aois,
)
from argos.services.satellite_indices import PROCESSING_VERSION, SATELLITE_METRICS, quality_status

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SatelliteAOIStatus:
    slug: str
    name: str
    geometry_hash: str
    area_m2: float


@dataclass(frozen=True, slots=True)
class SatelliteModuleStatus:
    status: str
    enabled: bool
    configured: bool
    credentials_available: bool
    geometry_defined: bool
    message: str
    latest_acquisition_time: datetime | None = None
    latest_update_time: datetime | None = None
    zone_count: int = 0
    observation_count: int = 0
    aois: list[SatelliteAOIStatus] | None = None


@dataclass(frozen=True, slots=True)
class SatelliteIngestionResult:
    status: str
    found_count: int
    processed_count: int
    skipped_count: int
    failed_count: int
    dry_run: bool
    warnings: list[str]
    processing_units: float | None = None


class SatelliteIngestionService:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings | None = None,
        adapter: CopernicusSatelliteAdapter | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = SatelliteRepository(session)
        self.adapter = adapter

    def status(self) -> SatelliteModuleStatus:
        enabled = self.settings.argos_satellite_enabled
        credentials_available = bool(self.settings.copernicus_client_id and self.settings.copernicus_client_secret)
        aois: dict[str, ConfiguredAOI] = {}
        warnings: list[str] = []
        try:
            aois = self._configured_aois()
            geometry_error = None
        except SatelliteGeometryError as exc:
            geometry_error = exc
        geometry_defined = bool(aois)
        zones = self.repository.zones()
        observation_count = self.repository.observation_count()
        latest = self.repository.latest_observation_timestamps()
        if not enabled:
            status = "disabled"
            message = "Satellite module is disabled."
        elif geometry_error is not None:
            status = "not_configured"
            message = str(geometry_error)
        elif not credentials_available or not geometry_defined:
            status = "not_configured"
            missing = []
            if not credentials_available:
                missing.append("Copernicus OAuth credentials")
            if not geometry_defined:
                missing.append("Satellite AOIs")
            message = "Missing " + " and ".join(missing) + "."
        else:
            status = "ready"
            message = "Satellite module is configured." if not warnings else " ".join(warnings)
        return SatelliteModuleStatus(
            status=status,
            enabled=enabled,
            configured=enabled and credentials_available and geometry_defined,
            credentials_available=credentials_available,
            geometry_defined=geometry_defined,
            message=message,
            latest_acquisition_time=latest[0] if latest else None,
            latest_update_time=(latest[1] or latest[2]) if latest else None,
            zone_count=len(aois) if aois else len(zones),
            observation_count=observation_count,
            aois=[
                SatelliteAOIStatus(slug=aoi.slug, name=aoi.name, geometry_hash=aoi.geometry_hash, area_m2=aoi.area_m2)
                for aoi in aois.values()
            ],
        )

    def backfill(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
        aoi_slug: str | None = None,
        zone_name: str | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> SatelliteIngestionResult:
        end = _ensure_utc(end or datetime.now(UTC))
        start = _ensure_utc(start or (end - timedelta(days=self.settings.argos_satellite_history_days)))
        if zone_name and not aoi_slug:
            aoi_slug = zone_name
        return self._run_range(start=start, end=end, aoi_slug=aoi_slug, force=force, dry_run=dry_run)

    def update(
        self,
        *,
        aoi_slug: str | None = None,
        zone_name: str | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> SatelliteIngestionResult:
        if zone_name and not aoi_slug:
            aoi_slug = zone_name
        source = self.repository.get_or_create_sentinel2_source()
        results: list[SatelliteIngestionResult] = []
        end = datetime.now(UTC)
        try:
            selected_aois = self._selected_aois(aoi_slug)
        except SatelliteGeometryError as exc:
            return SatelliteIngestionResult("error", 0, 0, 0, 1, dry_run, [str(exc)], None)
        for aoi in selected_aois.values():
            try:
                zone = self._get_or_create_configured_zone(aoi)
                latest = self.repository.latest_acquisition_time(zone_id=zone.id)
                start = (latest - timedelta(days=7)) if latest else (end - timedelta(days=self.settings.argos_satellite_history_days))
                result = self._run_range(start=start, end=end, aoi_slug=aoi.slug, force=force, dry_run=dry_run)
                results.append(result)
            except SatelliteGeometryError as exc:
                results.append(SatelliteIngestionResult("error", 0, 0, 0, 1, dry_run, [f"{aoi.slug}: {exc}"], None))
        logger.info(
            "satellite ingestion update",
            extra={
                "provider": "Copernicus Data Space Ecosystem",
                "aoi_slug": aoi_slug,
                "operation": "satellite_update",
                "status": _merge_results(results, dry_run=dry_run).status,
                "source_id": source.id,
            },
        )
        return _merge_results(results, dry_run=dry_run)

    def _run_range(
        self,
        *,
        start: datetime,
        end: datetime,
        aoi_slug: str | None,
        force: bool,
        dry_run: bool,
    ) -> SatelliteIngestionResult:
        if not self.settings.argos_satellite_enabled:
            return SatelliteIngestionResult("disabled", 0, 0, 0, 0, dry_run, ["Satellite module is disabled."], None)
        try:
            selected_aois = self._selected_aois(aoi_slug)
        except SatelliteGeometryError as exc:
            return SatelliteIngestionResult("error", 0, 0, 0, 1, dry_run, [str(exc)], None)
        adapter = self.adapter or CopernicusSatelliteAdapter.from_settings(self.settings)
        source = self.repository.get_or_create_sentinel2_source()
        results = [
            self._run_aoi_range(
                adapter=adapter,
                source_id=source.id,
                aoi=aoi,
                start=start,
                end=end,
                force=force,
                dry_run=dry_run,
            )
            for aoi in selected_aois.values()
        ]
        return _merge_results(results, dry_run=dry_run, processing_units=_processing_units(adapter))

    def _run_aoi_range(
        self,
        *,
        adapter: CopernicusSatelliteAdapter,
        source_id: int,
        aoi: ConfiguredAOI,
        start: datetime,
        end: datetime,
        force: bool,
        dry_run: bool,
    ) -> SatelliteIngestionResult:
        zone = self._get_or_create_configured_zone(aoi)
        started = time.monotonic()
        warnings: list[str] = []
        processed_count = 0
        skipped_count = 0
        failed_count = 0
        try:
            items = adapter.search_sentinel2_items(
                geometry=zone.geometry_geojson,
                start=start,
                end=end,
                max_cloud_cover=self.settings.argos_satellite_max_cloud_cover,
            )
        except (CopernicusError, SatelliteGeometryError) as exc:
            return SatelliteIngestionResult("error", 0, 0, 0, 1, dry_run, [f"{aoi.slug}: {exc}"], _processing_units(adapter))

        for item in items:
            existing = self.repository.observation_by_external_key(
                source_id=source_id,
                zone_id=zone.id,
                external_item_id=item.id,
                processing_version=PROCESSING_VERSION,
            )
            if existing is not None and not force:
                skipped_count += 1
                continue
            if dry_run:
                skipped_count += 1
                continue
            try:
                stats = adapter.get_sentinel2_statistics(geometry=zone.geometry_geojson, item=item)
                metrics, valid_fraction, invalid_fraction = parse_statistical_response(stats)
                observation_status = quality_status(
                    valid_fraction,
                    valid_threshold=self.settings.argos_satellite_valid_pixel_fraction,
                    partial_threshold=self.settings.argos_satellite_min_valid_pixel_fraction,
                )
                observation, _created = self.repository.upsert_observation(
                    source_id=source_id,
                    zone_id=zone.id,
                    external_item_id=item.id,
                    acquisition_time=item.acquisition_time,
                    interval_start=item.acquisition_time,
                    interval_end=item.acquisition_time,
                    processing_time=datetime.now(UTC),
                    platform=item.platform,
                    collection=item.collection,
                    product_type=item.product_type,
                    cloud_cover_metadata=item.cloud_cover,
                    valid_pixel_fraction=valid_fraction,
                    invalid_pixel_fraction=invalid_fraction,
                    quality_status=observation_status,
                    processing_version=PROCESSING_VERSION,
                    geometry_hash=zone.geometry_hash,
                    raw_metadata_json={"stac_item": item.raw, "statistics": stats},
                    force=force,
                )
                self.repository.replace_metrics(observation, metrics)
                if self.settings.argos_satellite_preview_enabled:
                    try:
                        self._store_previews(
                            adapter=adapter,
                            aoi_slug=aoi.slug,
                            geometry=zone.geometry_geojson,
                            item=item,
                            observation_id=observation.id,
                        )
                    except CopernicusError as exc:
                        warnings.append(f"{aoi.slug}: {item.id}: preview generation failed: {exc}")
                self.session.commit()
                processed_count += 1
                log_satellite_observation(item, zone_id=zone.id, aoi_slug=aoi.slug, operation="process_item", status=observation_status)
            except CopernicusError as exc:
                self.session.rollback()
                failed_count += 1
                warnings.append(f"{aoi.slug}: {item.id}: {exc}")
                log_satellite_observation(item, zone_id=zone.id, aoi_slug=aoi.slug, operation="process_item", status="error")

        duration_ms = round((time.monotonic() - started) * 1000)
        status = "degraded" if failed_count or warnings else "ready"
        logger.info(
            "satellite ingestion completed",
            extra={
                "provider": "Copernicus Data Space Ecosystem",
                "zone_id": zone.id,
                "aoi_slug": aoi.slug,
                "operation": "satellite_backfill",
                "duration_ms": duration_ms,
                "status": status,
            },
        )
        return SatelliteIngestionResult(
            status=status,
            found_count=len(items),
            processed_count=processed_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            dry_run=dry_run,
            warnings=warnings,
            processing_units=_processing_units(adapter),
        )

    def _configured_aois(self) -> dict[str, ConfiguredAOI]:
        return get_configured_aois(self.settings)

    def _selected_aois(self, aoi_slug: str | None) -> dict[str, ConfiguredAOI]:
        aois = self._configured_aois()
        if not aois:
            raise SatelliteGeometryError("Satellite AOI geometry is not defined.")
        if aoi_slug:
            if aoi_slug not in aois:
                raise SatelliteGeometryError(f"Satellite AOI {aoi_slug!r} is not configured.")
            return {aoi_slug: aois[aoi_slug]}
        return aois

    def _get_or_create_configured_zone(self, aoi: ConfiguredAOI) -> Any:
        return self.repository.get_or_create_zone(
            slug=aoi.slug,
            name=aoi.name,
            geometry_geojson=aoi.geometry,
            geometry_hash=aoi.geometry_hash,
            area_m2=aoi.area_m2,
        )

    def _store_previews(
        self,
        *,
        adapter: CopernicusSatelliteAdapter,
        aoi_slug: str,
        geometry: dict[str, Any],
        item: StacItem,
        observation_id: int,
    ) -> None:
        asset_dir = Path(self.settings.argos_satellite_asset_dir)
        if not asset_dir.is_absolute():
            asset_dir = Path.cwd() / asset_dir
        acquisition_slug = item.acquisition_time.strftime("%Y%m%dT%H%M%SZ")
        item_dir = asset_dir / aoi_slug / "sentinel-2-l2a" / item.id
        item_dir.mkdir(parents=True, exist_ok=True)
        for asset_type in ("preview_rgb_png", "preview_ndvi_png"):
            path = item_dir / f"{acquisition_slug}_{asset_type}.png"
            if path.exists():
                data = path.read_bytes()
            else:
                data = adapter.get_sentinel2_preview_png(
                    geometry=geometry,
                    item=item,
                    asset_type=asset_type,
                )
                path.write_bytes(data)
            self.repository.upsert_asset(
                observation_id=observation_id,
                asset_type=asset_type,
                storage_path=str(path),
                mime_type="image/png",
                checksum_sha256=sha256(data).hexdigest(),
                size_bytes=len(data),
            )


def parse_statistical_response(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], float, float]:
    outputs = _first_interval_outputs(payload)
    metrics: dict[str, dict[str, Any]] = {}
    sample_count = 0
    no_data_count = 0
    valid_pixel_count = 0
    for metric_code in SATELLITE_METRICS:
        band_stats = _metric_stats(outputs, metric_code)
        values = normalize_metric_stats(band_stats)
        metrics[metric_code] = values
        sample_count = max(sample_count, values.get("sample_count") or 0)
        no_data_count = max(no_data_count, values.get("no_data_count") or 0)
        valid_pixel_count = max(valid_pixel_count, values.get("valid_pixel_count") or 0)

    denominator = sample_count if sample_count > 0 else valid_pixel_count + no_data_count
    valid_fraction = 0.0 if denominator <= 0 else valid_pixel_count / denominator
    invalid_fraction = 1.0 - valid_fraction if denominator > 0 else 1.0
    return metrics, valid_fraction, invalid_fraction


def normalize_metric_stats(stats: dict[str, Any]) -> dict[str, Any]:
    sample_count = int(stats.get("sampleCount") or stats.get("sample_count") or 0)
    no_data_count = int(stats.get("noDataCount") or stats.get("no_data_count") or 0)
    valid_pixel_count = max(0, sample_count - no_data_count)
    percentiles = stats.get("percentiles") or {}
    return {
        "mean": _float_or_none(stats.get("mean")),
        "median": _float_or_none(percentiles.get("50") or percentiles.get(50)),
        "minimum": _float_or_none(stats.get("min")),
        "maximum": _float_or_none(stats.get("max")),
        "standard_deviation": _float_or_none(stats.get("stDev") or stats.get("stdDev")),
        "percentile_10": _float_or_none(percentiles.get("10") or percentiles.get(10)),
        "percentile_25": _float_or_none(percentiles.get("25") or percentiles.get(25)),
        "percentile_75": _float_or_none(percentiles.get("75") or percentiles.get(75)),
        "percentile_90": _float_or_none(percentiles.get("90") or percentiles.get(90)),
        "sample_count": sample_count,
        "no_data_count": no_data_count,
        "valid_pixel_count": valid_pixel_count,
    }


def log_satellite_observation(item: StacItem, *, zone_id: int, aoi_slug: str, operation: str, status: str) -> None:
    logger.info(
        "satellite observation",
        extra={
            "provider": "Copernicus Data Space Ecosystem",
            "zone_id": zone_id,
            "aoi_slug": aoi_slug,
            "external_item_id": item.id,
            "acquisition_time": item.acquisition_time.isoformat(),
            "operation": operation,
            "status": status,
        },
    )


def _first_interval_outputs(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, list) and data:
        outputs = data[0].get("outputs")
        if isinstance(outputs, dict):
            return outputs
    outputs = payload.get("outputs")
    if isinstance(outputs, dict):
        return outputs
    return {}


def _metric_stats(outputs: dict[str, Any], metric_code: str) -> dict[str, Any]:
    output = outputs.get(metric_code) or {}
    bands = output.get("bands") or {}
    band = bands.get("B0") or bands.get("0") or bands.get(metric_code) or {}
    stats = band.get("stats") or band.get("statistics") or band
    return stats if isinstance(stats, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _processing_units(adapter: Any) -> float | None:
    value = getattr(adapter, "processing_units_total", None)
    return float(value) if value is not None else None


def _merge_results(
    results: list[SatelliteIngestionResult],
    *,
    dry_run: bool,
    processing_units: float | None = None,
) -> SatelliteIngestionResult:
    if not results:
        return SatelliteIngestionResult("error", 0, 0, 0, 1, dry_run, ["No satellite AOIs were processed."], processing_units)
    warnings = [warning for result in results for warning in result.warnings]
    failed_count = sum(result.failed_count for result in results)
    status = "degraded" if failed_count or warnings or any(result.status == "degraded" for result in results) else "ready"
    if all(result.status == "disabled" for result in results):
        status = "disabled"
    if any(result.status == "error" for result in results) and not any(
        result.processed_count or result.skipped_count for result in results
    ):
        status = "error"
    return SatelliteIngestionResult(
        status=status,
        found_count=sum(result.found_count for result in results),
        processed_count=sum(result.processed_count for result in results),
        skipped_count=sum(result.skipped_count for result in results),
        failed_count=failed_count,
        dry_run=dry_run,
        warnings=warnings,
        processing_units=processing_units
        if processing_units is not None
        else sum(result.processing_units or 0 for result in results),
    )
