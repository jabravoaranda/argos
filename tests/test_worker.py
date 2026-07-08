from pathlib import Path

from argos.weather.ecowitt import EcowittConfig
from argos.worker.scheduled.weather import weather_schedule
from argos.worker.tasks import weather


def test_weather_schedule_uses_interval_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("ECOWITT_INTERVAL_SECONDS", "30")

    schedule = weather_schedule()

    assert schedule == {
        "ecowitt_collect_every_interval": {
            "task": "argos.worker.tasks.weather.collect_ecowitt",
            "schedule": 30.0,
        },
    }


def test_collect_ecowitt_task_runs_collector(monkeypatch) -> None:
    config = EcowittConfig(gw2000_ip="192.168.1.137")

    monkeypatch.setattr(weather, "load_config", lambda: config)
    monkeypatch.setattr(
        weather,
        "collect_once",
        lambda loaded_config: (Path("data/weather/2026/2026-07-08.csv"), Path("data/weather/raw/file.json")),
    )

    result = weather.collect_ecowitt.run()

    assert result == {
        "csv_path": "data\\weather\\2026\\2026-07-08.csv",
        "raw_path": "data\\weather\\raw\\file.json",
    }
