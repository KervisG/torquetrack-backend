# Carga la app de Celery con Django, así `@shared_task` se liga a ella en
# cualquier proceso (runserver, gunicorn, worker, tests).
from .celery import app as celery_app

__all__ = ("celery_app",)
