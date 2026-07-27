from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Any

import requests

from argos.config.settings import Settings
from argos.services.satellite_indices import SENTINEL_2_COLLECTION

logger = logging.getLogger(__name__)


class CopernicusError(RuntimeError):
    """Raised when Copernicus Data Space cannot provide usable data."""


class CopernicusConfigError(CopernicusError):
    """Raised when Copernicus credentials or AOI settings are incomplete."""


class CopernicusAuthError(CopernicusError):
    """Raised when Copernicus rejects authentication or authorization."""


class CopernicusRateLimitError(CopernicusError):
    """Raised when Copernicus rate limits the request."""


@dataclass(frozen=True, slots=True)
class CopernicusCredentials:
    client_id: str
    client_secret: str


@dataclass(frozen=True, slots=True)
class StacItem:
    id: str
    acquisition_time: datetime
    platform: str | None
    collection: str
    product_type: str | None
    cloud_cover: float | None
    raw: dict[str, Any]


class CopernicusSatelliteAdapter:
    provider = "Copernicus Data Space Ecosystem"

    def __init__(
        self,
        *,
        token_url: str,
        stac_url: str,
        catalog_url: str,
        statistics_url: str,
        process_url: str,
        credentials: CopernicusCredentials,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.token_url = token_url
        self.stac_url = stac_url.rstrip("/")
        self.catalog_url = catalog_url.rstrip("/")
        self.statistics_url = statistics_url
        self.process_url = process_url
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self._access_token: str | None = None
        self._token_expires_at_monotonic = 0.0
        self.processing_units_total = 0.0

    @classmethod
    def from_settings(cls, settings: Settings) -> CopernicusSatelliteAdapter:
        if not settings.copernicus_client_id or not settings.copernicus_client_secret:
            raise CopernicusConfigError(
                "Satellite ingestion requires COPERNICUS_CLIENT_ID and COPERNICUS_CLIENT_SECRET."
            )
        return cls(
            token_url=settings.copernicus_token_url,
            stac_url=settings.copernicus_stac_url,
            catalog_url=settings.copernicus_catalog_url,
            statistics_url=settings.copernicus_statistics_url,
            process_url=settings.copernicus_process_url,
            credentials=CopernicusCredentials(
                client_id=settings.copernicus_client_id,
                client_secret=settings.copernicus_client_secret,
            ),
            timeout_seconds=settings.argos_satellite_http_timeout_seconds,
        )

    def get_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at_monotonic - 60:
            return self._access_token

        response = self._request(
            "POST",
            self.token_url,
            authenticated=False,
            data={
                "grant_type": "client_credentials",
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        payload = response.json()
        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in") or 0)
        if not token or expires_in <= 0:
            raise CopernicusAuthError("Copernicus token response did not include a usable access token.")
        self._access_token = str(token)
        self._token_expires_at_monotonic = time.monotonic() + expires_in
        return self._access_token

    def search_sentinel2_items(
        self,
        *,
        geometry: dict[str, Any],
        start: datetime,
        end: datetime,
        max_cloud_cover: float,
        limit: int = 100,
    ) -> list[StacItem]:
        try:
            return self._search_sentinel2_items_stac(
                geometry=geometry,
                start=start,
                end=end,
                max_cloud_cover=max_cloud_cover,
                limit=limit,
            )
        except (CopernicusAuthError, CopernicusRateLimitError):
            raise
        except CopernicusError as exc:
            logger.warning(
                "copernicus stac search failed; falling back to sentinel hub catalog",
                extra={
                    "provider": self.provider,
                    "operation": "stac_search",
                    "status": "degraded",
                    "http_status": None,
                    "retry_count": None,
                },
            )
            return self._search_sentinel2_items_catalog(
                geometry=geometry,
                start=start,
                end=end,
                max_cloud_cover=max_cloud_cover,
                limit=limit,
                stac_error=exc,
            )

    def _search_sentinel2_items_stac(
        self,
        *,
        geometry: dict[str, Any],
        start: datetime,
        end: datetime,
        max_cloud_cover: float,
        limit: int,
    ) -> list[StacItem]:
        items: list[StacItem] = []
        payload: dict[str, Any] = {
            "collections": [SENTINEL_2_COLLECTION],
            "datetime": f"{format_utc(start)}/{format_utc(end)}",
            "intersects": geometry,
            "query": {"eo:cloud_cover": {"lte": max_cloud_cover}},
            "limit": limit,
        }
        url = f"{self.stac_url}/search"
        while True:
            response = self._request("POST", url, json=payload)
            data = response.json()
            for raw_item in data.get("features", []):
                if isinstance(raw_item, dict):
                    items.append(parse_stac_item(raw_item))

            next_url = _next_link(data)
            if not next_url:
                break
            url = next_url
            payload = {}

        return sorted(items, key=lambda item: item.acquisition_time)

    def _search_sentinel2_items_catalog(
        self,
        *,
        geometry: dict[str, Any],
        start: datetime,
        end: datetime,
        max_cloud_cover: float,
        limit: int,
        stac_error: CopernicusError,
    ) -> list[StacItem]:
        items: list[StacItem] = []
        payload: dict[str, Any] = {
            "collections": [SENTINEL_2_COLLECTION],
            "datetime": f"{format_utc(start)}/{format_utc(end)}",
            "intersects": geometry,
            "filter": {"op": "<=", "args": [{"property": "eo:cloud_cover"}, max_cloud_cover]},
            "filter-lang": "cql2-json",
            "limit": limit,
        }
        while True:
            response = self._request(
                "POST",
                f"{self.catalog_url}/search",
                json=payload,
                headers={"Accept": "application/geo+json"},
            )
            data = response.json()
            for raw_item in data.get("features", []):
                if isinstance(raw_item, dict):
                    items.append(parse_stac_item(raw_item))
            next_token = (data.get("context") or {}).get("next")
            if next_token is None:
                break
            payload["next"] = next_token

        if not items:
            logger.info(
                "sentinel hub catalog fallback completed after stac failure",
                extra={
                    "provider": self.provider,
                    "operation": "catalog_search",
                    "status": "empty",
                    "stac_error": str(stac_error),
                },
            )
        return sorted(items, key=lambda item: item.acquisition_time)

    def get_sentinel2_statistics(
        self,
        *,
        geometry: dict[str, Any],
        item: StacItem,
        evalscript: str | None = None,
    ) -> dict[str, Any]:
        script = evalscript if evalscript is not None else load_sentinel2_evalscript()
        interval_start, interval_end = acquisition_day_range(item.acquisition_time)
        payload = {
            "input": {
                "bounds": {"geometry": geometry},
                "data": [
                    {
                        "type": SENTINEL_2_COLLECTION,
                        "dataFilter": {
                            "timeRange": {
                                "from": format_utc(interval_start),
                                "to": format_utc(interval_end),
                            }
                        },
                    }
                ],
            },
            "aggregation": {
                "timeRange": {
                    "from": format_utc(interval_start),
                    "to": format_utc(interval_end),
                },
                "aggregationInterval": {"of": "P1D"},
                "evalscript": script,
            },
            "calculations": {
                metric: {
                    "statistics": {"default": {"percentiles": {"k": [10, 25, 50, 75, 90]}}},
                }
                for metric in ("ndvi", "savi", "ndre", "ndmi")
            },
        }
        response = self._request("POST", self.statistics_url, json=payload)
        return response.json()

    def get_sentinel2_preview_png(
        self,
        *,
        geometry: dict[str, Any],
        item: StacItem,
        asset_type: str,
        width: int = 512,
        height: int = 512,
    ) -> bytes:
        evalscript = preview_evalscript(asset_type)
        interval_start, interval_end = acquisition_day_range(item.acquisition_time)
        payload = {
            "input": {
                "bounds": {"geometry": geometry},
                "data": [
                    {
                        "type": SENTINEL_2_COLLECTION,
                        "dataFilter": {
                            "timeRange": {
                                "from": format_utc(interval_start),
                                "to": format_utc(interval_end),
                            }
                        },
                    }
                ],
            },
            "output": {
                "width": width,
                "height": height,
                "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
            },
            "evalscript": evalscript,
        }
        response = self._request(
            "POST",
            self.process_url,
            json=payload,
            headers={"Accept": "image/png"},
        )
        return response.content

    def _request(self, method: str, url: str, *, authenticated: bool = True, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Accept", "application/json")
        if authenticated:
            headers["Authorization"] = f"Bearer {self.get_token()}"

        retry_count = 0
        transient_statuses = {429, 500, 502, 503, 504}
        while True:
            started = time.monotonic()
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=self.timeout_seconds,
                    headers=headers,
                    **kwargs,
                )
            except requests.Timeout as exc:
                if retry_count >= 3:
                    raise CopernicusError("Copernicus request timed out.") from exc
                _sleep_backoff(retry_count, None)
                retry_count += 1
                continue
            except requests.RequestException as exc:
                raise CopernicusError("Copernicus request failed.") from exc

            duration_ms = round((time.monotonic() - started) * 1000)
            processing_units = _float_or_none(response.headers.get("x-processingunits-spent"))
            if processing_units is not None:
                self.processing_units_total += processing_units
            logger.info(
                "copernicus request",
                extra={
                    "provider": self.provider,
                    "operation": f"{method} {url}",
                    "duration_ms": duration_ms,
                    "status": "ok" if response.ok else "error",
                    "http_status": response.status_code,
                    "retry_count": retry_count,
                    "processing_units_if_available": processing_units,
                },
            )

            if response.status_code == 401:
                self._access_token = None
                raise CopernicusAuthError("Copernicus returned HTTP 401.")
            if response.status_code == 403:
                raise CopernicusAuthError("Copernicus returned HTTP 403.")
            if response.status_code == 429 and retry_count >= 3:
                raise CopernicusRateLimitError("Copernicus rate limit persisted after retries.")
            if response.status_code in transient_statuses and retry_count < 3:
                _sleep_backoff(retry_count, response.headers.get("Retry-After"))
                retry_count += 1
                continue
            if 400 <= response.status_code < 500:
                raise CopernicusError(f"Copernicus returned HTTP {response.status_code}.")
            if response.status_code >= 500:
                raise CopernicusError(f"Copernicus returned HTTP {response.status_code}.")
            return response


def parse_stac_item(raw_item: dict[str, Any]) -> StacItem:
    properties = raw_item.get("properties") or {}
    acquisition_value = properties.get("datetime") or properties.get("start_datetime")
    if not acquisition_value:
        raise CopernicusError("STAC item does not include an acquisition datetime.")
    acquisition_time = parse_datetime(str(acquisition_value))
    collection = raw_item.get("collection") or properties.get("collection") or SENTINEL_2_COLLECTION
    return StacItem(
        id=str(raw_item["id"]),
        acquisition_time=acquisition_time,
        platform=properties.get("platform"),
        collection=str(collection),
        product_type=properties.get("productType") or properties.get("s2:product_type"),
        cloud_cover=_float_or_none(properties.get("eo:cloud_cover")),
        raw=raw_item,
    )


def load_sentinel2_evalscript() -> str:
    return Path(__file__).with_name("sentinel2_indices_v1.js").read_text(encoding="utf-8")


def preview_evalscript(asset_type: str) -> str:
    if asset_type == "preview_rgb_png":
        return """
//VERSION=3
function setup() {
  return { input: ["B02", "B03", "B04", "SCL", "dataMask"], output: { bands: 4, sampleType: "AUTO" } };
}
function valid(s) { return s.dataMask === 1 && (s.SCL === 4 || s.SCL === 5); }
function evaluatePixel(s) {
  if (!valid(s)) { return [0, 0, 0, 0]; }
  return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02, 1];
}
"""
    if asset_type == "preview_ndvi_png":
        return """
//VERSION=3
function setup() {
  return { input: ["B04", "B08", "SCL", "dataMask"], output: { bands: 4, sampleType: "AUTO" } };
}
function valid(s) { return s.dataMask === 1 && (s.SCL === 4 || s.SCL === 5); }
function evaluatePixel(s) {
  const denominator = s.B08 + s.B04;
  if (!valid(s) || denominator === 0) { return [0, 0, 0, 0]; }
  const ndvi = (s.B08 - s.B04) / denominator;
  return [Math.max(0, 1 - ndvi), Math.max(0, ndvi), 0.15, 1];
}
"""
    raise ValueError(f"Unsupported Sentinel-2 preview asset type: {asset_type}")


def format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def acquisition_day_range(value: datetime) -> tuple[datetime, datetime]:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    day_start = datetime.combine(value.astimezone(UTC).date(), datetime_time.min, tzinfo=UTC)
    return day_start, day_start + timedelta(days=1)


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _next_link(payload: dict[str, Any]) -> str | None:
    for link in payload.get("links", []):
        if isinstance(link, dict) and link.get("rel") == "next" and link.get("href"):
            return str(link["href"])
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _sleep_backoff(retry_count: int, retry_after: str | None) -> None:
    if retry_after:
        try:
            time.sleep(min(float(retry_after), 30.0))
            return
        except ValueError:
            pass
    time.sleep(min(2**retry_count, 10))
