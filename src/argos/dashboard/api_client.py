from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ArgosApiError(RuntimeError):
    """Raised when the dashboard cannot retrieve ARGOS API data."""


@dataclass(frozen=True, slots=True)
class ArgosApiClient:
    base_url: str
    admin_token: str | None = None
    timeout_seconds: int = 5

    def get_health(self) -> dict[str, Any]:
        return self._get_json("/health")

    def get_latest(self) -> dict[str, Any] | None:
        return self._get_json("/api/v1/weather/latest")

    def get_station(self) -> dict[str, Any] | None:
        return self._get_json("/api/v1/weather/station")

    def get_station_hardware(self) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/station/hardware")

    def get_gateway_status(self) -> dict[str, Any]:
        return self._get_json("/api/v1/weather/gateway/status")

    def get_observations(self, *, start: str | None, end: str | None) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/observations", params={"from": start, "to": end})

    def get_daily_summary(self, *, start: str | None, end: str | None) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/summary/daily", params={"from": start, "to": end})

    def get_weekly_summary(self, *, start: str | None, end: str | None) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/summary/weekly", params={"from": start, "to": end})

    def get_data_gaps(self) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/admin/data-gaps", admin=True)

    def get_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/admin/events", params={"limit": limit}, admin=True)

    def get_unknown_fields(self) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/admin/unknown-fields", admin=True)

    def get_raw_reports(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/admin/raw-reports", params={"limit": limit}, admin=True)

    def get_satellite_status(self) -> dict[str, Any]:
        return self._get_json("/api/v1/satellite/status")

    def get_satellite_latest(self) -> dict[str, Any] | None:
        return self._get_json("/api/v1/satellite/latest")

    def get_satellite_zones(self) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/satellite/zones")

    def get_satellite_bounds(
        self,
        *,
        quality_status: str | None = None,
        zone_id: int | None = None,
    ) -> dict[str, Any]:
        return self._get_json(
            "/api/v1/satellite/bounds",
            params={"quality_status": quality_status, "zone_id": zone_id},
        )

    def get_satellite_observations(
        self,
        *,
        start: str | None,
        end: str | None,
        quality_status: str | None = None,
        zone_id: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._get_json(
            "/api/v1/satellite/observations",
            params={"from": start, "to": end, "quality_status": quality_status, "zone_id": zone_id},
        )

    def get_satellite_timeseries(
        self,
        *,
        metric: str,
        start: str | None,
        end: str | None,
        quality_status: str | None = None,
    ) -> dict[str, Any]:
        return self._get_json(
            "/api/v1/satellite/timeseries",
            params={"metric": metric, "from": start, "to": end, "quality_status": quality_status},
        )

    def get_satellite_export_json(
        self,
        *,
        start: str | None,
        end: str | None,
        quality_status: str | None = None,
        zone_id: int | None = None,
        metric: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._get_json(
            "/api/v1/satellite/export.json",
            params={
                "from": start,
                "to": end,
                "quality_status": quality_status,
                "zone_id": zone_id,
                "metric": metric,
            },
        )

    def update_satellite(self, *, zone: str | None = None, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        return self._request_json(
            "/api/v1/satellite/update",
            method="POST",
            params={"zone": zone, "force": force, "dry_run": dry_run},
            admin=True,
        )

    def backfill_satellite(
        self,
        *,
        start: str,
        end: str,
        zone: str | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self._request_json(
            "/api/v1/satellite/backfill",
            method="POST",
            params={"from": start, "to": end, "zone": zone, "force": force, "dry_run": dry_run},
            admin=True,
        )

    def get_weather_stations(self, *, provider: str | None = None) -> list[dict[str, Any]]:
        return self._get_json("/api/v1/weather/stations", params={"provider": provider})

    def get_aemet_observations(
        self,
        *,
        station: str,
        start: str | None,
        end: str | None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._get_json(
            "/api/v1/weather/aemet/observations",
            params={"station": station, "from": start, "to": end, "limit": limit, "offset": offset},
        )

    def get_latest_aemet_sync(self, *, station: str | None = None) -> dict[str, Any] | None:
        return self._get_json("/api/v1/weather/aemet/sync/latest", params={"station": station})

    def get_aemet_bounds(self, *, station: str) -> dict[str, Any]:
        return self._get_json("/api/v1/weather/aemet/bounds", params={"station": station})

    def backfill_aemet(
        self,
        *,
        station: str,
        start: str,
        end: str,
        block_days: int | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "/api/v1/weather/aemet/backfill",
            method="POST",
            params={"station": station, "from": start, "to": end, "block_days": block_days},
            admin=True,
        )

    def sync_aemet(self, *, station: str, lookback_days: int) -> dict[str, Any]:
        return self._request_json(
            "/api/v1/weather/aemet/sync",
            method="POST",
            params={"station": station, "lookback_days": lookback_days},
            admin=True,
        )

    def import_aemet_csv(self, *, station: str, path: str) -> dict[str, Any]:
        return self._request_json(
            "/api/v1/weather/aemet/import-csv",
            method="POST",
            params={"station": station, "path": path},
            admin=True,
        )

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any | None] | None = None,
        admin: bool = False,
    ) -> Any:
        return self._request_json(path, method="GET", params=params, admin=admin)

    def _request_json(
        self,
        path: str,
        *,
        method: str,
        params: dict[str, Any | None] | None = None,
        admin: bool = False,
    ) -> Any:
        url = self._build_url(path, params=params)
        headers = {"Accept": "application/json"}
        if admin:
            if not self.admin_token:
                raise ArgosApiError("Admin token is required for this endpoint.")
            headers["X-ARGOS-ADMIN-TOKEN"] = self.admin_token

        request = Request(url, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ArgosApiError(f"ARGOS API returned HTTP {exc.code} for {path}.") from exc
        except URLError as exc:
            raise ArgosApiError(f"Could not connect to ARGOS API at {self.base_url}.") from exc
        except TimeoutError as exc:
            raise ArgosApiError(f"ARGOS API request timed out for {path}.") from exc

    def _build_url(self, path: str, *, params: dict[str, Any | None] | None) -> str:
        base = self.base_url.rstrip("/")
        query_params = {key: value for key, value in (params or {}).items() if value is not None}
        query = urlencode(query_params)
        if query:
            return f"{base}{path}?{query}"
        return f"{base}{path}"
