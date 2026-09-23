"""`POST /api/quote/request`, `GET /api/quote/public/<token>`, and
`POST /api/quote/public/<token>/checkout` (task 6.1), pinned against
`app/api/quote/request/route.ts`, `app/api/quote/public/[token]/route.ts`,
and `app/api/quote/public/[token]/checkout/route.ts`.

Spec deviation (documented, matching Phase 5's precedent of intentional,
documented improvements over a legacy gap): the legacy GET and PDF public
routes never checked `expires_at`, only the checkout sub-route did (409).
The spec's "Public Magic-Link Quote Access" requirement explicitly demands
expired-token denial on every public action, so this phase adds that check
to the GET view too (410 Gone) — a read-only `expires_at` comparison, never
mutating `status`, so "no auto-reopen" holds trivially.
"""

import pytest
from django.utils import timezone

from apps.cart.models import Cart
from apps.catalog.models import Product
from apps.checkout.models import Order, Payment
from apps.quotes.models import Quote

PRODUCT_ID = "cummins-5.9-turbo-holset-hx35"
PRODUCT_DATA = {
    "id": PRODUCT_ID,
    "title": "5.9L Cummins HX35 Turbocharger",
    "partNumber": "HX35-590",
    "price": 429.0,
    "coreCharge": 150.0,
}


def _insert_product(product_id=PRODUCT_ID, data=None, active=True):
    Product.objects.create(id=product_id, data=data or PRODUCT_DATA, active=active)


def _insert_cart(cart_id, data):
    Cart.objects.create(id=cart_id, data=data)


def _make_quote(
    quote_id="quo_pub_1",
    number="Q10001",
    token="tok_" + "a" * 48,
    status="ACTIVE",
    expires_at=None,
    data=None,
):
    expires_at = expires_at or (timezone.now() + timezone.timedelta(days=30))
    quote = Quote.objects.create(
        id=quote_id,
        number=number,
        status=status,
        data={
            "publicToken": token,
            "customer": {"name": "Jane Diesel", "email": "jane@example.com"},
            "vehicle": {"year": 2004, "make": "Dodge", "model": "Ram 2500"},
            "items": [
                {
                    "productId": PRODUCT_ID,
                    "title": "5.9L Cummins HX35 Turbocharger",
                    "partNumber": "HX35-590",
                    "quantity": 1,
                    "unitPrice": 429.0,
                    "coreCharge": 150.0,
                }
            ],
            "totals": {"subtotal": 429.0, "core": 150.0, "shipping": 0, "tax": 0, "total": 579.0},
            **(data or {}),
        },
        created_at=timezone.now(),
        expires_at=expires_at,
        updated_at=timezone.now(),
    )
    return quote


def _fake_session(session_id="cs_test_quote", url="https://checkout.stripe.com/pay/cs_test_quote"):
    return {"id": session_id, "url": url}


@pytest.fixture(autouse=True)
def _stripe_secret_key(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    settings.RESEND_API_KEY = ""
    settings.SALES_EMAIL = ""
    return settings


# --- quote/request -----------------------------------------------------


@pytest.mark.django_db
def test_quote_request_requires_name(client):
    response = client.post(
        "/api/quote/request/",
        {"customer": {"email": "x@example.com"}, "items": [{"productId": PRODUCT_ID}]},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Name or company is required"


@pytest.mark.django_db
def test_quote_request_requires_non_empty_items(client):
    response = client.post(
        "/api/quote/request/",
        {"customer": {"name": "Jane Diesel"}, "items": []},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Cart is empty"


@pytest.mark.django_db
def test_quote_request_rejects_all_unknown_products(client):
    response = client.post(
        "/api/quote/request/",
        {"customer": {"name": "Jane Diesel"}, "items": [{"productId": "does-not-exist"}]},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "No valid products"


@pytest.mark.django_db
def test_quote_request_creates_quote_with_computed_totals(client):
    _insert_product()

    response = client.post(
        "/api/quote/request/",
        {
            "customer": {"name": "Jane Diesel", "email": "jane@example.com", "phone": "555-1000"},
            "vehicle": {"year": 2004, "make": "Dodge"},
            "items": [{"productId": PRODUCT_ID, "quantity": 2}],
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    quote = Quote.objects.get(pk=body["quoteId"])
    assert quote.number == body["quoteNumber"]
    assert quote.status == "BUILDING"
    # 429.00 * 2 = 858.00, core 150.00 * 2 = 300.00
    assert quote.data["totals"]["subtotal"] == 858.0
    assert quote.data["totals"]["core"] == 300.0
    assert quote.data["totals"]["total"] == 1158.0
    assert quote.customer_id is not None
    assert quote.customer.email == "jane@example.com"


@pytest.mark.django_db
def test_quote_request_links_cart_when_cart_id_present(client):
    _insert_product()
    _insert_cart("cart_quote_1", {"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"})

    response = client.post(
        "/api/quote/request/",
        {
            "customer": {"name": "Jane Diesel"},
            "items": [{"productId": PRODUCT_ID, "quantity": 1}],
            "cartId": "cart_quote_1",
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    data = Cart.objects.get(pk="cart_quote_1").data
    assert data["stage"] == "BUILDING_QUOTE"
    assert data["quoteId"] == response.json()["quoteId"]


# --- quote/public/<token> (GET) ----------------------------------------


@pytest.mark.django_db
def test_public_view_renders_html_for_valid_token(client):
    _make_quote()

    response = client.get(f"/api/quote/public/{'tok_' + 'a' * 48}/")

    assert response.status_code == 200
    assert response["content-type"].startswith("text/html")
    body = response.content.decode()
    assert "Q10001" in body
    assert "Jane Diesel" in body
    assert "HX35-590" in body


@pytest.mark.django_db
def test_public_view_returns_404_for_unknown_token(client):
    response = client.get("/api/quote/public/does-not-exist/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_public_view_denies_expired_token(client):
    token = "tok_" + "b" * 48
    _make_quote(
        quote_id="quo_pub_expired",
        number="Q10002",
        token=token,
        expires_at=timezone.now() - timezone.timedelta(days=1),
    )

    response = client.get(f"/api/quote/public/{token}/")

    assert response.status_code == 410
    # No auto-reopen: the quote's own status/expiry must stay untouched.
    quote = Quote.objects.get(pk="quo_pub_expired")
    assert quote.status == "ACTIVE"


# --- quote/public/<token>/checkout (POST) -------------------------------


@pytest.mark.django_db
def test_public_checkout_creates_order_and_stripe_session(client, monkeypatch):
    token = "tok_" + "c" * 48
    _make_quote(quote_id="quo_checkout_1", number="Q10003", token=token)
    monkeypatch.setattr("stripe.checkout.Session.create", lambda **kwargs: _fake_session())

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["url"] == "https://checkout.stripe.com/pay/cs_test_quote"

    order = Order.objects.get(number=body["orderNumber"])
    assert order.status == "PENDING_PAYMENT"
    assert order.payment_status == "UNPAID"
    assert order.data["quoteNumber"] == "Q10003"

    payment = Payment.objects.get(order=order)
    assert payment.data["source"] == "PUBLIC_QUOTE"

    quote = Quote.objects.get(pk="quo_checkout_1")
    assert quote.status == "CONVERTED"
    assert quote.data["orderNumber"] == order.number


@pytest.mark.django_db
def test_public_checkout_reuses_existing_unpaid_order(client, monkeypatch):
    token = "tok_" + "d" * 48
    quote = _make_quote(quote_id="quo_checkout_2", number="Q10004", token=token)
    existing_order = Order.objects.create(
        id="OID_EXISTING",
        number="O99999",
        status="PENDING_PAYMENT",
        payment_status="UNPAID",
        data={"quoteNumber": quote.number},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )
    monkeypatch.setattr("stripe.checkout.Session.create", lambda **kwargs: _fake_session())

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 200
    assert response.json()["orderNumber"] == existing_order.number
    assert Order.objects.filter(data__quoteNumber=quote.number).count() == 1


@pytest.mark.django_db
def test_public_checkout_returns_409_for_expired_quote(client):
    token = "tok_" + "e" * 48
    _make_quote(
        quote_id="quo_checkout_expired",
        number="Q10005",
        token=token,
        expires_at=timezone.now() - timezone.timedelta(days=1),
    )

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 409
    assert response.json()["error"] == "This quote has expired"


@pytest.mark.django_db
def test_public_checkout_returns_404_for_unknown_token(client):
    response = client.post("/api/quote/public/does-not-exist/checkout/")

    assert response.status_code == 404
