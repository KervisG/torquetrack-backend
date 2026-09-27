"""`BUILDING` todavía no tiene precio confirmado y `LOST` la cerró ventas: el
checkout responde 409 sin tocar Stripe ni crear pedidos."""

import logging
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.cart.models import Cart
from apps.catalog.models import Product
from apps.checkout.models import Order, Payment
from apps.customers.models import Customer
from apps.integrations.exceptions import ProviderError
from apps.quotes.models import Quote
from tests.factories import guest_cart_client
from tests.fakes import install_resend

CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"

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
def test_quote_request_never_overwrites_an_existing_guest_profile(client):
    # El email del body no prueba nada: la cotización se asocia al invitado
    # existente y el nombre y teléfono nuevos quedan solo en su snapshot.
    _insert_product()
    Customer.objects.create(
        id="C_GUEST_1", email="jane@example.com", data={"name": "Jane Real", "phone": "555-1"}
    )

    response = client.post(
        "/api/quote/request/",
        {
            "customer": {"name": "Mallory", "email": "JANE@example.com", "phone": "555-9"},
            "items": [{"productId": PRODUCT_ID, "quantity": 1}],
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    quote = Quote.objects.get(pk=response.json()["quoteId"])
    assert quote.customer_id == "C_GUEST_1"
    assert quote.data["customer"]["name"] == "Mallory"
    assert Customer.objects.get(pk="C_GUEST_1").data == {"name": "Jane Real", "phone": "555-1"}


@pytest.mark.django_db
def test_quote_request_links_the_session_cart():
    _insert_product()
    _insert_cart("cart_quote_1", {"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"})

    response = guest_cart_client("cart_quote_1").post(
        "/api/quote/request/",
        {
            "customer": {"name": "Jane Diesel"},
            "items": [{"productId": PRODUCT_ID, "quantity": 1}],
        },
        format="json",
    )

    assert response.status_code == 200
    data = Cart.objects.get(pk="cart_quote_1").data
    assert data["stage"] == "BUILDING_QUOTE"
    assert data["quoteId"] == response.json()["quoteId"]


@pytest.mark.django_db
def test_signed_in_quote_request_links_the_account_cart():
    from tests.factories import create_user, session_client

    _insert_product()
    user = create_user("U_QUOTE_CART")
    Cart.objects.create(
        id="cart_account",
        user=user,
        data={"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"},
    )
    client, _ = session_client("U_QUOTE_CART")

    response = client.post(
        "/api/quote/request/",
        {"customer": {"name": "Jane Diesel"}, "items": [{"id": PRODUCT_ID, "qty": 1}]},
        format="json",
    )

    assert response.status_code == 200
    data = Cart.objects.get(pk="cart_account").data
    assert data["stage"] == "BUILDING_QUOTE"
    assert data["quoteId"] == response.json()["quoteId"]


@pytest.mark.django_db
def test_quote_request_ignores_a_body_cart_id(client):
    _insert_product()
    victim = {"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"}
    _insert_cart("cart_victim", victim)

    response = client.post(
        "/api/quote/request/",
        {
            "customer": {"name": "Jane Diesel"},
            "items": [{"productId": PRODUCT_ID, "quantity": 1}],
            "cartId": "cart_victim",
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert Cart.objects.get(pk="cart_victim").data == victim
    assert "cart_victim" not in Quote.objects.get().data["memo"]


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
def test_public_view_footer_uses_the_company_settings(client, settings):
    settings.SALES_EMAIL = "parts@shop.example.com"
    settings.APP_URL = "https://shop.example.com/"
    settings.COMPANY_ADDRESS = "Tampa, FL"
    _make_quote()

    body = client.get(f"/api/quote/public/{'tok_' + 'a' * 48}/").content.decode()

    assert "parts@shop.example.com" in body
    assert "Tampa, FL" in body
    assert "shop.example.com</div>" in body
    assert "torquetrackdiesel.com" not in body
    assert "Sarasota" not in body


@pytest.mark.django_db
def test_public_view_footer_omits_an_unset_sales_email(client, settings):
    settings.SALES_EMAIL = ""
    settings.COMPANY_ADDRESS = "Tampa, FL"
    _make_quote()

    body = client.get(f"/api/quote/public/{'tok_' + 'a' * 48}/").content.decode()

    assert "Tampa, FL" in body
    assert "&bull; Tampa" not in body
    assert "teams@" not in body


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
    # No se reabre sola: el estado y el vencimiento quedan intactos.
    quote = Quote.objects.get(pk="quo_pub_expired")
    assert quote.status == "ACTIVE"


# --- quote/public/<token>/details (GET, JSON para el SPA) ---------------


@pytest.mark.django_db
def test_public_details_returns_the_customer_facing_quote(client):
    _make_quote(data={"memo": "Internal note", "createdBy": "rep@example.com"})

    response = client.get(f"/api/quote/public/{'tok_' + 'a' * 48}/details/")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert body["number"] == "Q10001"
    assert body["status"] == "ACTIVE"
    assert body["customer"] == {"name": "Jane Diesel", "company": ""}
    assert body["vehicle"] == {"year": 2004, "make": "Dodge", "model": "Ram 2500"}
    assert body["items"] == [
        {
            "title": "5.9L Cummins HX35 Turbocharger",
            "partNumber": "HX35-590",
            "quantity": 1,
            "unitPrice": 429.0,
            "coreCharge": 150.0,
            "lineTotal": 579.0,
        }
    ]
    assert body["totals"] == {
        "subtotal": 429.0,
        "core": 150.0,
        "shipping": 0,
        "tax": 0,
        "total": 579.0,
    }
    assert body["expiresAt"]
    assert body["createdAt"]
    serialized = response.content.decode()
    assert "tok_" not in serialized
    assert "Internal note" not in serialized
    assert "jane@example.com" not in serialized
    assert "rep@example.com" not in serialized


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status, paid_order, payable",
    [
        ("ACTIVE", False, True),
        ("CONTACTED", False, True),
        ("CONVERTED", False, True),
        ("CONVERTED", True, False),
        ("ACTIVE", True, False),
        ("BUILDING", False, False),
        ("LOST", False, False),
        ("EXPIRED", False, False),
    ],
)
def test_public_details_says_whether_checkout_is_available(client, status, paid_order, payable):
    # `payable` sale de la misma regla que `checkout_from_quote`: el SPA no
    # decide con su propia lista de estados.
    quote = _make_quote(status=status)
    if paid_order:
        _insert_quote_order(quote, "OID_PAID_DETAILS", "O20009", payment_status="PAID")

    response = client.get(f"/api/quote/public/{'tok_' + 'a' * 48}/details/")

    assert response.status_code == 200
    assert response.json()["payable"] is payable


@pytest.mark.django_db
def test_public_details_returns_404_for_unknown_token(client):
    response = client.get("/api/quote/public/does-not-exist/details/")

    assert response.status_code == 404
    assert response.json() == {"error": "Quote not found"}


@pytest.mark.django_db
def test_public_details_denies_expired_token(client):
    token = "tok_" + "c" * 48
    _make_quote(
        quote_id="quo_pub_expired_json",
        number="Q10003",
        token=token,
        expires_at=timezone.now() - timezone.timedelta(days=1),
    )

    response = client.get(f"/api/quote/public/{token}/details/")

    assert response.status_code == 410
    assert response.json() == {"error": "This quote has expired"}
    assert Quote.objects.get(pk="quo_pub_expired_json").status == "ACTIVE"


# --- quote/public/<token>/checkout (POST) -------------------------------


@pytest.mark.django_db
def test_public_checkout_creates_order_and_stripe_session(client, monkeypatch):
    token = "tok_" + "c" * 48
    _make_quote(quote_id="quo_checkout_1", number="Q10003", token=token)
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

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
    existing_order = _insert_quote_order(quote, "OID_EXISTING", "O99999")
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 200
    assert response.json()["orderNumber"] == existing_order.number
    assert Order.objects.filter(data__quoteNumber=quote.number).count() == 1


@pytest.mark.django_db
def test_public_checkout_hides_the_stripe_error_and_logs_it(client, monkeypatch, caplog):
    token = "tok_" + "s" * 48
    _make_quote(quote_id="quo_checkout_err", number="Q10009", token=token)

    def _boom(**kwargs):
        raise ProviderError("Invalid API Key for account acct_internal_123")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    with caplog.at_level(logging.WARNING, logger="apps.quotes.services.storefront"):
        response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 502
    assert response.json() == {"error": "Payment could not be started. Please try again."}
    assert "acct_internal_123" in caplog.text


def _insert_quote_order(quote, order_id, number, payment_status="UNPAID", **overrides):
    """Pedido de la cotización con el mismo snapshot de líneas y totales."""
    data = {
        "quoteNumber": quote.number,
        "items": quote.data["items"],
        "totals": quote.data["totals"],
        **overrides.pop("data", {}),
    }
    return Order.objects.create(
        id=order_id,
        number=number,
        status=overrides.pop("status", "PENDING_PAYMENT"),
        payment_status=payment_status,
        data=data,
    )


def _forbid_stripe(monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("Stripe must not be called for this quote")

    monkeypatch.setattr(CREATE_SESSION, _boom)


@pytest.mark.django_db
# Un reembolso no vuelve a abrir el cobro: el pedido sigue cobrado.
@pytest.mark.parametrize("payment_status", ["PAID", "PARTIALLY_REFUNDED", "REFUNDED"])
def test_public_checkout_refuses_a_quote_that_is_already_paid(client, monkeypatch, payment_status):
    token = "tok_" + "p" * 48
    quote = _make_quote(
        quote_id="quo_paid_1",
        number="Q10020",
        token=token,
        status="CONVERTED",
        data={"orderNumber": "O20001"},
    )
    _insert_quote_order(quote, "OID_PAID", "O20001", payment_status=payment_status, status="OPEN")
    _forbid_stripe(monkeypatch)

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 409
    assert response.json() == {"error": "This quote has already been paid"}
    assert Order.objects.filter(data__quoteNumber="Q10020").count() == 1
    assert Quote.objects.get(pk="quo_paid_1").data["orderNumber"] == "O20001"


@pytest.mark.django_db
def test_public_checkout_twice_after_payment_does_not_charge_again(client, monkeypatch):
    token = "tok_" + "q" * 48
    _make_quote(quote_id="quo_paid_2", number="Q10021", token=token)
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    first = client.post(f"/api/quote/public/{token}/checkout/")
    Order.objects.filter(number=first.json()["orderNumber"]).update(payment_status="PAID")
    _forbid_stripe(monkeypatch)
    second = client.post(f"/api/quote/public/{token}/checkout/")

    assert second.status_code == 409
    assert Order.objects.filter(data__quoteNumber="Q10021").count() == 1


@pytest.mark.django_db
def test_public_checkout_replaces_an_order_with_stale_totals(client, monkeypatch):
    # El staff editó la cotización después del primer checkout: el pedido
    # viejo no se cobra con los totales anteriores.
    token = "tok_" + "s" * 48
    quote = _make_quote(quote_id="quo_stale_1", number="Q10022", token=token)
    stale = _insert_quote_order(
        quote,
        "OID_STALE",
        "O20002",
        data={"totals": {"subtotal": 1.0, "core": 0, "shipping": 0, "tax": 0, "total": 1.0}},
    )
    Payment.objects.create(
        id="PAY_STALE", order=stale, provider="stripe", provider_id="cs_stale", status="PENDING"
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session("cs_fresh"))

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 200
    number = response.json()["orderNumber"]
    assert number != "O20002"
    fresh = Order.objects.get(number=number)
    assert fresh.data["totals"]["total"] == 579.0
    assert Payment.objects.get(order=fresh).amount == Decimal("579.00")
    stale.refresh_from_db()
    assert stale.status == "CANCELLED"
    assert stale.data["cancelReason"] == "QUOTE_CHANGED"
    assert Payment.objects.get(pk="PAY_STALE").status == "CANCELLED"
    assert Quote.objects.get(pk="quo_stale_1").data["orderNumber"] == number


@pytest.mark.django_db
def test_public_checkout_never_reuses_a_cancelled_order(client, monkeypatch):
    token = "tok_" + "x" * 48
    quote = _make_quote(quote_id="quo_cancelled_1", number="Q10023", token=token)
    _insert_quote_order(quote, "OID_CANCELLED", "O20003", status="CANCELLED")
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 200
    assert response.json()["orderNumber"] != "O20003"


@pytest.mark.django_db
def test_public_checkout_returns_410_for_expired_quote(client, monkeypatch):
    token = "tok_" + "e" * 48
    _make_quote(
        quote_id="quo_checkout_expired",
        number="Q10005",
        token=token,
        expires_at=timezone.now() - timezone.timedelta(days=1),
    )
    _forbid_stripe(monkeypatch)

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 410
    assert response.json() == {"error": "This quote has expired"}
    assert not Order.objects.filter(data__quoteNumber="Q10005").exists()


@pytest.mark.django_db
def test_public_checkout_returns_410_for_expired_status_even_before_the_date(client, monkeypatch):
    token = "tok_" + "f" * 48
    _make_quote(quote_id="quo_status_expired", number="Q10006", token=token, status="EXPIRED")
    _forbid_stripe(monkeypatch)

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 410
    assert response.json() == {"error": "This quote has expired"}
    assert Quote.objects.get(pk="quo_status_expired").status == "EXPIRED"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status, message",
    [
        ("BUILDING", "This quote is still being prepared. Contact TorqueTrack to finalize it."),
        ("LOST", "This quote is closed. Contact TorqueTrack for a new quote."),
        ("ARCHIVED", "This quote is closed. Contact TorqueTrack for a new quote."),
    ],
)
def test_public_checkout_rejects_non_payable_statuses(client, monkeypatch, status, message):
    token = "tok_" + "n" * 48
    _make_quote(quote_id="quo_not_payable", number="Q10007", token=token, status=status)
    _forbid_stripe(monkeypatch)

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 409
    assert response.json() == {"error": message}
    assert not Order.objects.filter(data__quoteNumber="Q10007").exists()
    assert Quote.objects.get(pk="quo_not_payable").status == status


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["ACTIVE", "CONTACTED", "CONVERTED"])
def test_public_checkout_accepts_payable_statuses(client, monkeypatch, status):
    token = "tok_" + "y" * 48
    _make_quote(quote_id="quo_payable", number="Q10008", token=token, status=status)
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = client.post(f"/api/quote/public/{token}/checkout/")

    assert response.status_code == 200
    assert Quote.objects.get(pk="quo_payable").status == "CONVERTED"


@pytest.mark.django_db
def test_public_checkout_returns_404_for_unknown_token(client):
    response = client.post("/api/quote/public/does-not-exist/checkout/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_quote_request_emails_escape_customer_and_product_data(client, settings, monkeypatch):
    # El nombre, el teléfono y los datos de la pieza llegan al HTML del correo:
    # sin escapar, un cliente podría inyectar marcado en la bandeja de ventas.
    settings.RESEND_API_KEY = "re_test_fake"
    settings.SALES_EMAIL = "sales@example.com"
    _insert_product(
        data={**PRODUCT_DATA, "title": "<b>Turbo</b>", "partNumber": "<i>HX35</i>"}
    )
    resend = install_resend(monkeypatch)

    response = client.post(
        "/api/quote/request/",
        {
            "customer": {
                "name": "<script>alert(1)</script>",
                "email": "jane@example.com",
                "phone": "<b>555</b>",
            },
            "items": [{"productId": PRODUCT_ID, "quantity": 1}],
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    staff_html, customer_html = resend.sent[0]["html"], resend.sent[1]["html"]
    for html in (staff_html, customer_html):
        assert "<script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;555&lt;/b&gt;" in staff_html
    assert "&lt;b&gt;Turbo&lt;/b&gt;" in staff_html
    assert "&lt;i&gt;HX35&lt;/i&gt;" in staff_html
