from __future__ import annotations

from celery import shared_task

from argos.weather.ecowitt import collect_once, load_config


@shared_task(name="argos.worker.tasks.weather.collect_ecowitt")
def collect_ecowitt() -> dict[str, str]:
    config = load_config()
    csv_path, raw_path = collect_once(config)
    return {
        "csv_path": str(csv_path),
        "raw_path": str(raw_path),
    }
