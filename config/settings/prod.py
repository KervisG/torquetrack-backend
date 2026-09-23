from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])  # noqa: F405

# Cookies de sesión y CSRF solo por HTTPS fuera de desarrollo.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
