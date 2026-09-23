"""Trivial settings-load test proving the pytest-django TDD foundation works
(Phase 1 deliverable). Kept intentionally minimal: it only proves the Django
project boots and every Phase 1 app skeleton is registered, not any business
logic (that lands per app starting in Phase 2).
"""
import importlib

import pytest
from django.conf import settings
from django.core.cache import cache
from rest_framework.test import APIClient

from tests.factories import DEFAULT_PASSWORD, create_user

EXPECTED_APPS = {
    "apps.auth",
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
}


def test_settings_are_configured():
    assert settings.configured


def test_installed_apps_include_drf_and_all_phase1_app_skeletons():
    assert "rest_framework" in settings.INSTALLED_APPS
    assert EXPECTED_APPS.issubset(set(settings.INSTALLED_APPS))


def _prod_settings():
    return importlib.import_module("config.settings.prod")


def test_prod_uses_host_prefixed_cookie_names():
    prod = _prod_settings()

    assert prod.SESSION_COOKIE_NAME == "__Host-sessionid"
    assert prod.CSRF_COOKIE_NAME == "__Host-csrftoken"


def test_prod_cookies_meet_the_host_prefix_requirements():
    # El navegador descarta en silencio una cookie `__Host-` que no sea
    # Secure, que tenga Domain o cuyo Path no sea `/`.
    prod = _prod_settings()

    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SESSION_COOKIE_DOMAIN is None
    assert prod.CSRF_COOKIE_DOMAIN is None
    assert prod.SESSION_COOKIE_PATH == "/"
    assert prod.CSRF_COOKIE_PATH == "/"


@pytest.mark.django_db
def test_login_under_prod_cookie_settings_sets_host_prefixed_secure_cookies(settings):
    prod = _prod_settings()
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
