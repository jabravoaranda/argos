from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ArgosNodeError(RuntimeError):
    """Raised when the dashboard cannot reach argos-node."""


@dataclass(frozen=True, slots=True)
class ArgosNodeClient:
    base_url: str
    timeout_seconds: int = 5

    def get_valve(self, valve_id: int) -> dict[str, Any] | None:
        return self._request_json("GET", f"/valves/{valve_id}")

    def get_status(self) -> dict[str, Any] | None:
        return self._request_json("GET", "/status")

    def open_valve(self, valve_id: int) -> dict[str, Any] | None:
        return self._request_json("POST", f"/valves/{valve_id}/open")

    def close_valve(self, valve_id: int) -> dict[str, Any] | None:
        return self._request_json("POST", f"/valves/{valve_id}/close")

    def reset_flowmeter_total(self) -> dict[str, Any] | None:
        return self._request_json("POST", "/flowmeter/reset-total")

    def reset_flowmeter_session(self) -> dict[str, Any] | None:
        return self._request_json("POST", "/flowmeter/reset-session")

    def reset_flowmeter_hydrological_year(self) -> dict[str, Any] | None:
        return self._request_json("POST", "/flowmeter/reset-hydrological-year")

    def get_valve_1(self) -> dict[str, Any] | None:
        return self.get_valve(1)

    def open_valve_1(self) -> dict[str, Any] | None:
        return self.open_valve(1)

    def close_valve_1(self) -> dict[str, Any] | None:
        return self.close_valve(1)

    def _request_json(self, method: str, path: str) -> dict[str, Any] | None:
        url = self._build_url(path)
        headers = {"Accept": "application/json"}
        data = b"" if method == "POST" else None
        request = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8").strip()
        except HTTPError as exc:
            raise ArgosNodeError(f"argos-node returned HTTP {exc.code} for {path}.") from exc
        except URLError as exc:
            raise ArgosNodeError(f"Could not connect to argos-node at {self.base_url}.") from exc
        except TimeoutError as exc:
            raise ArgosNodeError(f"argos-node request timed out for {path}.") from exc

        if not body:
            return None

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ArgosNodeError(f"argos-node returned invalid JSON for {path}.") from exc

        if not isinstance(payload, dict):
            raise ArgosNodeError(f"argos-node returned unexpected JSON for {path}.")
        return payload

    def _build_url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"
