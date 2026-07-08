from datetime import datetime
from pathlib import Path

import pytest

from argos.weather import ecowitt
from argos.weather.ecowitt import EcowittConfig, load_config, parse_livedata, run_worker, save_reading


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_load_config_reads_gw2000_ip_from_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ECOWITT_GW2000_IP", raising=False)
    monkeypatch.delenv("ECOWITT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("ARGOS_WEATHER_DATA_DIR", raising=False)

    config = load_config(FIXTURES_DIR / "ecowitt.yaml")

    assert config == EcowittConfig(
        gw2000_ip="192.168.1.137",
        timeout_seconds=2.5,
        interval_seconds=60.0,
        data_dir=Path("data/weather"),
    )


def test_parse_livedata_extracts_real_gw2000_shape() -> None:
    payload = _fixture_payload()
    row = parse_livedata(payload, datetime.fromisoformat("2026-07-08T23:30:00+02:00"))

    assert row == {
        "fecha_hora_local": "2026-07-08T23:30:00+02:00",
        "temperatura_exterior": "33.0",
        "humedad_exterior": "14",
        "presion_absoluta": "940.6",
        "presion_relativa": "940.6",
        "lluvia_evento": "0.0",
        "lluvia_diaria": "0.0",
        "lluvia_intensidad": "0.0",
        "viento_velocidad": "0.00",
        "viento_racha": "0.00",
        "viento_direccion": "307",
        "radiacion_solar": "0.00",
        "uv": "0",
        "bateria_ws90": "3.02",
        "condensador_ws90": "1.3",
    }


def test_parse_livedata_uses_empty_values_for_missing_fields() -> None:
    row = parse_livedata({}, datetime.fromisoformat("2026-07-08T23:30:00+02:00"))

    assert row["fecha_hora_local"] == "2026-07-08T23:30:00+02:00"
    assert all(value == "" for key, value in row.items() if key != "fecha_hora_local")


def test_save_reading_appends_daily_csv_and_raw_json() -> None:
    payload = _fixture_payload()
    row = parse_livedata(payload, datetime.fromisoformat("2026-07-08T23:30:00+02:00"))
    data_dir = Path("tests/.tmp/weather-data")
    _clean_test_dir(data_dir)

    csv_path, raw_path = save_reading(payload, row, data_dir)
    _, second_raw_path = save_reading(payload, row, data_dir)

    assert csv_path == data_dir / "2026" / "2026-07-08.csv"
    assert raw_path == data_dir / "raw" / "2026" / "2026-07-08" / "20260708T233000+0200.json"
    assert second_raw_path == data_dir / "raw" / "2026" / "2026-07-08" / "20260708T233000+0200_2.json"
    assert csv_path.read_text(encoding="utf-8").count("\n") == 3
    assert raw_path.exists()
    assert second_raw_path.exists()

    _clean_test_dir(data_dir)


def test_run_worker_collects_multiple_iterations_without_stopping_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    sleeps = []

    def fake_collect_once(config: EcowittConfig) -> tuple[Path, Path]:
        calls.append(config)
        if len(calls) == 2:
            raise ecowitt.EcowittFetchError("temporary failure")
        return Path("reading.csv"), Path("raw.json")

    monkeypatch.setattr(ecowitt, "collect_once", fake_collect_once)
    monkeypatch.setattr(ecowitt.time, "sleep", lambda seconds: sleeps.append(seconds))

    config = EcowittConfig(gw2000_ip="192.168.1.137", interval_seconds=5)
    result = run_worker(config, max_iterations=3)

    assert result == 0
    assert len(calls) == 3
    assert sleeps == [5, 5]


def _fixture_payload() -> dict:
    return {
        "common_list": [
            {"id": "0x02", "val": "33.0", "unit": "C"},
            {"id": "0x07", "val": "14%"},
            {"id": "0x0B", "val": "0.00 km/h"},
            {"id": "0x0C", "val": "0.00 km/h"},
            {"id": "0x15", "val": "0.00 W/m2"},
            {"id": "0x17", "val": "0"},
            {"id": "0x0A", "val": "307"},
        ],
        "piezoRain": [
            {"id": "srain_piezo", "val": "0"},
            {"id": "0x0D", "val": "0.0 mm"},
            {"id": "0x0E", "val": "0.0 mm/Hr"},
            {"id": "0x10", "val": "0.0 mm"},
            {
                "id": "0x13",
                "val": "0.6 mm",
                "battery": "5",
                "voltage": "3.02",
                "ws90cap_volt": "1.3",
                "ws90_ver": "160",
            },
        ],
        "wh25": [{"intemp": "26.7", "unit": "C", "inhumi": "34%", "abs": "940.6 hPa", "rel": "940.6 hPa"}],
        "debug": [{"heap": "85928"}],
    }


def _clean_test_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()
