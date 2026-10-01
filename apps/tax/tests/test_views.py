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
        "/api/tax/estimate/", {"amount": 100, "state": "FL", "zip": "33701"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    # Tasa estatal de respaldo de FL: 0.06.
    assert body["tax"] == 6.0
    assert body["rate"] == 0.06
    assert body["estimated"] is True


@pytest.mark.django_db
def test_reads_state_and_zip_from_nested_address():
    response = APIClient().post(
        "/api/tax/estimate/",
        {"subtotal": 100, "address": {"state": "fl", "zip": "33701"}},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tax"] == 6.0
    assert body["rate"] == 0.06


# --- nexo -------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"subtotal": 100, "core": 20, "shipping": 5, "state": "GA", "zip": "30301"},
        {"subtotal": 100, "address": {"state": "ca", "zip": "90001"}},
        {"subtotal": 100, "state": "TX"},
    ],
)
def test_state_without_nexus_pays_zero_without_calling_taxjar(settings, monkeypatch, payload):
    settings.TAXJAR_API_KEY = "tj_test_fake"

    def _boom(**kwargs):
        raise AssertionError("TaxJar must not be called outside the nexus states")

    monkeypatch.setattr("apps.integrations.tax.taxjar.calculate_tax", _boom)

    response = APIClient().post("/api/tax/estimate/", payload, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["tax"] == 0
    assert body["rate"] == 0
    assert body["provider"] == "none"
    assert body["estimated"] is False


@pytest.mark.django_db
def test_nexus_states_come_from_settings(settings):
    settings.SALES_TAX_NEXUS_STATES = ("GA",)

    florida = APIClient().post("/api/tax/estimate/", FL_REQUEST, format="json")

    assert florida.json()["tax"] == 0
    assert florida.json()["provider"] == "none"


def test_the_nexus_is_florida_only(settings):
    assert tuple(settings.SALES_TAX_NEXUS_STATES) == ("FL",)


def test_fallback_table_only_has_the_florida_state_rate():
    from decimal import Decimal

    from apps.tax.services import FALLBACK_TAX_RATES

    assert FALLBACK_TAX_RATES == {"FL": Decimal("0.06")}


@pytest.mark.django_db
def test_florida_fallback_taxes_parts_core_and_shipping():
    response = APIClient().post(
        "/api/tax/estimate/",
        {"subtotal": 100, "core": 20, "shipping": 5, "state": "FL", "zip": "33701"},
        format="json",
    )

    assert response.status_code == 200
    # 0.06 × (100 + 20 + 5): Florida grava el envío que el comprador no puede evitar.
    assert response.json()["tax"] == 7.5


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
        {"subtotal": 100, "core": 20, "shipping": 5, "state": "fl", "zip": "33701"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tax"] == 7.35
    assert body["provider"] == "taxjar"
    assert body["estimated"] is False
    assert captured["amount"] == 120.0
    assert captured["shipping"] == 5.0
    assert captured["to_state"] == "FL"
    assert captured["to_zip"] == "33701"


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


# --- estado de destino -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"subtotal": 100, "zip": "33701"},
        {"subtotal": 100, "state": "  ", "zip": "33701"},
        {"subtotal": 100, "address": {"zip": "33701"}},
    ],
)
def test_estimate_without_a_state_is_rejected(payload):
    # Un 0 sin estado se leería como "sin impuesto" aunque el envío vaya a FL.
    response = APIClient().post("/api/tax/estimate/", payload, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "Shipping state is required"}


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["ZZ", "Florida", "AP", 12])
def test_estimate_with_an_unknown_state_is_rejected(state):
    response = APIClient().post(
        "/api/tax/estimate/", {"subtotal": 100, "state": state, "zip": "33701"}, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "Shipping state must be a valid 2-letter US state code"
    }


@pytest.mark.django_db
def test_verified_customer_gets_the_exempt_estimate_without_a_state(monkeypatch):
    # La exención no depende del destino: no se le pide dirección.
    _no_taxjar(monkeypatch)
    client = _account("U_EXEMPT_NO_STATE", tax_status="VERIFIED")

    response = client.post("/api/tax/estimate/", {"subtotal": 100}, format="json")

    assert response.status_code == 200
    assert response.json() == EXEMPT


@pytest.mark.django_db
def test_fallback_tax_rounds_half_up_in_decimal():
    # 9.25 × 0.06 = 0.555 → 0.56; en `float` da 0.55499... y se cobraba 0.55.
    response = APIClient().post(
        "/api/tax/estimate/", {"subtotal": 9.25, "state": "FL", "zip": "33701"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["tax"] == 0.56
    assert response.json()["rate"] == 0.06


@pytest.mark.django_db
def test_calculate_sales_tax_returns_decimal_amounts():
    from decimal import Decimal

    from apps.tax.services import calculate_sales_tax

    result = calculate_sales_tax(
        subtotal=Decimal("47.75"), core_charge=0, shipping=0, state="FL", zip_code=""
    )

    assert result["tax"] == Decimal("2.87")
    assert result["rate"] == Decimal("0.06")


# --- ZIP contra estado --------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"subtotal": 100, "state": "GA", "zip": "33701"},
        {"subtotal": 100, "state": "FL", "zip": "30301"},
        {"subtotal": 100, "address": {"state": "ga", "zip": "33701-1234"}},
    ],
)
def test_estimate_with_a_zip_from_another_state_is_rejected(monkeypatch, payload):
    # Un ZIP de FL con estado "GA" daría 0 de impuesto a un envío a Florida.
    _no_taxjar(monkeypatch)

    response = APIClient().post("/api/tax/estimate/", payload, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "ZIP code does not match the selected state."}


@pytest.mark.django_db
def test_estimate_with_an_unassigned_zip_prefix_is_rejected():
    response = APIClient().post(
        "/api/tax/estimate/", {"subtotal": 100, "state": "FL", "zip": "00001"}, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {"error": "ZIP code is not a valid US ZIP code."}


@pytest.mark.django_db
def test_exempt_customer_skips_the_address_checks(monkeypatch):
    _no_taxjar(monkeypatch)
    client = _account("U_ZIP_EXEMPT", "VERIFIED")

    response = client.post(
        "/api/tax/estimate/", {"subtotal": 100, "state": "GA", "zip": "33701"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["tax"] == 0
