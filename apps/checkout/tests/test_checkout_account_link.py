"""Una cuenta con `Customer` vinculado compra como ese perfil: el email del
body no puede cambiar el cliente ni el perfil."""

import pytest

from apps.catalog.models import Product
from apps.checkout.models import Order
from apps.customers.models import Customer
from tests.factories import (
    create_customer,
    create_staff_user,
    create_user,
    session_client,
)
from tests.fakes import quote_shipping

CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"

PRODUCT_ID = "gm-65-injection-pump-dorman-502550"
PRODUCT_DATA = {
    "id": PRODUCT_ID,
    "title": "6.5L Turbo Diesel Fuel Injection Pump",
    "partNumber": "502-550",
    "price": 189.99,
    "coreCharge": 50.0,
    "make": "Chevrolet / GMC",
    "yearFrom": 1994,
    "yearTo": 2000,
    "engineFamily": "6.5",
}
VEHICLE = {"make": "Chevrolet", "year": 1996, "engine": "6.5"}
PROFILE = {"name": "Pat Fleet", "company": "Fleet LLC", "city": "Tampa"}


@pytest.fixture(autouse=True)
def _stripe(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    settings.TAXJAR_API_KEY = ""
    Product.objects.create(id=PRODUCT_ID, data=PRODUCT_DATA, active=True)
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return {"id": "cs_test_acct", "url": "https://checkout.stripe.com/pay/cs_test_acct"}

    monkeypatch.setattr(CREATE_SESSION, _create)
    captured["_selection"] = quote_shipping(
        monkeypatch, settings, zip_code="33701", items=[{"id": PRODUCT_ID, "qty": 1}]
    )
    return captured


def _account(tax_status="NOT SUBMITTED"):
    user = create_user("U_PAT", email="pat@example.com")
    create_customer(
        "C_PAT",
        email="pat@example.com",
        user=user,
        data=dict(PROFILE),
        tax_status=tax_status,
    )
    client, _ = session_client("U_PAT")
    return client


def _checkout(client, customer):
    return client.post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": VEHICLE,
            "customer": {"state": "FL", "zip": "33701", **customer},
            "shipping": {"shipmentId": "shp_checkout", "rateId": "rate_ground"},
        },
        format="json",
    )


@pytest.mark.django_db
def test_signed_in_customer_order_attaches_to_linked_profile():
    client = _account()

    response = _checkout(
        client,
        {"email": "pat@example.com", "name": "Pat Fleet", "state": "FL", "zip": "33701"},
    )

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer_id == "C_PAT"
    # No se crea un perfil invitado paralelo.
    assert Customer.objects.count() == 1


@pytest.mark.django_db
def test_signed_in_customer_body_email_cannot_redirect_the_order(_stripe):
    # Aunque ya exista un invitado con ese email, el pedido es de la cuenta.
    create_customer("C_GUEST", email="someone-else@example.com")
    client = _account()

    response = _checkout(client, {"email": "someone-else@example.com", "state": "FL"})

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer_id == "C_PAT"
    assert order.data["customer"]["email"] == "pat@example.com"
    assert _stripe["customer_email"] == "pat@example.com"
    assert Customer.objects.get(pk="C_GUEST").data == {}


@pytest.mark.django_db
def test_signed_in_checkout_still_requires_the_shipping_state():
    # El perfil no completa el estado de envío: la dirección del pedido es la
    # del body, y sin estado el impuesto daría 0.
    client = _account()

    response = _checkout(client, {"email": "pat@example.com", "state": ""})

    assert response.status_code == 400
    assert response.json() == {"error": "Shipping state is required"}
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_signed_in_checkout_never_overwrites_the_profile():
    client = _account()

    response = _checkout(
        client,
        {
            "email": "pat@example.com",
            "name": "Mallory",
            "company": "Other Co",
            "city": "Elsewhere",
            "taxStatus": "VERIFIED",
        },
    )

    assert response.status_code == 200
    customer = Customer.objects.get(pk="C_PAT")
    assert customer.data == PROFILE
    assert customer.tax_status == "NOT SUBMITTED"
    # La dirección de envío del pedido sí es la del body.
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.data["customer"]["city"] == "Elsewhere"


@pytest.mark.django_db
def test_signed_in_checkout_works_without_body_email():
    client = _account()

    response = _checkout(client, {"state": "FL", "zip": "33701"})

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer_id == "C_PAT"
    assert order.data["customer"]["email"] == "pat@example.com"


@pytest.mark.django_db
def test_verified_linked_profile_pays_zero_tax(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("TaxJar must not be called for an exempt customer")

    monkeypatch.setattr("apps.integrations.tax.taxjar.calculate_tax", _boom)
    client = _account(tax_status="VERIFIED")

    response = _checkout(client, {"state": "FL", "zip": "33701"})

    assert response.status_code == 200
    assert response.json()["tax"] == 0


@pytest.mark.django_db
def test_staff_without_profile_checks_out_as_guest():
    create_staff_user("U_STAFF", permissions=["orders.view"])
    client, _ = session_client("U_STAFF")

    response = _checkout(client, {"email": "walkin@example.com", "state": "FL"})

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer.email == "walkin@example.com"
    assert order.customer.user_id is None


@pytest.mark.django_db
def test_signed_in_checkout_requires_csrf():
    user = create_user("U_PAT", email="pat@example.com")
    create_customer("C_PAT", email="pat@example.com", user=user)
    client, _ = session_client("U_PAT", enforce_csrf=True)

    response = _checkout(client, {"state": "FL"})

    assert response.status_code == 403
    assert not Order.objects.exists()
