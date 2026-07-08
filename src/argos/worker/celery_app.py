from __future__ import annotations

import os

from celery import Celery

from argos.worker.scheduled.weather import weather_schedule


DEFAULT_BROKER_URL = "redis://localhost:6379/0"


def create_app() -> Celery:
    broker_url = os.getenv("ARGOS_BROKER_URL", os.getenv("BROKER_URL", DEFAULT_BROKER_URL))
    result_backend = os.getenv("ARGOS_RESULT_BACKEND", os.getenv("RESULT_BACKEND", broker_url))

    celery_app = Celery(
        "argos",
        broker=broker_url,
        backend=result_backend,
        include=["argos.worker.tasks.weather"],
    )
    celery_app.conf.timezone = os.getenv("ARGOS_TIMEZONE", "Europe/Madrid")
    celery_app.conf.beat_schedule = weather_schedule()
    celery_app.conf.broker_connection_retry_on_startup = True
    return celery_app


app = create_app()
