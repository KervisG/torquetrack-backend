"""Mismas líneas, mismo dinero en `POST /api/checkout/`, `POST /api/quote/request/`
y `POST /api/admin/quotes/` (más su convert y el link de pago de
`/api/admin/orders/<id>/payment-link/`).

Los tres repreciaban con copias propias: el panel multiplicaba el precio sin
redondear (3 × 19.995 = 59.99) mientras el storefront y Stripe cobraban
3 × 20.00, y el webhook marcaba el pago como `PAYMENT_AMOUNT_MISMATCH`. Ahora
todos pasan por `price_lines`/`build_totals` de `apps.catalog.services`.

Mocking: Stripe en el adaptador (`create_checkout_session`), EasyPost con
`quote_shipping` de `tests/fakes.py`; TaxJar sin key (tabla de respaldo).
"""

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.checkout.models import Order, Payment
from apps.common.numbers import to_cents
from apps.quotes.models import Quote
from tests.factories import CHECKOUT_CONTACT, create_staff_user, session_client
from tests.fakes import quote_shipping

CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"
PRODUCT_ID = "gm-65-glow-plug"
PRODUCT_DATA = {
    "id": PRODUCT_ID,
    "title": "Glow Plug",
    "partNumber": "GP-65",
    "price": 19.995,
    "coreCharge": 1.005,
    "make": "Chevrolet / GMC",
    "yearFrom": 1994,
    "yearTo": 2000,
    "engineFamily": "6.5",
    "shippingWeight": 1,
}
VEHICLE = {"make": "Chevrolet", "year": 1996, "engine": "6.5"}
STOREFRONT_QUANTITY_ERROR = "Item quantity must be a whole number from 1 to 99"


@pytest.fixture(autouse=True)
def _providers(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    settings.TAXJAR_API_KEY = ""
    settings.SALES_EMAIL = ""
    sessions = []

    def _create(**kwargs):
        sessions.append(kwargs)
        number = len(sessions)
        return {"id": f"cs_test_{number}", "url": f"https://checkout.stripe.com/{number}"}

    monkeypatch.setattr(CREATE_SESSION, _create)
    return sessions


def _insert_product():
    Product.objects.create(id=PRODUCT_ID, data=PRODUCT_DATA, active=True)


def _stripe_cents(session: dict) -> int:
    return sum(line["unit_amount"] * line["quantity"] for line in session["line_items"])


def _checkout(monkeypatch, settings, qty):
    selection = quote_shipping(
        monkeypatch, settings, zip_code="33701", items=[{"id": PRODUCT_ID, "qty": qty}]
    )
    return APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": PRODUCT_ID, "qty": qty}],
            "vehicle": VEHICLE,
            "customer": {**CHECKOUT_CONTACT, "state": "FL", "zip": "33701"},
            "shipping": selection,
        },
        format="json",
    )


def _request_quote(items):
    return APIClient().post(
        "/api/quote/request/",
        {"customer": {"name": "Jane Diesel"}, "items": items},
        format="json",
    )


def _staff_client():
    create_staff_user(
        "usr_pricing", permissions=["quotes.create", "quotes.convert", "payments.take"]
    )
    client, _ = session_client("usr_pricing")
    return client


def _panel_quote(client, items):
    return client.post(
        "/api/admin/quotes/",
        {
            "customer": {"name": "Fleet Co"},
            "items": items,
            "shipping": 0,
            # Fuera de Florida no hay nexo: el total de la cotización queda
            # sin impuesto.
            "shippingAddress": {"state": "OR", "zip": "97201"},
        },
        format="json",
    )


# --- mismo total -------------------------------------------------------------


@pytest.mark.django_db
def test_checkout_quote_request_and_panel_price_the_same_lines_alike(
    monkeypatch, settings, _providers
):
    _insert_product()

    checkout = _checkout(monkeypatch, settings, qty=3)
    assert checkout.status_code == 200
    order_totals = Order.objects.get(pk=checkout.json()["orderId"]).data["totals"]

    request = _request_quote([{"productId": PRODUCT_ID, "quantity": 3}])
    assert request.status_code == 200
    request_totals = Quote.objects.get(pk=request.json()["quoteId"]).data["totals"]

    # El panel copia el precio del catálogo en la línea (quote-catalog-picker).
    panel = _panel_quote(
        _staff_client(),
        [{"productId": PRODUCT_ID, "quantity": 3, "unitPrice": 19.995, "coreCharge": 1.005}],
    )
    assert panel.status_code == 200
    panel_totals = panel.json()["quote"]["totals"]

    for totals in (order_totals, request_totals, panel_totals):
        assert (totals["subtotal"], totals["core"]) == (60.0, 3.03)
    assert request_totals["total"] == panel_totals["total"] == 63.03


@pytest.mark.django_db
def test_stripe_charges_exactly_the_payment_amount_of_a_checkout(monkeypatch, settings, _providers):
    _insert_product()

    response = _checkout(monkeypatch, settings, qty=3)

    assert response.status_code == 200
    payment = Payment.objects.get(order_id=response.json()["orderId"])
    assert _stripe_cents(_providers[-1]) == to_cents(payment.amount)


@pytest.mark.django_db
def test_stripe_charges_exactly_the_payment_amount_of_a_panel_quote(_providers):
    client = _staff_client()
    created = _panel_quote(
        client, [{"title": "Glow Plug", "quantity": 3, "unitPrice": 19.995, "coreCharge": 1.005}]
    )
    quote_id = created.json()["quote"]["id"]
    order_id = client.post(f"/api/admin/quotes/{quote_id}/convert/").json()["order"]["id"]

    response = client.post(f"/api/admin/orders/{order_id}/payment-link/")

    assert response.status_code == 200
    payment = Payment.objects.get(order_id=order_id)
    assert float(payment.amount) == created.json()["quote"]["totals"]["total"] == 63.03
    assert _stripe_cents(_providers[-1]) == to_cents(payment.amount) == 6303


# --- cantidad ----------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("qty", [0, 100, 2.5, "abc"])
def test_checkout_rejects_a_quantity_outside_one_to_ninety_nine(qty, _providers):
    _insert_product()

    response = APIClient().post(
        "/api/checkout/",
        {"items": [{"id": PRODUCT_ID, "qty": qty}], "vehicle": VEHICLE},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": STOREFRONT_QUANTITY_ERROR}
    assert not Order.objects.exists()
    assert _providers == []


@pytest.mark.django_db
@pytest.mark.parametrize("quantity", [0, 100, 2.5, "abc"])
def test_quote_request_rejects_a_quantity_outside_one_to_ninety_nine(quantity):
    _insert_product()

    response = _request_quote([{"productId": PRODUCT_ID, "quantity": quantity}])

    assert response.status_code == 400
    assert response.json() == {"error": STOREFRONT_QUANTITY_ERROR}
    assert not Quote.objects.exists()


@pytest.mark.django_db
def test_panel_keeps_its_whole_number_rule_without_the_storefront_cap():
    client = _staff_client()

    rejected = _panel_quote(client, [{"title": "Plug", "quantity": 0, "unitPrice": 5}])
    accepted = _panel_quote(client, [{"title": "Plug", "quantity": 250, "unitPrice": 5}])

    assert rejected.status_code == 400
    assert rejected.json() == {
        "error": "Item quantity must be a whole number of at least 1",
        "field": "quantity",
    }
    assert accepted.status_code == 200
    assert accepted.json()["quote"]["totals"]["subtotal"] == 1250.0


# --- precio propio -----------------------------------------------------------


@pytest.mark.django_db
def test_quote_request_ignores_a_price_sent_by_the_client():
    _insert_product()

    response = _request_quote(
        [{"productId": PRODUCT_ID, "quantity": 1, "unitPrice": 0.01, "coreCharge": 0}]
    )

    totals = Quote.objects.get(pk=response.json()["quoteId"]).data["totals"]
    assert (totals["subtotal"], totals["core"]) == (20.0, 1.01)


@pytest.mark.django_db
def test_panel_rejects_a_negative_custom_price():
    response = _panel_quote(_staff_client(), [{"title": "Credit", "quantity": 1, "unitPrice": -50}])

    assert response.status_code == 400
    assert response.json() == {
        "error": "Item prices must be amounts of 0 or more",
        "field": "unit_price",
    }
    assert not Quote.objects.exists()
