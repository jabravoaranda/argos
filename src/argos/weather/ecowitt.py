from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv
from requests import RequestException, Timeout


ENDPOINT_PATH = "/get_livedata_info"
DEFAULT_DATA_DIR = Path("data/weather")

CSV_COLUMNS = [
    "fecha_hora_local",
    "temperatura_exterior",
    "humedad_exterior",
    "presion_absoluta",
    "presion_relativa",
    "lluvia_evento",
    "lluvia_diaria",
    "lluvia_intensidad",
    "viento_velocidad",
    "viento_racha",
    "viento_direccion",
    "radiacion_solar",
    "uv",
    "bateria_ws90",
    "condensador_ws90",
]


@dataclass(frozen=True)
class EcowittConfig:
    gw2000_ip: str
    timeout_seconds: float = 10.0
    interval_seconds: float = 60.0
    data_dir: Path = DEFAULT_DATA_DIR

    @property
    def endpoint_url(self) -> str:
        return f"http://{self.gw2000_ip}{ENDPOINT_PATH}"


class EcowittError(RuntimeError):
    """Base error for Ecowitt collection failures."""


class EcowittConfigError(EcowittError):
    """Raised when required configuration is missing or invalid."""


class EcowittFetchError(EcowittError):
    """Raised when the GW2000 cannot be reached or returns invalid data."""


def load_config(config_path: Path | None = None) -> EcowittConfig:
    load_dotenv()

    file_config: dict[str, Any] = {}
    resolved_config_path = _resolve_config_path(config_path)
    if resolved_config_path:
        with resolved_config_path.open("r", encoding="utf-8") as config_file:
            loaded = yaml.safe_load(config_file) or {}
        if not isinstance(loaded, dict):
            raise EcowittConfigError("Ecowitt config must be a YAML mapping.")
        raw_config = loaded.get("ecowitt", loaded)
        if not isinstance(raw_config, dict):
            raise EcowittConfigError("The 'ecowitt' section must be a YAML mapping.")
        file_config = raw_config

    gw2000_ip = _setting(file_config, "gw2000_ip", "ECOWITT_GW2000_IP")
    if not gw2000_ip:
        raise EcowittConfigError(
            "Missing GW2000 IP. Set ECOWITT_GW2000_IP in .env or ecowitt.gw2000_ip in config.yaml."
        )

    timeout = _setting(file_config, "timeout_seconds", "ECOWITT_TIMEOUT_SECONDS") or "10"
    interval = _setting(file_config, "interval_seconds", "ECOWITT_INTERVAL_SECONDS") or "60"
    data_dir = _setting(file_config, "data_dir", "ARGOS_WEATHER_DATA_DIR") or str(DEFAULT_DATA_DIR)

    return EcowittConfig(
        gw2000_ip=gw2000_ip,
        timeout_seconds=float(timeout),
        interval_seconds=float(interval),
        data_dir=Path(data_dir),
    )


def fetch_livedata(config: EcowittConfig) -> dict[str, Any]:
    try:
        response = requests.get(config.endpoint_url, timeout=config.timeout_seconds)
        response.raise_for_status()
    except Timeout as exc:
        raise EcowittFetchError(f"Timeout querying GW2000 at {config.endpoint_url}") from exc
    except RequestException as exc:
        raise EcowittFetchError(f"GW2000 not accessible at {config.endpoint_url}: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise EcowittFetchError("GW2000 response is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise EcowittFetchError("GW2000 JSON response must be an object.")

    return payload


def parse_livedata(payload: dict[str, Any], captured_at: datetime | None = None) -> dict[str, str]:
    captured_at = captured_at or datetime.now().astimezone()
    common = _items_by_id(payload.get("common_list"))
    rain = _items_by_id(payload.get("piezoRain"))
    wh25 = _first_mapping(payload.get("wh25"))

    row = {column: "" for column in CSV_COLUMNS}
    row["fecha_hora_local"] = captured_at.isoformat(timespec="seconds")
    row["temperatura_exterior"] = _clean_value(common.get("0x02"))
    row["humedad_exterior"] = _clean_value(common.get("0x07"))
    row["presion_absoluta"] = _clean_value(wh25.get("abs"))
    row["presion_relativa"] = _clean_value(wh25.get("rel"))
    row["lluvia_evento"] = _clean_value(rain.get("0x0D"))
    row["lluvia_diaria"] = _clean_value(rain.get("0x10"))
    row["lluvia_intensidad"] = _clean_value(rain.get("0x0E"))
    row["viento_velocidad"] = _clean_value(common.get("0x0B"))
    row["viento_racha"] = _clean_value(common.get("0x0C"))
    row["viento_direccion"] = _clean_value(common.get("0x0A"))
    row["radiacion_solar"] = _clean_value(common.get("0x15"))
    row["uv"] = _clean_value(common.get("0x17"))
    row["bateria_ws90"] = _clean_value(_first_present(rain.get("0x13"), "voltage", "battery"))
    row["condensador_ws90"] = _clean_value(_first_present(rain.get("0x13"), "ws90cap_volt"))

    _warn_unexpected_payload(payload)
    return row


def save_reading(payload: dict[str, Any], row: dict[str, str], data_dir: Path) -> tuple[Path, Path]:
    timestamp = datetime.fromisoformat(row["fecha_hora_local"])
    year = f"{timestamp.year:04d}"
    day = timestamp.date().isoformat()

    csv_path = data_dir / year / f"{day}.csv"
    raw_dir = data_dir / "raw" / year / day
    raw_path = _unique_path(raw_dir / f"{timestamp.strftime('%Y%m%dT%H%M%S%z')}.json")

    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with raw_path.open("w", encoding="utf-8") as raw_file:
        json.dump(payload, raw_file, ensure_ascii=False, indent=2, sort_keys=True)

    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})

    return csv_path, raw_path


def collect_once(config: EcowittConfig) -> tuple[Path, Path]:
    payload = fetch_livedata(config)
    row = parse_livedata(payload)
    return save_reading(payload, row, config.data_dir)


def run_worker(config: EcowittConfig, max_iterations: int | None = None) -> int:
    logger = logging.getLogger(__name__)
    iteration = 0
    logger.info("Starting Ecowitt worker with %.1f second interval.", config.interval_seconds)

    while max_iterations is None or iteration < max_iterations:
        iteration += 1
        try:
            logger.info("Worker iteration %s: querying %s", iteration, config.endpoint_url)
            csv_path, raw_path = collect_once(config)
            logger.info("CSV reading saved to %s", csv_path)
            logger.info("Raw JSON saved to %s", raw_path)
        except EcowittError as exc:
            logger.error("%s", exc)
        except Exception:
            logger.exception("Unexpected error while collecting Ecowitt data.")

        if max_iterations is not None and iteration >= max_iterations:
            break
        time.sleep(config.interval_seconds)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download GW2000 LAN weather readings.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional YAML config file. Defaults to config.yaml if it exists.",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help="Run continuously, collecting one reading every configured interval.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger(__name__)

    try:
        config = load_config(args.config)
        if args.worker:
            return run_worker(config)

        logger.info("Querying Ecowitt GW2000 LAN endpoint: %s", config.endpoint_url)
        csv_path, raw_path = collect_once(config)
    except KeyboardInterrupt:
        logger.info("Ecowitt worker stopped by user.")
        return 0
    except EcowittError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Unexpected error while collecting Ecowitt data.")
        return 1

    logger.info("CSV reading saved to %s", csv_path)
    logger.info("Raw JSON saved to %s", raw_path)
    return 0


def _resolve_config_path(config_path: Path | None) -> Path | None:
    if config_path:
        if not config_path.exists():
            raise EcowittConfigError(f"Config file not found: {config_path}")
        return config_path

    default_path = Path("config.yaml")
    return default_path if default_path.exists() else None


def _setting(config: dict[str, Any], key: str, env_var: str) -> str | None:
    value = config.get(key, os.getenv(env_var))
    return str(value) if value is not None else None


def _items_by_id(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}

    items: dict[str, dict[str, Any]] = {}
    for item in value:
        if isinstance(item, dict) and "id" in item:
            items[str(item["id"])] = item
    return items


def _first_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    if isinstance(value, dict):
        return value
    return {}


def _first_present(item: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        if key in item:
            return item[key]
    return None


def _clean_value(item_or_value: Any) -> str:
    if isinstance(item_or_value, dict):
        value = item_or_value.get("val")
    else:
        value = item_or_value

    if value is None:
        return ""

    text = str(value).strip()
    match = re.match(r"^-?\d+(?:[.,]\d+)?", text)
    if match:
        return match.group(0).replace(",", ".")
    return text


def _warn_unexpected_payload(payload: dict[str, Any]) -> None:
    logger = logging.getLogger(__name__)
    expected_top_level = {"common_list", "piezoRain", "wh25", "debug"}
    for key in sorted(set(payload) - expected_top_level):
        logger.warning("Unexpected GW2000 top-level section: %s", key)

    for section in ("common_list", "piezoRain", "wh25"):
        if section not in payload:
            logger.warning("Expected GW2000 section missing: %s", section)

    for section in ("common_list", "piezoRain"):
        if section in payload and not isinstance(payload[section], list):
            logger.warning("Unexpected GW2000 section type for %s: %s", section, type(payload[section]).__name__)
    if "wh25" in payload and not isinstance(payload["wh25"], list | dict):
        logger.warning("Unexpected GW2000 section type for wh25: %s", type(payload["wh25"]).__name__)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


if __name__ == "__main__":
    raise SystemExit(main())
