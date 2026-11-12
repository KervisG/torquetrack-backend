"""Configuración de pytest compartida por todo el repo."""
import pytest


@pytest.fixture(autouse=True, scope="session")
def _celery_tasks_run_in_process():
    """Ningún test llega a Redis, aunque el `.env` local defina
    `CELERY_BROKER_URL`: `.delay()` corre la tarea en el proceso y un error de
    la tarea hace fallar el test en lugar de quedar en el resultado."""
    from config import celery_app

    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)


@pytest.fixture(autouse=True)
def _no_deployment_settings_from_the_local_env(settings):
    """Los tests leen el `.env` local (base y `SECRET_KEY`), pero no heredan lo
    que solo tiene sentido desplegado. Con `ERROR_ALERT_EMAILS` cada test que
    simula un 502 de un proveedor mandaba una alerta real por correo; con
    `NUM_PROXIES` el throttle confiaba en un `X-Forwarded-For` que no existe.
    Los tests que prueban esas opciones las fijan ellos mismos."""
    settings.ERROR_ALERT_EMAILS = []
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}


@pytest.fixture(autouse=True)
def _email_logo_from_the_app_url(settings):
    """El logo de los correos sale de `APP_URL`, aunque el `.env` local tenga
    Spaces configurado: los tests no dependen del bucket de quien los corre."""
    settings.EMAIL_LOGO_URL = ""
