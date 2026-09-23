"""Tests de `POST /api/checkout`.

La API real de Stripe nunca se llama: se parchea su adaptador,
`apps.integrations.payments.stripe.create_checkout_session`, y nunca se usa
un `STRIPE_SECRET_KEY` real.
"""

import pytest
from rest_framework.test import APIClient

from apps.cart.models import Cart
from apps.catalog.models import Product
from apps.checkout.models import Order, Payment
from apps.integrations.exceptions import ProviderError
from tests.factories import create_customer

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


def _insert_product(product_id=PRODUCT_ID, data=None, active=True):
    Product.objects.create(id=product_id, data=data or PRODUCT_DATA, active=active)


def _insert_customer(customer_id, email, tax_status="NOT SUBMITTED"):
    create_customer(customer_id, email=email, tax_status=tax_status)


def _insert_cart(cart_id, data):
    Cart.objects.create(id=cart_id, data=data)


def _fake_session(session_id="cs_test_123", url="https://checkout.stripe.com/pay/cs_test_123"):
    return {"id": session_id, "url": url}


@pytest.fixture(autouse=True)
def _stripe_secret_key(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    return settings


@pytest.mark.django_db
def test_returns_503_when_stripe_not_configured(settings):
    settings.STRIPE_SECRET_KEY = ""

    response = APIClient().post("/api/checkout/", {"items": []}, format="json")

    assert response.status_code == 503
    assert "STRIPE_SECRET_KEY" in response.json()["error"]


@pytest.mark.django_db
def test_returns_400_when_cart_is_empty():
    response = APIClient().post("/api/checkout/", {"items": []}, format="json")

    assert response.status_code == 400
    assert response.json()["error"] == "Cart is empty"


@pytest.mark.django_db
def test_returns_400_when_no_valid_products_in_cart():
    response = APIClient().post(
        "/api/checkout/", {"items": [{"id": "does-not-exist", "qty": 1}]}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"] == "No valid products in cart"


@pytest.mark.django_db
def test_reprices_from_db_ignoring_client_submitted_price(monkeypatch):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 2, "price": 0.01}],
            "vehicle": {"make": "Chevrolet", "year": 1996, "engine": "6.5"},
        },
        format="json",
    )

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    # 189.99 * 2 = 379.98, never the client-submitted 0.01 * 2.
    assert order.data["totals"]["subtotal"] == 379.98


@pytest.mark.django_db
def test_returns_409_when_fitment_check_fails(monkeypatch):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": {"make": "Ford", "year": 1996, "engine": "6.5"},
        },
        format="json",
    )

    assert response.status_code == 409
    assert "VIN fitment check failed" in response.json()["error"]
    assert not Order.objects.filter(data__vehicle__make="Ford").exists()


@pytest.mark.django_db
def test_verified_customer_pays_zero_tax(monkeypatch):
    _insert_product()
    _insert_customer("cus_verified_1", "verified@example.com", tax_status="VERIFIED")
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": {"make": "Chevrolet", "year": 1996, "engine": "6.5"},
            "customer": {"email": "verified@example.com", "state": "FL", "zip": "33701"},
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tax"] == 0
    order = Order.objects.get(pk=body["orderId"])
    assert order.data["taxSource"] == "Tax exempt"


@pytest.mark.django_db
def test_non_verified_customer_gets_fallback_table_tax(monkeypatch, settings):
    settings.TAXJAR_API_KEY = ""
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": {"make": "Chevrolet", "year": 1996, "engine": "6.5"},
            "customer": {"email": "anon@example.com", "state": "FL", "zip": "33701"},
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    # FL fallback rate is 0.06; subtotal+core = 189.99+50.0 = 239.99, no shipping.
    assert body["tax"] == round(239.99 * 0.06, 2)


@pytest.mark.django_db
def test_creates_order_and_pending_payment_via_stripe_sdk(monkeypatch):
    _insert_product()
    monkeypatch.setattr(
        CREATE_SESSION,
        lambda **kwargs: _fake_session("cs_test_created", "https://checkout.stripe.com/pay/cs_test_created"),
    )

    response = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": {"make": "Chevrolet", "year": 1996, "engine": "6.5"},
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://checkout.stripe.com/pay/cs_test_created"

    order = Order.objects.get(pk=body["orderId"])
    assert order.status == "PENDING_PAYMENT"
    assert order.payment_status == "UNPAID"

    payment = Payment.objects.get(order=order)
    assert payment.provider == "stripe"
    assert payment.provider_id == "cs_test_created"
    assert payment.status == "PENDING"


@pytest.mark.django_db
def test_stripe_session_failure_marks_order_payment_setup_failed(monkeypatch):
    _insert_product()

    def _boom(**kwargs):
        raise ProviderError("Could not create secure checkout")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    response = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": {"make": "Chevrolet", "year": 1996, "engine": "6.5"},
        },
        format="json",
    )

    assert response.status_code == 502
    order = Order.objects.get()
    assert order.status == "PAYMENT_SETUP_FAILED"
    assert not Payment.objects.filter(order=order).exists()


@pytest.mark.django_db
def test_resolves_existing_customer_by_email_and_merges_submitted_fields(monkeypatch):
    _insert_product()
    _insert_customer("cus_existing_1", "repeat@example.com")
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": {"make": "Chevrolet", "year": 1996, "engine": "6.5"},
            "customer": {"email": "repeat@example.com", "name": "Repeat Customer"},
        },
        format="json",
    )

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer_id == "cus_existing_1"


@pytest.mark.django_db
def test_guest_checkout_never_merges_into_a_registered_customer_profile(monkeypatch):
    # Un invitado solo escribe un email: si se mezclara con el perfil de una
    # cuenta registrada, cualquiera podría pisar su dirección o sumarle pedidos.
    from tests.factories import create_user

    _insert_product()
    owner = create_user("U_REGISTERED", email="owner@example.com")
    create_customer(
        "cus_registered", email="owner@example.com", user=owner, data={"city": "Tampa"}
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": {"make": "Chevrolet", "year": 1996, "engine": "6.5"},
            "customer": {"email": "owner@example.com", "city": "Elsewhere"},
        },
        format="json",
    )

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer_id != "cus_registered"
    from apps.customers.models import Customer

    assert Customer.objects.get(pk="cus_registered").data == {"city": "Tampa"}


@pytest.mark.django_db
def test_cart_transitions_to_checkout_stage_when_cart_id_present(monkeypatch):
    _insert_product()
    _insert_cart("cart_uuid_checkout_1", {"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"})
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = APIClient().post(
        "/api/checkout/",
        {
            "cartId": "cart_uuid_checkout_1",
            "items": [{"id": PRODUCT_ID, "qty": 1}],
            "vehicle": {"make": "Chevrolet", "year": 1996, "engine": "6.5"},
        },
        format="json",
    )

    assert response.status_code == 200
    data = Cart.objects.get(pk="cart_uuid_checkout_1").data
    assert data["stage"] == "CHECKOUT"
    assert data["orderId"] == response.json()["orderId"]
