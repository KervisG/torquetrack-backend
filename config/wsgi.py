import os

from django.core.wsgi import get_wsgi_application

# Punto de entrada del servidor (gunicorn): sin settings explícitos arranca
# en producción, nunca en `dev` con `DEBUG = True`.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
