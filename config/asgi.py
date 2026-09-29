import os

from django.core.asgi import get_asgi_application

# Punto de entrada del servidor (gunicorn): sin settings explícitos arranca
# en producción, nunca en `dev` con `DEBUG = True`.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
