import importlib
import logging
import sys

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient

from tests.factories import DEFAULT_PASSWORD, create_user

EXPECTED_APPS = {
    "apps.auth",
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


VALID_SECRET_KEY = "k7#Qz!v2Lp9@Xr4$Wm8^Tn3&Hs6*Jd1(Fb5)Gc0-Ye_Ua+Io=Pe"


def _load_prod(monkeypatch, **environ):
    """`prod.py` valida el entorno al importarse, así que cada test lo recarga
    en vez de reusar el módulo cacheado."""
    for name in ("DJANGO_SECRET_KEY", "RESEND_API_KEY", "FROM_EMAIL", "APP_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    sys.modules.pop("config.settings.prod", None)
    return importlib.import_module("config.settings.prod")


@pytest.fixture
def prod(monkeypatch):
    return _load_prod(monkeypatch, DJANGO_SECRET_KEY=VALID_SECRET_KEY)


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


def test_prod_warns_when_email_settings_are_missing(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="config.settings"):
        _load_prod(monkeypatch, DJANGO_SECRET_KEY=VALID_SECRET_KEY)

    message = caplog.text
    assert "RESEND_API_KEY" in message
    assert "FROM_EMAIL" in message
    assert "APP_URL" in message


def test_prod_does_not_warn_when_email_settings_are_present(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="config.settings"):
        _load_prod(
            monkeypatch,
            DJANGO_SECRET_KEY=VALID_SECRET_KEY,
            RESEND_API_KEY="re_test_fake",
            FROM_EMAIL="TorqueTrack <no-reply@example.com>",
            APP_URL="https://shop.example.com",
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


def test_app_url_defaults_to_the_vite_spa(monkeypatch, restore_base_settings):
    # Los enlaces de los correos y el retorno de Stripe van al SPA de Vite.
    monkeypatch.delenv("APP_URL", raising=False)
    base = _load_base(monkeypatch)

    assert base.APP_URL == "http://localhost:5173"


def test_empty_cache_url_falls_back_to_the_database_cache(monkeypatch, restore_base_settings):
    # `env.example` deja `CACHE_URL=` vacío; copiarlo a `.env` no puede
    # romper el arranque.
    base = _load_base(monkeypatch, CACHE_URL="")

    assert base.CACHES["default"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"


def test_active_settings_use_the_database_cache():
    assert settings.CACHES["default"]["BACKEND"] == (
        "django.core.cache.backends.db.DatabaseCache"
    )
