from __future__ import annotations

import os


def weather_schedule() -> dict[str, dict]:
    interval_seconds = float(os.getenv("ECOWITT_INTERVAL_SECONDS", "60"))
    return {
        "ecowitt_collect_every_interval": {
            "task": "argos.worker.tasks.weather.collect_ecowitt",
            "schedule": interval_seconds,
        },
    }
