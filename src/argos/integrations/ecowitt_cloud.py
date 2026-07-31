from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from argos.config.settings import Settings

UrlopenFunc = Callable[..., Any]

DEFAULT_HISTORY_CALLBACKS = (
    "outdoor",
    "indoor",
    "solar_and_uvi",
    "rainfall",
    "rainfall_piezo",
    "wind",
    "pressure",
    "battery",
)


class EcowittCloudError(RuntimeError):
    """Raised when Ecowitt Cloud cannot provide usable JSON data."""


class EcowittCloudConfigError(EcowittCloudError):
    """Raised when Ecowitt Cloud credentials are incomplete."""


@dataclass(frozen=True, slots=True)
class EcowittCloudCredentials:
    application_key: str
    api_key: str
    mac: str


@dataclass(frozen=True, slots=True)
class EcowittCloudClient:
    base_url: str
    api_version: str
    credentials: EcowittCloudCredentials
    local_timezone: str = "Europe/Madrid"
    timeout_seconds: int = 10
    urlopen_func: UrlopenFunc = urlopen

    @classmethod
    def from_settings(cls, settings: Settings) -> EcowittCloudClient:
        if (
            not settings.ecowitt_cloud_application_key
            or not settings.ecowitt_cloud_api_key
            or not settings.ecowitt_cloud_mac
        ):
            raise EcowittCloudConfigError(
                "Ecowitt Cloud backfill requires ECOWITT_CLOUD_APPLICATION_KEY, "
                "ECOWITT_CLOUD_API_KEY and ECOWITT_CLOUD_MAC."
            )

        return cls(
            base_url=settings.ecowitt_cloud_base_url,
            api_version=settings.ecowitt_cloud_api_version,
            credentials=EcowittCloudCredentials(
                application_key=settings.ecowitt_cloud_application_key,
                api_key=settings.ecowitt_cloud_api_key,
                mac=settings.ecowitt_cloud_mac,
            ),
            local_timezone=settings.local_timezone,
            timeout_seconds=settings.ecowitt_cloud_timeout_seconds,
        )

    def get_history(
        self,
        *,
        start: datetime,
        end: datetime,
        callbacks: tuple[str, ...] = DEFAULT_HISTORY_CALLBACKS,
    ) -> dict[str, Any]:
        params = {
            "application_key": self.credentials.application_key,
            "api_key": self.credentials.api_key,
            "mac": self.credentials.mac,
            "start_date": format_cloud_datetime(start, timezone_name=self.local_timezone),
            "end_date": format_cloud_datetime(end, timezone_name=self.local_timezone),
            "call_back": ",".join(callbacks),
        }
        payload = self._get_json("/device/history", params=params)
        code = payload.get("code")
        if code not in (None, 0, "0"):
            message = payload.get("msg") or payload.get("message") or "unknown Ecowitt Cloud error"
            raise EcowittCloudError(f"Ecowitt Cloud returned code {code}: {message}")
        return payload

    def _get_json(self, path: str, *, params: dict[str, str]) -> dict[str, Any]:
        url = self._build_url(path, params=params)
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with self.urlopen_func(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise EcowittCloudError(f"Ecowitt Cloud returned HTTP {exc.code} for {path}.") from exc
        except URLError as exc:
            raise EcowittCloudError("Could not connect to Ecowitt Cloud.") from exc
        except TimeoutError as exc:
            raise EcowittCloudError(f"Ecowitt Cloud request timed out for {path}.") from exc
        except json.JSONDecodeError as exc:
            raise EcowittCloudError("Ecowitt Cloud returned a non-JSON response.") from exc

        if not isinstance(payload, dict):
            raise EcowittCloudError("Ecowitt Cloud JSON response must be an object.")
        return payload

    def _build_url(self, path: str, *, params: dict[str, str]) -> str:
        base = self.base_url.rstrip("/")
        version = self.api_version.strip("/")
        return f"{base}/api/{version}{path}?{urlencode(params)}"


def format_cloud_datetime(value: datetime, *, timezone_name: str = "Europe/Madrid") -> str:
    if value.tzinfo is not None:
        value = value.astimezone(ZoneInfo(timezone_name))
    return value.strftime("%Y-%m-%d %H:%M:%S")
