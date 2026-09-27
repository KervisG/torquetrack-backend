"""Impuesto que guarda `POST /api/admin/quotes/`: lo calcula el servidor.

Al guardar, el backend recalcula el impuesto con `estimate_tax_for_customer`
sobre las líneas repreciadas y la dirección de envío guardada en la
cotización (`shippingAddress`). El `tax` del body se ignora; solo quien tiene
`tax_exemptions.review` puede mandar `taxOverride: {amount, reason}`, que se
guarda como `taxSource: "manual"` y deja `QUOTE_TAX_OVERRIDDEN` en la
bitácora. Convertir y cobrar la cotización copian ese total guardado.

Mocking: TaxJar en el adaptador (`apps.integrations.tax.taxjar.calculate_tax`)
y Stripe en `apps.integrations.payments.stripe.create_checkout_session`. Los
caminos que no deben llamar a TaxJar lo parchean para que lance excepción.
"""
import pytest

from apps.checkout.models import Order
from apps.integrations.exceptions import ProviderError
from apps.quotes.models import Quote
from tests.factories import (
    activity_count,
    create_customer,
    create_staff_user,
    create_user,
    session_client,
)

TAXJAR = "apps.integrations.tax.taxjar.calculate_tax"
CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"
FL_ADDRESS = {"address1": "100 Main St", "city": "Tampa", "state": "FL", "zip": "33701"}
OVERRIDE_FORBIDDEN = {"error": "Overriding tax requires tax_exemptions.review"}
ADDRESS_REQUIRED = {"error": "Shipping state and ZIP are required to calculate tax"}


@pytest.fixture
def taxjar_seven(monkeypatch, settings):
    """TaxJar responde 7 % sobre 100 (el monto gravable de `_body`)."""
    settings.TAXJAR_API_KEY = "tj_test_fake"
    calls = []

    def _fake(**kwargs):
        calls.append(kwargs)
        return {"amount_to_collect": 7.0, "rate": 0.07}

    monkeypatch.setattr(TAXJAR, _fake)
    return calls


@pytest.fixture
def forbid_taxjar(monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("TaxJar must not be called")

    monkeypatch.setattr(TAXJAR, _boom)


def _staff(user_id, *extra_permissions):
    create_staff_user(
        user_id, permissions=["quotes.create", "quotes.edit", "quotes.view", *extra_permissions]
    )
    client, _ = session_client(user_id)
    return client


def _customer(customer_id, tax_status="NOT SUBMITTED"):
    email = f"{customer_id.lower()}@example.com"
    user = create_user(f"usr_{customer_id}", email=email)
    return create_customer(customer_id, email=email, user=user, tax_status=tax_status)


def _body(**extra):
    return {
        "customer": {"name": "Fleet Co", "email": ""},
        "items": [{"title": "Injector", "unitPrice": 100.0, "quantity": 1, "coreCharge": 0}],
        "shipping": 0,
        "shippingAddress": FL_ADDRESS,
        **extra,
    }


def _saved(response):
    return Quote.objects.get(pk=response.json()["quote"]["id"])


# --- el servidor calcula -----------------------------------------------------


@pytest.mark.django_db
def test_staff_without_review_cannot_lower_the_tax(taxjar_seven):
    customer = _customer("C_tax_plain")
    client = _staff("usr_tax_plain")

    response = client.post(
        "/api/admin/quotes/",
        _body(customerId=customer.pk, tax=0, taxSource="manual", taxRate=0),
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["quote"]["totals"]["tax"] == 7
    assert response.json()["quote"]["taxSource"] == "calculated"
    quote = _saved(response)
    assert quote.data["totals"]["tax"] == 7
    assert quote.data["totals"]["total"] == 107
    assert quote.data["tax"] == 7
    assert quote.data["taxSource"] == "calculated"
    assert quote.data["taxRate"] == 0.07
    assert quote.data["taxProvider"] == "taxjar"
    assert "taxOverride" not in quote.data
    # El cálculo usó la dirección guardada y el monto repreciado.
    assert taxjar_seven[0]["to_state"] == "FL"
    assert taxjar_seven[0]["to_zip"] == "33701"
    assert taxjar_seven[0]["to_city"] == "Tampa"
    assert taxjar_seven[0]["to_street"] == "100 Main St"
    assert taxjar_seven[0]["amount"] == 100


@pytest.mark.django_db
def test_the_shipping_address_is_normalized_and_saved(taxjar_seven):
    client = _staff("usr_tax_address")

    response = client.post(
        "/api/admin/quotes/",
        _body(
            shippingAddress={
                "address1": " 100 Main St ",
                "city": "Tampa",
                "state": " fl",
                "zip": "33701-1234",
            }
        ),
        format="json",
    )

    assert response.status_code == 200
    assert _saved(response).data["shippingAddress"] == {
        "address1": "100 Main St",
        "city": "Tampa",
        "state": "FL",
        "zip": "33701-1234",
    }


@pytest.mark.django_db
def test_saving_without_review_replaces_a_previous_manual_override(taxjar_seven):
    reviewer = _staff("usr_tax_reviewer", "tax_exemptions.review")
    saved = reviewer.post(
        "/api/admin/quotes/",
        _body(taxOverride={"amount": 1, "reason": "Out-of-state delivery"}),
        format="json",
    ).json()["quote"]
    plain = _staff("usr_tax_plain_edit")

    response = plain.post("/api/admin/quotes/", _body(id=saved["id"], tax=1), format="json")

    assert response.status_code == 200
    quote = _saved(response)
    assert quote.data["totals"]["tax"] == 7
    assert quote.data["taxSource"] == "calculated"
    assert "taxOverride" not in quote.data


@pytest.mark.django_db
def test_a_quote_with_nothing_to_tax_needs_no_address(forbid_taxjar):
    client = _staff("usr_tax_empty")

    response = client.post(
        "/api/admin/quotes/", {"customer": {"name": "Draft"}, "items": []}, format="json"
    )

    assert response.status_code == 200
    quote = _saved(response)
    assert quote.data["totals"]["tax"] == 0
    assert quote.data["taxSource"] == "calculated"


# --- override ----------------------------------------------------------------


@pytest.mark.django_db
def test_tax_override_without_review_is_forbidden(forbid_taxjar):
    client = _staff("usr_tax_no_review")

    response = client.post(
        "/api/admin/quotes/",
        _body(taxOverride={"amount": 0, "reason": "Customer asked"}),
        format="json",
    )

    assert response.status_code == 403
    assert response.json() == OVERRIDE_FORBIDDEN
    assert not Quote.objects.exists()
    assert activity_count(action="QUOTE_TAX_OVERRIDDEN") == 0


@pytest.mark.django_db
def test_tax_override_with_review_is_saved_as_manual_and_logged(forbid_taxjar):
    customer = _customer("C_tax_override")
    client = _staff("usr_tax_review", "tax_exemptions.review")

    response = client.post(
        "/api/admin/quotes/",
        _body(customerId=customer.pk, taxOverride={"amount": 2.5, "reason": " Resale in GA "}),
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["quote"]["totals"]["tax"] == 2.5
    quote = _saved(response)
    assert quote.data["totals"]["tax"] == 2.5
    assert quote.data["totals"]["total"] == 102.5
    assert quote.data["taxSource"] == "manual"
    override = quote.data["taxOverride"]
    assert override["amount"] == 2.5
    assert override["reason"] == "Resale in GA"
    assert override["by"] == "usr_tax_review@example.com"
    assert override["at"]
    assert activity_count(
        action="QUOTE_TAX_OVERRIDDEN",
        entity_id=quote.pk,
        actor_id="usr_tax_review@example.com",
    ) == 1


@pytest.mark.django_db
def test_resaving_the_same_override_is_not_logged_twice(forbid_taxjar):
    client = _staff("usr_tax_review_twice", "tax_exemptions.review")
    override = {"amount": 0, "reason": "Delivered out of state"}
    saved = client.post("/api/admin/quotes/", _body(taxOverride=override), format="json").json()

    response = client.post(
        "/api/admin/quotes/",
        _body(id=saved["quote"]["id"], taxOverride=override, memo="edited"),
        format="json",
    )

    assert response.status_code == 200
    assert activity_count(action="QUOTE_TAX_OVERRIDDEN", entity_id=saved["quote"]["id"]) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"amount": -1, "reason": "x"}, "Tax override amount must be 0 or more"),
        ({"amount": "abc", "reason": "x"}, "Tax override amount must be 0 or more"),
        ({"amount": True, "reason": "x"}, "Tax override amount must be 0 or more"),
        ({"amount": 1, "reason": "  "}, "Tax override reason is required"),
        ({"amount": 1}, "Tax override reason is required"),
        ({"amount": 1, "reason": "x" * 501}, "Tax override reason must be 500 characters or fewer"),
        ("zero", "Tax override must be an object with amount and reason"),
    ],
)
def test_tax_override_is_validated(forbid_taxjar, override, message):
    client = _staff("usr_tax_review_bad", "tax_exemptions.review")

    response = client.post("/api/admin/quotes/", _body(taxOverride=override), format="json")

    assert response.status_code == 400
    assert response.json() == {"error": message}
    assert not Quote.objects.exists()


@pytest.mark.django_db
def test_an_exempt_customer_cannot_get_a_tax_override(forbid_taxjar):
    customer = _customer("C_tax_exempt_override", "VERIFIED")
    client = _staff("usr_tax_review_exempt", "tax_exemptions.review")

    response = client.post(
        "/api/admin/quotes/",
        _body(customerId=customer.pk, taxOverride={"amount": 5, "reason": "x"}),
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Tax-exempt customers cannot have a tax override"}


# --- exención y dirección ----------------------------------------------------


@pytest.mark.django_db
def test_exempt_customer_gets_zero_tax_without_an_address(forbid_taxjar):
    customer = _customer("C_tax_exempt", "VERIFIED")
    client = _staff("usr_tax_exempt")

    body = _body(customerId=customer.pk, tax=9)
    del body["shippingAddress"]
    response = client.post("/api/admin/quotes/", body, format="json")

    assert response.status_code == 200
    quote = _saved(response)
    assert quote.data["totals"]["tax"] == 0
    assert quote.data["taxSource"] == "exempt"
    assert quote.data["taxExempt"] is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    "address",
    [None, {}, {"state": "FL", "zip": ""}, {"state": "", "zip": "33701"}],
)
def test_a_non_exempt_quote_without_state_and_zip_is_rejected(forbid_taxjar, address):
    client = _staff("usr_tax_no_address")

    response = client.post("/api/admin/quotes/", _body(shippingAddress=address), format="json")

    assert response.status_code == 400
    assert response.json() == ADDRESS_REQUIRED
    assert not Quote.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("address", "message"),
    [
        ("FL 33701", "Shipping address must be an object with text fields"),
        ({**FL_ADDRESS, "zip": 33701}, "Shipping address must be an object with text fields"),
        ({**FL_ADDRESS, "state": "Florida"}, "Shipping state must be a 2-letter code"),
        ({**FL_ADDRESS, "zip": "3370"}, "Shipping ZIP must be 5 digits or ZIP+4"),
        (
            {**FL_ADDRESS, "city": "x" * 201},
            "Shipping address fields must be 200 characters or fewer",
        ),
    ],
)
def test_the_shipping_address_is_validated(forbid_taxjar, address, message):
    client = _staff("usr_tax_bad_address")

    response = client.post("/api/admin/quotes/", _body(shippingAddress=address), format="json")

    assert response.status_code == 400
    assert response.json() == {"error": message}


@pytest.mark.django_db
def test_a_taxjar_failure_falls_back_to_the_state_table(monkeypatch, settings):
    settings.TAXJAR_API_KEY = "tj_test_fake"

    def _down(**kwargs):
        raise ProviderError("TaxJar is down")

    monkeypatch.setattr(TAXJAR, _down)
    client = _staff("usr_tax_fallback")

    response = client.post("/api/admin/quotes/", _body(tax=0), format="json")

    assert response.status_code == 200
    quote = _saved(response)
    assert quote.data["totals"]["tax"] == 6
    assert quote.data["taxSource"] == "calculated"
    assert quote.data["taxProvider"] == "fallback"
    assert quote.data["taxRate"] == 0.06


# --- conversión y cobro heredan el impuesto guardado -------------------------


@pytest.mark.django_db
def test_converting_inherits_the_recalculated_tax(taxjar_seven):
    customer = _customer("C_tax_convert")
    client = _staff("usr_tax_convert", "quotes.convert")
    saved = client.post(
        "/api/admin/quotes/", _body(customerId=customer.pk, tax=0), format="json"
    ).json()["quote"]

    response = client.post(f"/api/admin/quotes/{saved['id']}/convert/")

    assert response.status_code == 200
    order = Order.objects.get(number=response.json()["order"]["number"])
    assert order.data["totals"]["tax"] == 7
    assert order.data["totals"]["total"] == 107


@pytest.mark.django_db
def test_the_public_checkout_inherits_the_recalculated_tax(taxjar_seven, monkeypatch, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    sessions = []

    def _fake_session(**kwargs):
        sessions.append(kwargs)
        return {"id": "cs_test_tax", "url": "https://checkout.stripe.com/pay/cs_test_tax"}

    monkeypatch.setattr(CREATE_SESSION, _fake_session)
    client = _staff("usr_tax_public")
    saved = client.post("/api/admin/quotes/", _body(tax=0), format="json").json()["quote"]
    link = client.post(f"/api/admin/quotes/{saved['id']}/preview/").json()["url"]
    token = link.rstrip("/").rsplit("/", 1)[-1]

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 200
    order = Order.objects.get(number=response.json()["orderNumber"])
    assert order.data["totals"]["tax"] == 7
    assert order.data["totals"]["total"] == 107
    assert len(sessions) == 1
