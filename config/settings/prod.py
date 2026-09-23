import logging

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

logger = logging.getLogger("config.settings")

DEBUG = False


def _is_weak_secret_key(value: str) -> bool:
    # Mismos criterios que `security.W009` de `check --deploy`, más los
    # valores de ejemplo del repo: con una key conocida cualquiera firma
    # cookies de sesión y tokens.
    return (
        not value
        or value in {INSECURE_DEV_SECRET_KEY, "change-me-in-production"}  # noqa: F405
        or value.startswith("django-insecure-")
        or len(value) < 50
        or len(set(value)) < 5
    )


SECRET_KEY = env("DJANGO_SECRET_KEY", default="")  # noqa: F405
if _is_weak_secret_key(SECRET_KEY):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a random value of at least 50 characters "
        "in production."
    )

# Sin correo no llegan los enlaces de reset de contraseña ni de verificación,
# pero la tienda funciona igual: se avisa en lugar de impedir el arranque.
RESEND_API_KEY = env("RESEND_API_KEY", default="")  # noqa: F405
FROM_EMAIL = env("FROM_EMAIL", default="")  # noqa: F405
APP_URL = env("APP_URL", default="")  # noqa: F405
_missing_email_settings = [
    name
    for name, value in (
        ("RESEND_API_KEY", RESEND_API_KEY),
        ("FROM_EMAIL", FROM_EMAIL),
        ("APP_URL", APP_URL),
    )
    if not value
]
if _missing_email_settings:
    logger.warning(
        "Account emails are disabled or will carry broken links; missing: %s",
        ", ".join(_missing_email_settings),
    )
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
