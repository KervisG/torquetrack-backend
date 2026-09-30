"""App de Celery del proyecto (worker y beat: `celery -A config worker|beat`).

Sigue la integración oficial con Django: la configuración sale de `settings`
con el prefijo `CELERY_` y cada app declara sus tareas en `apps/<app>/tasks.py`,
que `autodiscover_tasks()` encuentra por `INSTALLED_APPS`.
"""
import os

from celery import Celery

# Igual que `config/wsgi.py`: sin settings explícitos el worker arranca en
# producción, nunca en `dev` con `DEBUG = True`.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
