from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])  # noqa: F405

# Cookies de sesión y CSRF con el prefijo `__Host-`. El navegador solo acepta
# una cookie con ese prefijo si es Secure, tiene Path=/ y no tiene Domain, así
# que queda atada al host exacto: un subdominio (o una respuesta HTTP en
# claro) no puede sobrescribirla ni inyectar una propia para fijar la sesión
# o el token CSRF. Solo aplica en producción porque exige HTTPS; en
# http://localhost algunos navegadores descartarían la cookie y no habría
# sesión. El SPA no depende del nombre: recibe el token CSRF en el body.
SESSION_COOKIE_NAME = "__Host-sessionid"
CSRF_COOKIE_NAME = "__Host-csrftoken"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_PATH = "/"
CSRF_COOKIE_PATH = "/"
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
