"""Configuración de pytest compartida por todo el repo."""
import pytest


@pytest.fixture(autouse=True, scope="session")
def _celery_tasks_run_in_process():
    """Ningún test llega a Redis, aunque el `.env` local defina
    `CELERY_BROKER_URL`: `.delay()` corre la tarea en el proceso y un error de
    la tarea hace fallar el test en lugar de quedar en el resultado."""
    from config import celery_app

    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
