from __future__ import annotations

from dataclasses import dataclass

from kombu.exceptions import OperationalError

from argos.worker.celery_app import app as celery_app


@dataclass(frozen=True)
class EnqueuedTask:
    task_id: str


class DashboardTaskError(RuntimeError):
    """Raised when the dashboard cannot enqueue a background task."""


def enqueue_ecowitt_update() -> EnqueuedTask:
    try:
        result = celery_app.send_task("argos.worker.tasks.weather.collect_ecowitt")
    except OperationalError as exc:
        raise DashboardTaskError(f"No se pudo conectar con Redis/Celery: {exc}") from exc
    except Exception as exc:
        raise DashboardTaskError(f"No se pudo encolar la actualizacion: {exc}") from exc

    return EnqueuedTask(task_id=result.id)
