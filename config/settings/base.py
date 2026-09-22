"""Shared Django settings for all environments.

Environment variable names for the integrations shared with the existing
Next.js app (Stripe, TaxJar, EasyPost, Resend, RingCentral, DATABASE_URL,
DATABASE_SSL) are verified against real source usage in
`docs/migration/phase-0-infra-env-validation.md` (Phase 0 output) and MUST
stay in sync with that document.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.auth",
    "apps.accounts",
    "apps.customers",
    "apps.catalog",
    "apps.fitment",
    "apps.cart",
    "apps.checkout",
    "apps.quotes",
    "apps.backoffice",
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
    # Design decision #5 (auth/RBAC): dual session scopes equivalent to
    # the frozen Next.js app's tt_admin/tt_customer cookies. Additive to
    # the generic single-cookie SessionMiddleware above (kept for Django's
    # own admin site and any future generic use); these two attach
    # `request.admin_session` / `request.customer_session` independently.
    "apps.auth.sessions.AdminSessionMiddleware",
    "apps.auth.sessions.CustomerSessionMiddleware",
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

# DATABASE_URL / DATABASE_SSL are shared with the existing Next.js app during
# the strangler migration (design decision #2: one Neon Postgres for both
# stacks). Default points at the local Docker Compose `db` service.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://torquetrack:torquetrack@localhost:5435/torquetrack",
    ),
}
if env.bool("DATABASE_SSL", default=False):
    DATABASES["default"]["OPTIONS"] = {"sslmode": "require"}

# Design decision #5 (auth): `ScryptLegacyHasher` verifies the existing
# Next.js `scrypt$salt$hash` rows and rehashes to PBKDF2 (Django's default)
# on next successful login. Django's OWN `ScryptPasswordHasher` also uses
# `algorithm = "scrypt"` but a different 6-part encoding — it is
# deliberately NOT listed here to avoid colliding with `ScryptLegacyHasher`
# for that same algorithm name (see `apps/accounts/hashers.py`).
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "apps.auth.hashers.ScryptLegacyHasher",
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

# Design decision #5 (auth): 7-day default expiry for both admin and
# customer session scopes (`apps/accounts/sessions.py`), matching
# `lib/auth.ts`'s `newSession(kind, subjectId, days=7)`.
SESSION_COOKIE_AGE = 7 * 24 * 60 * 60

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Solo el scope del login de admin: el resto de los endpoints sigue sin
    # tope para no desviarse del contrato legado en esta fase
    # (`apps/accounts/throttling.py`).
    "DEFAULT_THROTTLE_RATES": {
        "admin_login": env("ADMIN_LOGIN_THROTTLE_RATE", default="10/min"),
    },
}

# Phase 5 (checkout/webhook) integration env vars, names verified against
# real `process.env.*` usage in `docs/migration/phase-0-infra-env-validation.md`
# (Stripe and TaxJar tables) — not assumed.
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
TAXJAR_API_KEY = env("TAXJAR_API_KEY", default="")
SHIP_FROM_ZIP = env("SHIP_FROM_ZIP", default="")
APP_URL = env("APP_URL", default="http://localhost:3000")

# Phase 7 (shipping/rates) — EasyPost, name verified against
# `docs/migration/phase-0-infra-env-validation.md` (Phase 0 output).
EASYPOST_API_KEY = env("EASYPOST_API_KEY", default="")

# Phase 6 (quotes/PDF) — Resend email, names verified against
# `docs/migration/phase-0-infra-env-validation.md` (Phase 0 output).
RESEND_API_KEY = env("RESEND_API_KEY", default="")
FROM_EMAIL = env("FROM_EMAIL", default="")
SALES_EMAIL = env("SALES_EMAIL", default="")
REPLY_TO_EMAIL = env("REPLY_TO_EMAIL", default="")
