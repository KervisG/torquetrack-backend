"""Trivial settings-load test proving the pytest-django TDD foundation works
(Phase 1 deliverable). Kept intentionally minimal: it only proves the Django
project boots and every Phase 1 app skeleton is registered, not any business
logic (that lands per app starting in Phase 2).
"""
from django.conf import settings

EXPECTED_APPS = {
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
}


def test_settings_are_configured():
    assert settings.configured


def test_installed_apps_include_drf_and_all_phase1_app_skeletons():
    assert "rest_framework" in settings.INSTALLED_APPS
    assert EXPECTED_APPS.issubset(set(settings.INSTALLED_APPS))
