"""Todo lo configurable sale de variables de entorno; `.env.example` las lista."""
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

# Sin fallback en ningún entorno: firma sesiones, CSRF y enlaces por correo.
# En local y en los tests sale de `.env`; `prod.py` además exige que sea fuerte.
SECRET_KEY = env("DJANGO_SECRET_KEY")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    # `authorization` va antes: `authentication.User.role` apunta a su `Role`.
    "apps.authorization",
    "apps.authentication",
    "apps.customers",
    "apps.catalog",
    "apps.fitment",
    "apps.cart",
    "apps.checkout",
    "apps.numbering",
    "apps.quotes",
    "apps.audit",
    "apps.dashboard",
    "apps.shipping",
    "apps.tax",
    "apps.vin",
    "apps.integrations",
    "apps.health",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Sirve `STATIC_ROOT` (admin) desde el mismo proceso: el hosting no tiene
    # un servidor de estáticos delante.
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

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

# Auth estándar de Django: el `User` propio es el modelo de cuentas (también
# de `/django-admin/`). El login es el `ModelBackend` por defecto y los permisos
# salen de `User.has_perm`, que lee solo el Role.
AUTH_USER_MODEL = "authentication.User"

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
# `collectstatic` copia acá los estáticos al construir la imagen.
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery (`config/celery.py`). El broker es infraestructura y sale del entorno;
# vacío, `dev.py` corre las tareas en el proceso y `prod.py` no arranca.
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="")
# El worker reintenta conectar al arrancar: espera a Redis en lugar de caerse
# si levanta después. Explícito porque Celery 5.x avisa si queda implícito.
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
# Sin backend de resultados: nadie espera el valor de una tarea y el worker ya
# lo escribe en su log.
CELERY_TASK_IGNORE_RESULT = True
# El mensaje se confirma al terminar la tarea: si el worker muere a mitad
# (deploy, OOM), Redis la vuelve a entregar. Exige tareas idempotentes. Con
# prefetch 1 cada proceso reserva una sola tarea, así una larga no deja otras
# encoladas detrás de ella mientras hay procesos libres.
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# El límite blando lanza `SoftTimeLimitExceeded` para cerrar en orden; el duro
# mata el proceso. Ambos muy por debajo del `visibility_timeout` de Redis (1 h),
# así una tarea viva nunca se entrega dos veces.
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_TIME_LIMIT = 300
# El worker conserva `LOGGING` (consola y alertas de error por correo) en lugar
# de reemplazar los handlers del logger raíz por los suyos.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# Trabajos programados (regla de negocio, literal). Horarios en `CELERY_TIMEZONE`
# (UTC). Los comandos `expire_quotes` y `purge_carts` siguen para correrlos a mano.
CELERY_BEAT_SCHEDULE = {
    "expire-stale-quotes": {
        "task": "apps.quotes.tasks.expire_quotes",
        "schedule": crontab(minute=0),
    },
    "purge-empty-carts": {
        "task": "apps.cart.tasks.purge_carts",
        "schedule": crontab(hour=3, minute=30),
    },
}

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
    # Cerrado por defecto: una view que olvide declarar permisos queda solo
    # para staff. Igual toda view declara `permission_classes` explícito
    # (`AllowAny` las públicas); `tests/test_view_permissions.py` lo exige.
    "DEFAULT_PERMISSION_CLASSES": [
        "apps.authorization.permissions.HasRolePermission",
    ],
    # Un solo formato de error: `{"error": ...}` también para los que arma DRF.
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
    # Solo JSON, sin la API navegable: el SPA no la usa y `/api/docs/` ya
    # sirve para explorar la API a mano.
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # DRF solo entiende periodos `s`, `m`, `h` y `d` (`N/periodo`).
    "DEFAULT_THROTTLE_RATES": {
        "login": "10/min",
        "login_account": "20/hour",
        "register": "10/hour",
        "activate": "10/hour",
        "password_reset": "10/hour",
        "password_reset_account": "5/hour",
        "password_reset_confirm": "10/hour",
        "verify_email": "20/hour",
        "verify_email_resend": "5/hour",
        # Storefront público. El SPA pide envío, impuesto y VIN solo al tocar
        # un botón, y el impuesto una vez más al pagar: los topes dejan margen
        # para corregir la dirección varias veces sin bloquear a un cliente.
        "checkout": "10/hour",
        "quote_checkout": "10/hour",
        "quote_request": "10/hour",
        "quote_pdf": "20/hour",
        "shipping_rates": "30/min",
        "tax_estimate": "30/min",
        "vin_decode": "20/min",
        "fitment_check": "30/min",
    },
    # Proxies de confianza que agregan su entrada a `X-Forwarded-For` (ver
    # `get_client_ip`). 0 y no el `None` de DRF: con `None` DRF usaría el
    # header entero, que escribe el propio cliente.
    "NUM_PROXIES": env.int("NUM_PROXIES", default=0),
}

# `/api/schema/`, `/api/docs/` y `/api/redoc/`. Describen también las rutas
# del panel, así que solo las ve el staff con sesión.
SPECTACULAR_SETTINGS = {
    "TITLE": "TorqueTrack Diesel API",
    "DESCRIPTION": "Storefront and admin API for TorqueTrack Diesel.",
    "VERSION": "1.0.0",
    "SCHEMA_PATH_PREFIX": r"/api/(admin/)?",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_AUTHENTICATION": ["rest_framework.authentication.SessionAuthentication"],
    "SERVE_PERMISSIONS": ["apps.authorization.permissions.HasRolePermission"],
    # Varios campos se llaman `status` con conjuntos distintos. Sin esto
    # spectacular les pone un nombre con hash (`Status6b4Enum`) o reutiliza
    # `FulfillmentStatusEnum` para dos conjuntos.
    "ENUM_NAME_OVERRIDES": {
        "OrderStatusEnum": "apps.checkout.models.order.OrderStatus",
        "OrderPaymentStatusEnum": "apps.checkout.models.order.OrderPaymentStatus",
        "FulfillmentStatusEnum": "apps.checkout.models.order.FulfillmentStatus",
        "PaymentStatusEnum": "apps.checkout.models.payment.PaymentStatus",
        "RefundStatusEnum": "apps.checkout.models.refund.RefundStatus",
        "QuoteStatusEnum": "apps.quotes.models.quote.QuoteStatus",
        "CartStatusEnum": "apps.cart.models.cart.CartStatus",
        "TaxStatusEnum": "apps.customers.models.customer.TaxStatus",
    },
}

# Key de `request.META` con la IP real del cliente. Solo es confiable si el
# origen acepta tráfico exclusivamente desde Cloudflare; si no, cualquiera
# puede falsificar el header. Vacío usa `REMOTE_ADDR`.
CLIENT_IP_HEADER = env("CLIENT_IP_HEADER", default="")

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
TAXJAR_API_KEY = env("TAXJAR_API_KEY", default="")
# Origen de los envíos (EasyPost) y del impuesto (TaxJar). Un valor vacío
# cuenta como no definido, igual que `CACHE_URL`.
SHIP_FROM_ZIP = env("SHIP_FROM_ZIP", default="") or "34241"
APP_URL = env("APP_URL", default="http://localhost:5173")
EASYPOST_API_KEY = env("EASYPOST_API_KEY", default="")
RESEND_API_KEY = env("RESEND_API_KEY", default="")
FROM_EMAIL = env("FROM_EMAIL", default="")
SALES_EMAIL = env("SALES_EMAIL", default="")
REPLY_TO_EMAIL = env("REPLY_TO_EMAIL", default="")
# Dirección que muestran la cotización y su PDF junto a `SALES_EMAIL` y
# `APP_URL`.
COMPANY_ADDRESS = env("COMPANY_ADDRESS", default="") or "Sarasota, FL"

# Todo sale por consola (el hosting recoge stdout/stderr). El formato no lleva
# datos del request: lo que se loguea son mensajes propios, que nunca incluyen
# tokens, contraseñas ni datos personales. Los loggers `apps.*` no tienen
# handler propio y propagan al root, así `LOG_LEVEL` los gobierna a todos.
LOG_LEVEL = env("LOG_LEVEL", default="INFO").upper()
# Destinatarios de las alertas de error por correo (`config/error_alerts.py`,
# vía Resend con `FROM_EMAIL`), separados por comas. Vacío las apaga: local y
# tests no mandan nada.
ERROR_ALERT_EMAILS = env.list("ERROR_ALERT_EMAILS", default=[])
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        # Un correo por error distinto cada 15 minutos; no toca la consola.
        "error_email": {"class": "config.error_alerts.ErrorEmailHandler", "level": "ERROR"},
    },
    "root": {"handlers": ["console", "error_email"], "level": LOG_LEVEL},
    "loggers": {
        # Sin los handlers por defecto de Django (consola solo con DEBUG y
        # `mail_admins`): todo va al root, sin duplicar líneas.
        "django": {"handlers": [], "level": "INFO", "propagate": True},
        # 4xx y 5xx de las views; con INFO no aporta nada más.
        "django.request": {"handlers": [], "level": "WARNING", "propagate": True},
        "apps": {"handlers": [], "propagate": True},
    },
}
