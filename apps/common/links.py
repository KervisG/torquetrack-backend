from django.conf import settings

DEFAULT_APP_URL = "http://localhost:5173"


def app_url(path: str = "") -> str:
    """URL absoluta del SPA para enlaces que salen por correo o hacia Stripe.

    El respaldo cubre un `APP_URL=` vacío en el `.env` de desarrollo, que pisa
    el default de `settings`. En producción nunca se usa: `prod.py` lanza
    `ImproperlyConfigured` si `APP_URL` falta o no es `https://`.
    """
    return f"{(settings.APP_URL or DEFAULT_APP_URL).rstrip('/')}{path}"
