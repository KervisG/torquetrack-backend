"""Settings de Django comunes a todos los entornos.

Las integraciones (Stripe, TaxJar, EasyPost, Resend, RingCentral) y la base
de datos (DATABASE_URL, DATABASE_SSL) se configuran por variables de entorno;
`env.example` lista los nombres esperados.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

# Solo sirve en local: `prod.py` se niega a arrancar con este valor.
INSECURE_DEV_SECRET_KEY = "insecure-dev-key-change-me"
SECRET_KEY = env("DJANGO_SECRET_KEY", default=INSECURE_DEV_SECRET_KEY)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.auth",
    "apps.customers",
    "apps.catalog",
    "apps.fitment",
    "apps.cart",
    "apps.checkout",
    "apps.quotes",
    "apps.audit",
    "apps.dashboard",
    "apps.shipping",
    "apps.tax",
    "apps.vin",
    "apps.integrations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# DATABASE_URL / DATABASE_SSL apuntan al Postgres de la app. Por defecto se
# usa el servicio `db` de Docker Compose local.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://torquetrack:torquetrack@localhost:5435/torquetrack",
    ),
}
if env.bool("DATABASE_SSL", default=False):
    DATABASES["default"]["OPTIONS"] = {"sslmode": "require"}

# Cache compartido en Postgres (tabla `django_cache`, la crea la migración
# `tt_auth.0010_cache_table`). Los contadores de los throttles viven aquí y
# tienen que verse desde todos los workers y sobrevivir a un deploy; un
# LocMemCache es por proceso y se vacía al reiniciar. `CACHE_URL` permite
# cambiar de backend sin tocar código (p. ej. `redis://host:6379/1`); vacío
# cuenta como no definida.
CACHES = {
    "default": env.cache_url_config(env("CACHE_URL", default="") or "dbcache://django_cache"),
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Una sola sesión para clientes y staff (`apps/auth/sessions.py`), con 7 días
# de vida, httpOnly y SameSite=Lax. Las cookies usan los nombres por defecto
# de Django (`sessionid`, `csrftoken`); producción les agrega el prefijo
# `__Host-` en `prod.py`.
SESSION_COOKIE_AGE = 7 * 24 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# El SPA recibe el token CSRF en el body de `/api/session/`, login, registro y
# activación, y lo manda en `X-CSRFToken` en cada request que muta. Así no
# depende del nombre de la cookie, que cambia entre entornos.
# El proxy de Vite reescribe el Host, así que el origen del SPA tiene que
# figurar como confiable o Django rechaza el `Origin`.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost:5173"])

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Scopes de los endpoints públicos de cuenta (`apps/auth/utils/throttling.py`).
    # DRF solo entiende periodos `s`, `m`, `h` y `d` (`N/periodo`).
    "DEFAULT_THROTTLE_RATES": {
        "login": env("LOGIN_THROTTLE_RATE", default="10/min"),
        "login_account": env("LOGIN_ACCOUNT_THROTTLE_RATE", default="20/hour"),
        "register": env("REGISTER_THROTTLE_RATE", default="10/hour"),
        "activate": env("ACTIVATE_THROTTLE_RATE", default="10/hour"),
        "password_reset": env("PASSWORD_RESET_THROTTLE_RATE", default="10/hour"),
        "password_reset_account": env("PASSWORD_RESET_ACCOUNT_THROTTLE_RATE", default="5/hour"),
        "password_reset_confirm": env("PASSWORD_RESET_CONFIRM_THROTTLE_RATE", default="10/hour"),
        "verify_email": env("VERIFY_EMAIL_THROTTLE_RATE", default="20/hour"),
        "verify_email_resend": env("VERIFY_EMAIL_RESEND_THROTTLE_RATE", default="5/hour"),
    },
}

# Key de `request.META` con la IP real del cliente para los throttles por IP
# (en producción, `HTTP_CF_CONNECTING_IP`). Solo es confiable si el origen
# acepta tráfico exclusivamente desde Cloudflare (allowlist en el firewall o
# Cloudflare Tunnel); si no, cualquiera puede falsificar el header. Vacío usa
# `REMOTE_ADDR`.
CLIENT_IP_HEADER = env("CLIENT_IP_HEADER", default="")

# Integraciones de checkout y webhook: Stripe y TaxJar.
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
TAXJAR_API_KEY = env("TAXJAR_API_KEY", default="")
SHIP_FROM_ZIP = env("SHIP_FROM_ZIP", default="")
APP_URL = env("APP_URL", default="http://localhost:5173")

# Cotización de envíos: EasyPost.
EASYPOST_API_KEY = env("EASYPOST_API_KEY", default="")

# Emails de cotizaciones, restablecer contraseña y verificar el email: Resend.
RESEND_API_KEY = env("RESEND_API_KEY", default="")
FROM_EMAIL = env("FROM_EMAIL", default="")
SALES_EMAIL = env("SALES_EMAIL", default="")
REPLY_TO_EMAIL = env("REPLY_TO_EMAIL", default="")
