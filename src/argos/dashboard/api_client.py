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

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any | None] | None = None,
        admin: bool = False,
    ) -> Any:
        url = self._build_url(path, params=params)
        headers = {"Accept": "application/json"}
        if admin:
            if not self.admin_token:
                raise ArgosApiError("Admin token is required for this endpoint.")
            headers["X-ARGOS-ADMIN-TOKEN"] = self.admin_token

        request = Request(url, headers=headers, method="GET")
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
