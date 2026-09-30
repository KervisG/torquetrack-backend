import logging
from urllib.parse import urlsplit

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
        or value in {"insecure-dev-key-change-me", "change-me-in-production"}
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

# `APP_URL` arma el retorno de Stripe y los enlaces de los correos y de la
# cotización. Sin él caerían en `http://localhost:5173` (`apps/common/links.py`),
# así que producción no arranca con un valor vacío o sin HTTPS.
APP_URL = env("APP_URL", default="")  # noqa: F405
_app_url = urlsplit(APP_URL)
if _app_url.scheme != "https" or not _app_url.netloc:
    raise ImproperlyConfigured(
        "APP_URL must be set to the https:// URL of the storefront in production."
    )

# El SPA manda el `Origin` de `APP_URL`; el default de `base.py` es el de Vite
# en local. `CSRF_TRUSTED_ORIGINS` lo reemplaza si el panel vive en otro origen.
CSRF_TRUSTED_ORIGINS = env.list(  # noqa: F405
    "CSRF_TRUSTED_ORIGINS", default=[f"{_app_url.scheme}://{_app_url.netloc}"]
)

# Sin correo no llegan los enlaces de reset de contraseña ni de verificación,
# pero la tienda funciona igual: se avisa en lugar de impedir el arranque.
RESEND_API_KEY = env("RESEND_API_KEY", default="")  # noqa: F405
FROM_EMAIL = env("FROM_EMAIL", default="")  # noqa: F405
_missing_email_settings = [
    name
    for name, value in (
        ("RESEND_API_KEY", RESEND_API_KEY),
        ("FROM_EMAIL", FROM_EMAIL),
    )
    if not value
]
if _missing_email_settings:
    logger.warning(
        "Account emails are disabled or will carry broken links; missing: %s",
        ", ".join(_missing_email_settings),
    )
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])  # noqa: F405

# El prefijo `__Host-` exige Secure, Path=/ y sin Domain, así que la cookie
# queda atada al host exacto: un subdominio o una respuesta HTTP en claro no
# puede sobrescribirla para fijar la sesión o el token CSRF. Solo aplica en
# producción porque exige HTTPS; el SPA recibe el token CSRF en el body y no
# depende del nombre.
SESSION_COOKIE_NAME = "__Host-sessionid"
CSRF_COOKIE_NAME = "__Host-csrftoken"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_PATH = "/"
CSRF_COOKIE_PATH = "/"
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None

# HTTPS obligatorio. `SECURE_SSL_REDIRECT` responde 301 a todo request en
# claro, salvo el health check: muchos hostings lo pingan por HTTP dentro de su
# red y un 301 lo daría por caído.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
# Un año de HSTS por defecto. El preload es opt-in: salir de la lista de los
# navegadores tarda meses.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(  # noqa: F405
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)  # noqa: F405
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# Detrás de un proxy que termina TLS (Cloudflare, el balanceador del hosting)
# Django ve HTTP y, con el redirect activo, entraría en un bucle de 301. Solo
# se activa si el proxy SIEMPRE escribe `X-Forwarded-Proto` y el origen no es
# alcanzable sin pasar por él; si no, cualquiera podría mandar el header.
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if env.bool("USE_X_FORWARDED_PROTO", default=False)  # noqa: F405
    else None
)

# IP del cliente para los throttles: `base.py` lee `CLIENT_IP_HEADER`
# (Cloudflare) y `NUM_PROXIES` (proxies de confianza que agregan su entrada a
# `X-Forwarded-For`). Detrás del proxy del mismo dominio que sirve el SPA y la
# API, sin ninguno de los dos todos los clientes comparten la IP del proxy y
# un mismo tope; con `NUM_PROXIES` mayor que los proxies reales, cualquiera
# elige su IP.

# Estáticos con hash en el nombre y comprimidos (gzip/brotli), servidos por
# WhiteNoise con caché larga. Exige `collectstatic` antes de arrancar: el
# `Dockerfile` lo corre al construir la imagen.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
