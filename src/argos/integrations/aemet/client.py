from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from time import sleep
from typing import Any
from urllib.parse import urlparse

import requests

from argos.config.settings import Settings

RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class AemetError(RuntimeError):
    """Raised when AEMET OpenData cannot provide usable data."""


class AemetConfigError(AemetError):
    """Raised when AEMET OpenData credentials are not configured."""


class AemetResponseError(AemetError):
    """Raised when AEMET OpenData returns an unexpected response."""


@dataclass(slots=True)
class AemetClient:
    base_url: str
    api_key: str
    station_id: str = "6127X"
    timeout_seconds: int = 20
    max_retries: int = 3
    backoff_seconds: float = 0.5
    session: requests.Session | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> AemetClient:
        if not settings.aemet_api_key:
            raise AemetConfigError("AEMET OpenData requires AEMET_API_KEY.")
        return cls(
            base_url=settings.aemet_base_url,
            api_key=settings.aemet_api_key,
            station_id=settings.aemet_station_id,
            timeout_seconds=settings.aemet_timeout_seconds,
            max_retries=settings.aemet_max_retries,
            backoff_seconds=settings.aemet_backoff_seconds,
        )

    def daily_climatology(self, *, start: date, end: date, station_id: str | None = None) -> list[dict[str, Any]]:
        idema = station_id or self.station_id
        path = (
            "/valores/climatologicos/diarios/datos/"
            f"fechaini/{_format_aemet_date(start)}/fechafin/{_format_aemet_date(end)}/estacion/{idema}"
        )
        initial = self._get_json(path, include_api_key=True)
        data_url = self._extract_data_url(initial)
        payload = self._get_json(data_url, include_api_key=False, absolute_url=True)
        if not isinstance(payload, list):
            raise AemetResponseError("AEMET data URL returned JSON that is not a list.")
        return [item for item in payload if isinstance(item, dict)]

    def station_metadata(self, *, station_id: str | None = None) -> dict[str, Any] | None:
        stations = self.stations_metadata()
        selected = station_id or self.station_id
        for station in stations:
            if str(station.get("indicativo", "")).strip() == selected:
                return station
        return None

    def stations_metadata(self) -> list[dict[str, Any]]:
        initial = self._get_json("/valores/climatologicos/inventarioestaciones/todasestaciones", include_api_key=True)
        data_url = self._extract_data_url(initial)
        payload = self._get_json(data_url, include_api_key=False, absolute_url=True)
        if not isinstance(payload, list):
            raise AemetResponseError("AEMET station metadata data URL returned JSON that is not a list.")
        return [item for item in payload if isinstance(item, dict)]

    def _get_json(self, path_or_url: str, *, include_api_key: bool, absolute_url: bool = False) -> Any:
        url = path_or_url if absolute_url else f"{self.base_url.rstrip('/')}/{path_or_url.lstrip('/')}"
        headers = {"Accept": "application/json"}
        params = {"api_key": self.api_key} if include_api_key else None
        last_error: Exception | None = None
        http = self.session or requests.Session()
        for attempt in range(self.max_retries + 1):
            try:
                response = http.get(url, headers=headers, params=params, timeout=self.timeout_seconds)
                if response.status_code in RETRY_STATUS_CODES and attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                if response.status_code >= 400:
                    raise AemetResponseError(f"AEMET returned HTTP {response.status_code}.")
                return response.json()
            except requests.Timeout as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise AemetError("AEMET request timed out.") from exc
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise AemetError("Could not connect to AEMET OpenData.") from exc
            except ValueError as exc:
                raise AemetResponseError("AEMET returned a non-JSON response.") from exc
        raise AemetError("AEMET request failed.") from last_error

    def _extract_data_url(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            raise AemetResponseError("AEMET metadata response must be a JSON object.")
        data_url = payload.get("datos")
        if not isinstance(data_url, str) or not data_url.strip():
            raise AemetResponseError("AEMET metadata response does not include a usable datos URL.")
        parsed = urlparse(data_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AemetResponseError("AEMET metadata response includes an invalid datos URL.")
        return data_url

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.backoff_seconds > 0:
            sleep(self.backoff_seconds * (2**attempt))


def _format_aemet_date(value: date) -> str:
    return f"{value.isoformat()}T00:00:00UTC"
