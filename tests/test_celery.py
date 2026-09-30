"""Cableado de Celery: la app de `config/celery.py`, sus settings y Celery Beat.

Ningún test necesita Redis: `conftest.py` pone las tareas en modo eager y acá
solo se inspecciona la configuración. `CELERY_BEAT_SCHEDULE` es regla de
negocio (literal en `base.py`), así que se fijan los horarios exactos y que
cada entrada apunte a una tarea registrada.
"""
import importlib
import os
import sys

from celery.schedules import crontab
from django.conf import settings

from config import celery_app


def test_config_package_exposes_the_celery_app():
    # `celery -A config` busca `celery_app` (o `app`) en el paquete `config`.
    assert celery_app.main == "config"


def test_celery_entry_point_defaults_to_prod_settings(monkeypatch):
    # El worker y beat importan `config.celery`; sin settings explícitos tienen
    # que caer en producción, igual que `config.wsgi`, nunca en `dev`.
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.delitem(sys.modules, "config.celery", raising=False)
    try:
        importlib.import_module("config.celery")

        assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings.prod"
    finally:
        # El módulo recargado creó otra app de Celery y la dejó como actual.
        celery_app.set_current()


def test_celery_reads_its_settings_from_django_with_the_celery_namespace():
    assert celery_app.conf.timezone == settings.TIME_ZONE
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]


def test_workers_ack_late_and_prefetch_one_task_at_a_time():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_tasks_have_a_soft_limit_below_the_hard_limit():
    soft = celery_app.conf.task_soft_time_limit
    hard = celery_app.conf.task_time_limit

    assert soft and hard
    assert soft < hard


def test_worker_keeps_the_django_logging_config():
    # Si Celery toma el logger raíz, el worker pierde el handler de alertas de
    # error por correo de `LOGGING`.
    assert celery_app.conf.worker_hijack_root_logger is False


def test_tests_run_tasks_eagerly_and_propagate_errors():
    assert celery_app.conf.task_always_eager is True
    assert celery_app.conf.task_eager_propagates is True


def test_beat_schedule_runs_the_maintenance_jobs_at_fixed_times():
    schedule = settings.CELERY_BEAT_SCHEDULE

    assert schedule == {
        "expire-stale-quotes": {
            "task": "apps.quotes.tasks.expire_quotes",
            "schedule": crontab(minute=0),
        },
        "purge-empty-carts": {
            "task": "apps.cart.tasks.purge_carts",
            "schedule": crontab(hour=3, minute=30),
        },
    }


def test_every_beat_entry_points_to_a_registered_task():
    # Un nombre mal escrito no falla al arrancar beat: el worker descarta el
    # mensaje como tarea desconocida.
    celery_app.loader.import_default_modules()

    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        assert entry["task"] in celery_app.tasks
