"""`POST /api/tax/estimate` (task 7.5), pinned against
`app/api/tax/estimate/route.ts` and `lib/tax.ts`.

The real TaxJar REST API is never called: `requests.post` is monkeypatched
at `apps.checkout.services.requests.post` (the shared `calculate_sales_tax`
this view reuses — see `apps.tax.services` module docstring), and no real
`TAXJAR_API_KEY` is ever used.
"""
import pytest
from rest_framework.test import APIClient

from tests.factories import create_customer


def _insert_customer(customer_id, email, tax_status="NOT SUBMITTED"):
    create_customer(customer_id, email=email, tax_status=tax_status)


@pytest.mark.django_db
def test_verified_customer_id_returns_exempt_without_calculation(monkeypatch):
    _insert_customer("cus_verified_tax", "verified@example.com", tax_status="VERIFIED")

    def _boom(*args, **kwargs):
        raise AssertionError("TaxJar must not be called for an exempt customer")

    monkeypatch.setattr("apps.checkout.services.requests.post", _boom)

    response = APIClient().post(
        "/api/tax/estimate/", {"customerId": "cus_verified_tax"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "tax": 0,
        "rate": 0,
        "source": "Tax exempt - certificate verified",
        "exempt": True,
        "provider": "exempt",
    }


@pytest.mark.django_db
def test_non_exempt_customer_uses_fallback_table_when_taxjar_unconfigured(settings):
    settings.TAXJAR_API_KEY = ""
    _insert_customer("cus_not_verified", "notverified@example.com")

    response = APIClient().post(
        "/api/tax/estimate/",
        {"customerId": "cus_not_verified", "subtotal": 100, "state": "FL", "zip": "33701"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tax"] == 6.0
    assert body["rate"] == 0.06
    assert body["provider"] == "fallback"
    assert body["estimated"] is True


@pytest.mark.django_db
def test_no_customer_id_uses_fallback_table_directly(settings):
    settings.TAXJAR_API_KEY = ""

    response = APIClient().post(
        "/api/tax/estimate/", {"amount": 100, "state": "GA", "zip": "30301"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    # GA fallback rate is 0.04.
    assert body["tax"] == 4.0
    assert body["rate"] == 0.04


@pytest.mark.django_db
def test_reads_state_and_zip_from_nested_address():
    from django.test import override_settings

    with override_settings(TAXJAR_API_KEY=""):
        response = APIClient().post(
            "/api/tax/estimate/",
            {"subtotal": 100, "address": {"state": "TX", "zip": "75001"}},
            format="json",
        )

    assert response.status_code == 200
    body = response.json()
    # TX fallback rate is 0.0625.
    assert body["tax"] == 6.25
    assert body["rate"] == 0.0625


@pytest.mark.django_db
def test_taxjar_success_returned_when_configured(settings, monkeypatch):
    settings.TAXJAR_API_KEY = "tj_test_fake"

    class _FakeResponse:
        ok = True

        def json(self):
            return {"tax": {"amount_to_collect": 7.35, "rate": 0.0735}}

    def _fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse()

    monkeypatch.setattr("apps.checkout.services.requests.post", _fake_post)

    response = APIClient().post(
        "/api/tax/estimate/", {"subtotal": 100, "state": "CA", "zip": "90001"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tax"] == 7.35
    assert body["provider"] == "taxjar"
    assert body["estimated"] is False


@pytest.mark.django_db
def test_unknown_state_falls_back_to_zero_rate(settings):
    settings.TAXJAR_API_KEY = ""

    response = APIClient().post(
        "/api/tax/estimate/", {"subtotal": 100, "state": "ZZ", "zip": "00000"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["rate"] == 0
