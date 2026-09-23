"""Todo lo configurable sale de variables de entorno; `env.example` las lista."""
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

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://torquetrack:torquetrack@localhost:5435/torquetrack",
    ),
}
if env.bool("DATABASE_SSL", default=False):
    DATABASES["default"]["OPTIONS"] = {"sslmode": "require"}

# Los contadores de los throttles tienen que verse desde todos los workers y
# sobrevivir a un deploy: un LocMemCache es por proceso y se vacía al
# reiniciar. Un `CACHE_URL` vacío cuenta como no definido.
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

# Producción les agrega el prefijo `__Host-` a los nombres de las cookies.
SESSION_COOKIE_AGE = 7 * 24 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# El proxy de Vite reescribe el Host, así que el origen del SPA tiene que
# figurar como confiable o Django rechaza el `Origin`.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost:5173"])

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
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

# Key de `request.META` con la IP real del cliente. Solo es confiable si el
# origen acepta tráfico exclusivamente desde Cloudflare; si no, cualquiera
# puede falsificar el header. Vacío usa `REMOTE_ADDR`.
CLIENT_IP_HEADER = env("CLIENT_IP_HEADER", default="")

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
TAXJAR_API_KEY = env("TAXJAR_API_KEY", default="")
SHIP_FROM_ZIP = env("SHIP_FROM_ZIP", default="")
APP_URL = env("APP_URL", default="http://localhost:5173")
EASYPOST_API_KEY = env("EASYPOST_API_KEY", default="")
RESEND_API_KEY = env("RESEND_API_KEY", default="")
FROM_EMAIL = env("FROM_EMAIL", default="")
SALES_EMAIL = env("SALES_EMAIL", default="")
REPLY_TO_EMAIL = env("REPLY_TO_EMAIL", default="")
