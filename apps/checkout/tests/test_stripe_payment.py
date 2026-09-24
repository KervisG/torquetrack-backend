"""El último test recorre los cuatro flujos de cobro con un espía sobre
`start_stripe_payment` en el módulo de cada caller."""
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.checkout import services as checkout_services
from apps.checkout.models import Order, Payment
from apps.checkout.services import start_stripe_payment
from apps.integrations.exceptions import ProviderError
from apps.quotes.models import Quote
from tests.factories import create_staff_user, session_client
from tests.fakes import quote_shipping

CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"


def _fake_session(**kwargs):
    return {"id": "cs_unified", "url": "https://checkout.stripe.com/pay/cs_unified"}


@pytest.fixture(autouse=True)
def _stripe(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    settings.TAXJAR_API_KEY = ""
    settings.RESEND_API_KEY = ""


@pytest.mark.django_db
def test_start_stripe_payment_records_a_pending_payment_for_the_order_total(monkeypatch):
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return _fake_session()

    monkeypatch.setattr(CREATE_SESSION, _create)
    # Un `id` dentro del jsonb nunca desvía la sesión hacia otro pedido.
    order = Order.objects.create(
        id="OID_1",
        number="O30001",
        data={"id": "OID_OTHER", "totals": {"total": 10.005}},
    )

    payment, session = start_stripe_payment(order, data={"source": "TEST"})

    assert session["url"] == "https://checkout.stripe.com/pay/cs_unified"
    payment.refresh_from_db()
    assert payment.order_id == "OID_1"
    assert payment.provider == "stripe"
    assert payment.provider_id == "cs_unified"
    assert payment.status == "PENDING"
    assert payment.amount == Decimal("10.01")
    assert payment.data == {"sessionId": "cs_unified", "source": "TEST"}
    assert captured["client_reference_id"] == "OID_1"
    assert captured["metadata"] == {"order_id": "OID_1", "order_number": "O30001"}


@pytest.mark.django_db
def test_start_stripe_payment_records_nothing_when_stripe_fails(monkeypatch):
    def _boom(**kwargs):
        raise ProviderError("Stripe down")

    monkeypatch.setattr(CREATE_SESSION, _boom)
    order = Order.objects.create(id="OID_2", number="O30002", data={"totals": {"total": 5}})

    with pytest.raises(ProviderError):
        start_stripe_payment(order)

    assert not Payment.objects.exists()


@pytest.mark.django_db
def test_every_payment_flow_goes_through_start_stripe_payment(monkeypatch, settings):
    from apps.checkout import admin_services
    from apps.quotes import services as quote_services

    monkeypatch.setattr(CREATE_SESSION, _fake_session)
    sources = []
    real = checkout_services.start_stripe_payment

    def _spy(order, *, data=None):
        sources.append((data or {}).get("source"))
        return real(order, data=data)

    for module in (checkout_services, admin_services, quote_services):
        monkeypatch.setattr(module, "start_stripe_payment", _spy)

    product = {"id": "p1", "title": "Pump", "price": 100.0, "make": "Ford"}
    Product.objects.create(id="p1", data=product, active=True)
    selection = quote_shipping(
        monkeypatch, settings, zip_code="33701", items=[{"id": "p1", "qty": 1}]
    )
    storefront = APIClient().post(
        "/api/checkout/",
        {
            "items": [{"id": "p1", "qty": 1}],
            "vehicle": {"make": "Ford"},
            "customer": {"state": "FL", "zip": "33701"},
            "shipping": selection,
        },
        format="json",
    )

    Order.objects.create(id="ord_admin", number="O30003", data={"totals": {"total": 20}})
    create_staff_user("U_CASHIER", permissions=["payments.take"])
    staff, _ = session_client("U_CASHIER")
    link = staff.post("/api/admin/orders/ord_admin/payment-link/")
    take = staff.post("/api/admin/orders/ord_admin/take-payment/")

    token = "tok_" + "u" * 48
    Quote.objects.create(
        id="quo_unified",
        number="Q30001",
        status="ACTIVE",
        data={"publicToken": token, "items": [], "totals": {"total": 30}},
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )
    public_quote = APIClient().post(f"/api/quote/public/{token}/checkout/")

    assert [r.status_code for r in (storefront, link, take, public_quote)] == [200] * 4
    assert sources == [
        "STOREFRONT_CHECKOUT",
        "ADMIN_PAYMENT_LINK",
        "EMPLOYEE_TAKE_PAYMENT",
        "PUBLIC_QUOTE",
    ]
    assert Payment.objects.count() == 4
