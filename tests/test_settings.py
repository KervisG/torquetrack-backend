import copy
import importlib
import logging
import logging.config
import os
import re
import sys

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from rest_framework.test import APIClient

from tests.factories import DEFAULT_PASSWORD, create_user

EXPECTED_APPS = {
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
}


def test_settings_are_configured():
    assert settings.configured


def test_installed_apps_include_drf_and_every_domain_app():
    assert "rest_framework" in settings.INSTALLED_APPS
    assert EXPECTED_APPS.issubset(set(settings.INSTALLED_APPS))


HTTPS_ENV = (
    "SECURE_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SECURE_HSTS_PRELOAD",
    "USE_X_FORWARDED_PROTO",
)
VALID_SECRET_KEY = "k7#Qz!v2Lp9@Xr4$Wm8^Tn3&Hs6*Jd1(Fb5)Gc0-Ye_Ua+Io=Pe"
VALID_APP_URL = "https://shop.example.com"
VALID_BROKER_URL = "redis://redis.internal:6379/0"


def _load_prod(monkeypatch, **environ):
    """`prod.py` valida el entorno al importarse, así que cada test lo recarga
    en vez de reusar el módulo cacheado.

    `CELERY_BROKER_URL` trae un valor válido salvo que el test lo fije; con
    `None` queda sin definir."""
    for name in (
        "DJANGO_SECRET_KEY",
        "RESEND_API_KEY",
        "FROM_EMAIL",
        "APP_URL",
        "CSRF_TRUSTED_ORIGINS",
        "CELERY_BROKER_URL",
        *HTTPS_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    environ = {"CELERY_BROKER_URL": VALID_BROKER_URL, **environ}
    for name, value in environ.items():
        if value is not None:
            monkeypatch.setenv(name, value)
    sys.modules.pop("config.settings.prod", None)
    return importlib.import_module("config.settings.prod")


@pytest.fixture
def prod(monkeypatch):
    return _load_prod(monkeypatch, DJANGO_SECRET_KEY=VALID_SECRET_KEY, APP_URL=VALID_APP_URL)


def test_prod_uses_host_prefixed_cookie_names(prod):

    assert prod.SESSION_COOKIE_NAME == "__Host-sessionid"
    assert prod.CSRF_COOKIE_NAME == "__Host-csrftoken"


def test_prod_cookies_meet_the_host_prefix_requirements(prod):
    # El navegador descarta en silencio una cookie `__Host-` que no sea
    # Secure, que tenga Domain o cuyo Path no sea `/`.

    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SESSION_COOKIE_DOMAIN is None
    assert prod.CSRF_COOKIE_DOMAIN is None
    assert prod.SESSION_COOKIE_PATH == "/"
    assert prod.CSRF_COOKIE_PATH == "/"


@pytest.mark.django_db
def test_login_under_prod_cookie_settings_sets_host_prefixed_secure_cookies(settings, prod):
    for name in (
        "SESSION_COOKIE_NAME",
        "CSRF_COOKIE_NAME",
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
        "SESSION_COOKIE_DOMAIN",
        "CSRF_COOKIE_DOMAIN",
        "SESSION_COOKIE_PATH",
        "CSRF_COOKIE_PATH",
    ):
        setattr(settings, name, getattr(prod, name))
    cache.clear()
    create_user(
        "U_PROD_COOKIES", email="prod.cookies@example.com", password=DEFAULT_PASSWORD
    )

    response = APIClient().post(
        "/api/login/",
        {"email": "prod.cookies@example.com", "password": DEFAULT_PASSWORD},
        format="json",
    )

    assert response.status_code == 200
    for name in ("__Host-sessionid", "__Host-csrftoken"):
        cookie = response.cookies[name]
        assert cookie["secure"] is True
        assert cookie["path"] == "/"
        assert cookie["domain"] == ""


# --- fail-fast de producción -------------------------------------------------


@pytest.mark.parametrize(
    "secret_key",
    [
        None,
        "",
        "insecure-dev-key-change-me",
        "change-me-in-production",
        "django-insecure-" + "a1b2c3d4e5" * 5,
        "short-but-random-7Q!x",
        "a" * 60,
    ],
)
def test_prod_refuses_to_start_without_a_strong_secret_key(monkeypatch, secret_key):
    environ = {} if secret_key is None else {"DJANGO_SECRET_KEY": secret_key}

    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        _load_prod(monkeypatch, **environ)


def test_prod_accepts_a_strong_secret_key(prod):
    assert prod.SECRET_KEY == VALID_SECRET_KEY


@pytest.mark.parametrize(
    "app_url",
    [None, "", "http://shop.example.com", "shop.example.com", "https://"],
)
def test_prod_refuses_to_start_without_an_https_app_url(monkeypatch, app_url):
    # Sin `APP_URL` los enlaces de los correos y el retorno de Stripe caerían
    # en `http://localhost:5173` de `apps/common/links.py`.
    environ = {"DJANGO_SECRET_KEY": VALID_SECRET_KEY}
    if app_url is not None:
        environ["APP_URL"] = app_url

    with pytest.raises(ImproperlyConfigured, match="APP_URL"):
        _load_prod(monkeypatch, **environ)


def test_prod_accepts_an_https_app_url(prod):
    assert prod.APP_URL == VALID_APP_URL


@pytest.mark.parametrize("broker_url", [None, ""])
def test_prod_refuses_to_start_without_a_celery_broker(monkeypatch, broker_url):
    # Sin broker Celery caería en `amqp://localhost` y beat publicaría los
    # trabajos programados a un broker que no existe.
    with pytest.raises(ImproperlyConfigured, match="CELERY_BROKER_URL"):
        _load_prod(
            monkeypatch,
            DJANGO_SECRET_KEY=VALID_SECRET_KEY,
            APP_URL=VALID_APP_URL,
            CELERY_BROKER_URL=broker_url,
        )


def test_prod_accepts_a_celery_broker_url(prod):
    assert prod.CELERY_BROKER_URL == VALID_BROKER_URL


def test_prod_never_runs_tasks_eagerly(prod):
    assert getattr(prod, "CELERY_TASK_ALWAYS_EAGER", False) is False


def test_prod_trusts_the_app_url_origin_for_csrf(monkeypatch):
    prod = _load_prod(
        monkeypatch, DJANGO_SECRET_KEY=VALID_SECRET_KEY, APP_URL="https://shop.example.com/store/"
    )

    assert prod.CSRF_TRUSTED_ORIGINS == ["https://shop.example.com"]


def test_prod_csrf_trusted_origins_can_be_set_from_the_environment(monkeypatch):
    prod = _load_prod(
        monkeypatch,
        DJANGO_SECRET_KEY=VALID_SECRET_KEY,
        APP_URL=VALID_APP_URL,
        CSRF_TRUSTED_ORIGINS="https://shop.example.com,https://admin.example.com",
    )

    assert prod.CSRF_TRUSTED_ORIGINS == ["https://shop.example.com", "https://admin.example.com"]


def test_prod_warns_when_email_settings_are_missing(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="config.settings"):
        _load_prod(monkeypatch, DJANGO_SECRET_KEY=VALID_SECRET_KEY, APP_URL=VALID_APP_URL)

    message = caplog.text
    assert "RESEND_API_KEY" in message
    assert "FROM_EMAIL" in message
    assert "APP_URL" not in message


def test_prod_does_not_warn_when_email_settings_are_present(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="config.settings"):
        _load_prod(
            monkeypatch,
            DJANGO_SECRET_KEY=VALID_SECRET_KEY,
            RESEND_API_KEY="re_test_fake",
            FROM_EMAIL="TorqueTrack <no-reply@example.com>",
            APP_URL=VALID_APP_URL,
        )

    assert caplog.text == ""


# --- cache compartido --------------------------------------------------------


def _load_base(monkeypatch, **environ):
    monkeypatch.delenv("CACHE_URL", raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(importlib.import_module("config.settings.base"))


@pytest.fixture
def restore_base_settings():
    yield
    importlib.reload(importlib.import_module("config.settings.base"))


def test_cache_defaults_to_the_shared_database_cache(monkeypatch, restore_base_settings):
    # Los contadores del throttle tienen que verse desde todos los workers y
    # sobrevivir a un deploy: un cache en memoria del proceso no sirve.
    base = _load_base(monkeypatch)

    assert base.CACHES["default"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"
    assert base.CACHES["default"]["LOCATION"] == "django_cache"


def test_cache_can_be_overridden_with_cache_url(monkeypatch, restore_base_settings):
    base = _load_base(monkeypatch, CACHE_URL="redis://cache.internal:6379/1")

    assert base.CACHES["default"]["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert base.CACHES["default"]["LOCATION"] == "redis://cache.internal:6379/1"


def test_every_throttle_scope_has_a_rate(monkeypatch, restore_base_settings):
    # Un scope sin rate no falla al arrancar: DRF lanza `ImproperlyConfigured`
    # en la primera request a la view y responde 500.
    from rest_framework.throttling import SimpleRateThrottle

    from apps.authentication.utils import throttling

    base = _load_base(monkeypatch)
    rates = base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    scopes = {
        cls.scope
        for cls in vars(throttling).values()
        if isinstance(cls, type)
        and issubclass(cls, SimpleRateThrottle)
        and getattr(cls, "scope", None)
    }

    assert scopes
    assert scopes <= rates.keys()


def test_num_proxies_defaults_to_zero(monkeypatch, restore_base_settings):
    # 0 y no `None`: con `None` DRF confiaría en el `X-Forwarded-For` entero,
    # que escribe el propio cliente.
    monkeypatch.delenv("NUM_PROXIES", raising=False)
    base = _load_base(monkeypatch)

    assert base.REST_FRAMEWORK["NUM_PROXIES"] == 0


def test_num_proxies_comes_from_the_environment(monkeypatch, restore_base_settings):
    base = _load_base(monkeypatch, NUM_PROXIES="1")

    assert base.REST_FRAMEWORK["NUM_PROXIES"] == 1


def test_app_url_defaults_to_the_vite_spa(monkeypatch, restore_base_settings):
    # Los enlaces de los correos y el retorno de Stripe van al SPA de Vite.
    monkeypatch.delenv("APP_URL", raising=False)
    base = _load_base(monkeypatch)

    assert base.APP_URL == "http://localhost:5173"


def test_celery_broker_url_defaults_to_empty(monkeypatch, restore_base_settings):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    base = _load_base(monkeypatch)

    assert base.CELERY_BROKER_URL == ""


def test_celery_broker_url_comes_from_the_environment(monkeypatch, restore_base_settings):
    base = _load_base(monkeypatch, CELERY_BROKER_URL="redis://redis:6379/0")

    assert base.CELERY_BROKER_URL == "redis://redis:6379/0"


def test_dev_runs_tasks_in_process_only_without_a_broker(monkeypatch, restore_base_settings):
    # Sin Redis local `.delay()` intentaría `amqp://localhost`: en dev la
    # tarea corre en el proceso. Con broker, la manda al worker.
    def load_dev(**environ):
        _load_base(monkeypatch, **environ)
        return importlib.reload(importlib.import_module("config.settings.dev"))

    try:
        monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
        without_broker = load_dev()
        assert without_broker.CELERY_TASK_ALWAYS_EAGER is True
        assert without_broker.CELERY_TASK_EAGER_PROPAGATES is True

        with_broker = load_dev(CELERY_BROKER_URL="redis://redis:6379/0")
        assert with_broker.CELERY_TASK_ALWAYS_EAGER is False
    finally:
        monkeypatch.undo()
        importlib.reload(importlib.import_module("config.settings.base"))
        importlib.reload(importlib.import_module("config.settings.dev"))


def test_empty_cache_url_falls_back_to_the_database_cache(monkeypatch, restore_base_settings):
    # `.env.example` deja `CACHE_URL=` vacío; copiarlo a `.env` no puede
    # romper el arranque.
    base = _load_base(monkeypatch, CACHE_URL="")

    assert base.CACHES["default"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"


def test_active_settings_use_the_database_cache():
    assert settings.CACHES["default"]["BACKEND"] == (
        "django.core.cache.backends.db.DatabaseCache"
    )


# --- HTTPS en producción -------------------------------------------------------


def test_prod_forces_https_with_safe_defaults(prod):
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SECURE_HSTS_SECONDS == 31536000
    assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
    # El preload es difícil de revertir (listas de los navegadores): opt-in.
    assert prod.SECURE_HSTS_PRELOAD is False
    assert prod.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert prod.SECURE_REFERRER_POLICY == "same-origin"


def test_prod_trusts_x_forwarded_proto_only_when_enabled(monkeypatch):
    # Sin proxy delante, cualquiera podría mandar el header y hacerse pasar
    # por HTTPS; por eso es opt-in.
    default = _load_prod(monkeypatch, DJANGO_SECRET_KEY=VALID_SECRET_KEY, APP_URL=VALID_APP_URL)
    assert default.SECURE_PROXY_SSL_HEADER is None

    behind_proxy = _load_prod(
        monkeypatch,
        DJANGO_SECRET_KEY=VALID_SECRET_KEY,
        APP_URL=VALID_APP_URL,
        USE_X_FORWARDED_PROTO="true",
    )
    assert behind_proxy.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_prod_https_settings_can_be_tuned_from_the_environment(monkeypatch):
    prod = _load_prod(
        monkeypatch,
        DJANGO_SECRET_KEY=VALID_SECRET_KEY,
        APP_URL=VALID_APP_URL,
        SECURE_SSL_REDIRECT="false",
        SECURE_HSTS_SECONDS="3600",
        SECURE_HSTS_INCLUDE_SUBDOMAINS="false",
        SECURE_HSTS_PRELOAD="true",
    )

    assert prod.SECURE_SSL_REDIRECT is False
    assert prod.SECURE_HSTS_SECONDS == 3600
    assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is False
    assert prod.SECURE_HSTS_PRELOAD is True


def test_prod_exempts_only_the_health_check_from_the_https_redirect(prod):
    exempt = [re.compile(pattern) for pattern in prod.SECURE_REDIRECT_EXEMPT]

    assert any(pattern.search("api/health/") for pattern in exempt)
    assert not any(pattern.search("api/login/") for pattern in exempt)
    assert not any(pattern.search("api/health/extra/") for pattern in exempt)


@pytest.mark.django_db
def test_health_check_answers_plain_http_under_the_prod_redirect(prod):
    with override_settings(
        SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=prod.SECURE_REDIRECT_EXEMPT
    ):
        health = APIClient().get("/api/health/")
        other = APIClient().get("/api/products/")

    assert health.status_code == 200
    assert other.status_code == 301
    assert other["Location"].startswith("https://")


# --- logging -----------------------------------------------------------------


def test_logging_defaults_to_info_on_the_console(monkeypatch, restore_base_settings):
    base = _load_base(monkeypatch)

    assert base.LOGGING["root"] == {"handlers": ["console", "error_email"], "level": "INFO"}
    assert base.LOGGING["handlers"]["console"] == {
        "class": "logging.StreamHandler",
        "formatter": "plain",
    }
    assert base.LOGGING["formatters"]["plain"]["format"] == (
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    assert base.LOGGING["loggers"]["django.request"]["level"] == "WARNING"
    assert base.LOGGING["disable_existing_loggers"] is False


def test_logging_level_comes_from_log_level(monkeypatch, restore_base_settings):
    base = _load_base(monkeypatch, LOG_LEVEL="debug")

    assert base.LOGGING["root"]["level"] == "DEBUG"


def test_logging_config_loads_and_app_loggers_reach_the_root(
    monkeypatch, restore_base_settings
):
    base = _load_base(monkeypatch, LOG_LEVEL="WARNING")
    root = logging.getLogger()
    previous_level, previous_handlers = root.level, root.handlers[:]
    try:
        logging.config.dictConfig(copy.deepcopy(base.LOGGING))
        app_logger = logging.getLogger("apps.checkout.services.payments")

        assert root.level == logging.WARNING
        assert app_logger.propagate is True
        assert app_logger.handlers == []
        assert app_logger.getEffectiveLevel() == logging.WARNING
    finally:
        logging.config.dictConfig(copy.deepcopy(settings.LOGGING))
        root.setLevel(previous_level)
        root.handlers[:] = previous_handlers



def test_error_alert_handler_is_on_the_root_at_error_level(monkeypatch, restore_base_settings):
    base = _load_base(monkeypatch)

    assert base.LOGGING["handlers"]["error_email"] == {
        "class": "config.error_alerts.ErrorEmailHandler",
        "level": "ERROR",
    }


def test_error_alert_emails_default_to_none(monkeypatch, restore_base_settings):
    monkeypatch.delenv("ERROR_ALERT_EMAILS", raising=False)
    base = _load_base(monkeypatch)

    assert base.ERROR_ALERT_EMAILS == []


def test_error_alert_emails_come_from_a_comma_separated_env(
    monkeypatch, restore_base_settings
):
    base = _load_base(monkeypatch, ERROR_ALERT_EMAILS="ops@example.com,owner@example.com")

    assert base.ERROR_ALERT_EMAILS == ["ops@example.com", "owner@example.com"]

# --- datos de la empresa y origen de los envíos ---------------------------------


def test_company_address_and_ship_from_zip_have_defaults(monkeypatch, restore_base_settings):
    monkeypatch.delenv("COMPANY_ADDRESS", raising=False)
    monkeypatch.delenv("SHIP_FROM_ZIP", raising=False)
    base = _load_base(monkeypatch)

    assert base.COMPANY_ADDRESS == "Sarasota, FL"
    assert base.SHIP_FROM_ZIP == "34241"


def test_empty_company_address_and_ship_from_zip_fall_back(monkeypatch, restore_base_settings):
    # Copiar `.env.example` con la variable vacía no puede dejar el origen de
    # los envíos o el pie de la cotización en blanco.
    base = _load_base(monkeypatch, COMPANY_ADDRESS="", SHIP_FROM_ZIP="")

    assert base.COMPANY_ADDRESS == "Sarasota, FL"
    assert base.SHIP_FROM_ZIP == "34241"


def test_company_address_and_ship_from_zip_come_from_the_environment(
    monkeypatch, restore_base_settings
):
    base = _load_base(monkeypatch, COMPANY_ADDRESS="Tampa, FL", SHIP_FROM_ZIP="33602")

    assert base.COMPANY_ADDRESS == "Tampa, FL"
    assert base.SHIP_FROM_ZIP == "33602"


# --- archivos estáticos y puntos de entrada del servidor ------------------------


def test_static_files_are_collected_and_served_by_whitenoise():
    assert settings.STATIC_ROOT == settings.BASE_DIR / "staticfiles"
    security = settings.MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
    assert settings.MIDDLEWARE[security + 1] == "whitenoise.middleware.WhiteNoiseMiddleware"


def test_prod_serves_compressed_hashed_static_files(prod):
    assert prod.STORAGES["staticfiles"]["BACKEND"] == (
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )
    assert prod.STORAGES["default"]["BACKEND"] == (
        "django.core.files.storage.FileSystemStorage"
    )


def test_wsgi_entry_point_defaults_to_prod_settings(monkeypatch):
    # Gunicorn importa `config.wsgi`; si el entorno no define los settings,
    # tiene que caer en producción y no en `dev` con `DEBUG = True`.
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.setattr("django.core.wsgi.get_wsgi_application", lambda: "app")
    monkeypatch.delitem(sys.modules, "config.wsgi", raising=False)

    importlib.import_module("config.wsgi")

    assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings.prod"


def test_api_renders_json_only(monkeypatch, restore_base_settings):
    # Sin la API navegable de DRF: el SPA solo consume JSON y `/api/docs/`
    # ya sirve para explorar la API a mano.
    base = _load_base(monkeypatch)

    assert base.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] == [
        "rest_framework.renderers.JSONRenderer",
    ]


def test_base_refuses_to_start_without_a_secret_key(monkeypatch):
    # Sin fallback en ningún entorno: dev, tests y Docker leen la key de `.env`
    # o del entorno. Se anula `read_env` para que un `.env` local no la aporte.
    import environ

    monkeypatch.setattr(environ.Env, "read_env", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    try:
        with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
            _load_base(monkeypatch)
    finally:
        # Devuelve la key antes de recargar `base` para los demás tests.
        monkeypatch.undo()
        importlib.reload(importlib.import_module("config.settings.base"))
