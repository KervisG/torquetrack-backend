"""Tests de `POST /api/tax/estimate`.

La exención sale solo de la sesión: una cuenta con un `Customer` vinculado
cuyo `tax_status` es `VERIFIED` recibe impuesto 0. Cualquier `customerId`
del body se ignora; si no, cualquiera que conociera el id de un cliente
obtendría una estimación exenta y sabría su estado fiscal. Con sesión se
exige CSRF, igual que en el checkout.

Mocking: TaxJar se falsea en su adaptador,
`apps.integrations.tax.taxjar.calculate_tax`. Los caminos exentos lo
parchean con una función que lanza `AssertionError`.
"""
import pytest
from rest_framework.test import APIClient

from apps.integrations.exceptions import ProviderError
from tests.factories import create_customer, create_staff_user, create_user, session_client

EXEMPT = {
    "tax": 0,
    "rate": 0,
    "source": "Tax exempt - certificate verified",
    "exempt": True,
    "provider": "exempt",
}
FL_REQUEST = {"subtotal": 100, "state": "FL", "zip": "33701"}


@pytest.fixture(autouse=True)
def _taxjar_off(settings):
    settings.TAXJAR_API_KEY = ""


def _no_taxjar(monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("TaxJar must not be called for an exempt customer")

    monkeypatch.setattr("apps.integrations.tax.taxjar.calculate_tax", _boom)


def _account(user_id, tax_status):
    user = create_user(user_id, email=f"{user_id.lower()}@example.com")
    create_customer(f"C_{user_id}", email=user.email, user=user, tax_status=tax_status)
    client, _ = session_client(user_id)
    return client


# --- exención ---------------------------------------------------------------


@pytest.mark.django_db
def test_body_customer_id_of_a_verified_customer_is_ignored_for_anonymous():
    create_customer("cus_verified_tax", email="verified@example.com", tax_status="VERIFIED")

    response = APIClient().post(
        "/api/tax/estimate/", {"customerId": "cus_verified_tax", **FL_REQUEST}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body.get("exempt") is not True
    assert body["tax"] == 6.0
    assert body["provider"] == "fallback"


@pytest.mark.django_db
def test_signed_in_verified_customer_gets_exempt_estimate(monkeypatch):
    _no_taxjar(monkeypatch)
    client = _account("U_VERIFIED", tax_status="VERIFIED")

    response = client.post("/api/tax/estimate/", FL_REQUEST, format="json")

    assert response.status_code == 200
    assert response.json() == EXEMPT


@pytest.mark.django_db
def test_signed_in_customer_cannot_borrow_another_customers_exemption():
    create_customer("cus_other_verified", email="other@example.com", tax_status="VERIFIED")
    client = _account("U_PLAIN", tax_status="NOT SUBMITTED")

    response = client.post(
        "/api/tax/estimate/", {"customerId": "cus_other_verified", **FL_REQUEST}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["tax"] == 6.0


@pytest.mark.django_db
def test_signed_in_non_verified_customer_pays_normal_tax():
    client = _account("U_PENDING", tax_status="PENDING")

    response = client.post("/api/tax/estimate/", FL_REQUEST, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["tax"] == 6.0
    assert body["rate"] == 0.06


@pytest.mark.django_db
def test_staff_without_profile_pays_normal_tax():
    create_staff_user("U_STAFF", full_access=True)
    client, _ = session_client("U_STAFF")

    response = client.post("/api/tax/estimate/", FL_REQUEST, format="json")

    assert response.status_code == 200
    assert response.json()["tax"] == 6.0


@pytest.mark.django_db
def test_signed_in_request_without_csrf_is_rejected():
    create_user("U_CSRF", email="csrf@example.com")
    client, _ = session_client("U_CSRF", enforce_csrf=True)

    response = client.post("/api/tax/estimate/", FL_REQUEST, format="json")

    assert response.status_code == 403


# --- cálculo ----------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_uses_fallback_table_when_taxjar_unconfigured():
    response = APIClient().post(
        "/api/tax/estimate/", {"amount": 100, "state": "GA", "zip": "30301"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    # GA fallback rate is 0.04.
    assert body["tax"] == 4.0
    assert body["rate"] == 0.04
    assert body["estimated"] is True


@pytest.mark.django_db
def test_reads_state_and_zip_from_nested_address():
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
    captured = {}

    def _fake_calculate(**kwargs):
        captured.update(kwargs)
        return {"amount_to_collect": 7.35, "rate": 0.0735}

    monkeypatch.setattr("apps.integrations.tax.taxjar.calculate_tax", _fake_calculate)

    response = APIClient().post(
        "/api/tax/estimate/",
        {"subtotal": 100, "core": 20, "shipping": 5, "state": "ca", "zip": "90001"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tax"] == 7.35
    assert body["provider"] == "taxjar"
    assert body["estimated"] is False
    assert captured["amount"] == 120.0
    assert captured["shipping"] == 5.0
    assert captured["to_state"] == "CA"


@pytest.mark.django_db
def test_taxjar_failure_falls_back_to_the_state_table(settings, monkeypatch):
    settings.TAXJAR_API_KEY = "tj_test_fake"

    def _fail(**kwargs):
        raise ProviderError("TaxJar is down")

    monkeypatch.setattr("apps.integrations.tax.taxjar.calculate_tax", _fail)

    response = APIClient().post("/api/tax/estimate/", FL_REQUEST, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "fallback"
    assert body["tax"] == 6.0


@pytest.mark.django_db
def test_without_zip_taxjar_is_not_called(settings, monkeypatch):
    settings.TAXJAR_API_KEY = "tj_test_fake"

    def _boom(**kwargs):
        raise AssertionError("TaxJar needs a destination zip")

    monkeypatch.setattr("apps.integrations.tax.taxjar.calculate_tax", _boom)

    response = APIClient().post(
        "/api/tax/estimate/", {"subtotal": 100, "state": "FL"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "fallback"


@pytest.mark.django_db
def test_unknown_state_falls_back_to_zero_rate():
    response = APIClient().post(
        "/api/tax/estimate/", {"subtotal": 100, "state": "ZZ", "zip": "00000"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["rate"] == 0
