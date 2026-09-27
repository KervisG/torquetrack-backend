"""`checkout.session.expired` en `POST /api/webhooks/stripe/`.

La firma se verifica con el adaptador real (HMAC local, sin red). La sesión ya
venció en Stripe, así que el evento nunca debe llamar a la API:
`expire_checkout_session` y `retrieve_payment_method` se parchean para que
lancen. Reglas que se assertean a propósito: solo se cancela un pedido
`PENDING_PAYMENT` sin cobrar cuya ÚNICA sesión pendiente es la vencida; un
pedido pagado o con otra sesión vigente no se toca; el evento es idempotente
(una sola fila `ORDER_EXPIRED`) y una cotización con ese pedido vuelve a poder
pagarse.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import Order, Payment
from apps.quotes.models import Quote
from tests.factories import activity_count

WEBHOOK_SECRET = "whsec_test_fake_not_real"
EXPIRE_SESSION = "apps.integrations.payments.stripe.expire_checkout_session"
CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"


def _sign(payload: bytes) -> str:
    ts = int(time.time())
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return f"t={ts},v1={signature}"


def _post_expired(session_id, order_id):
    event = {
        "id": f"evt_{session_id}",
        "type": "checkout.session.expired",
        "data": {
            "object": {
                "id": session_id,
                "status": "expired",
                "payment_status": "unpaid",
                "client_reference_id": order_id,
                "metadata": {"order_id": order_id},
            }
        },
    }
    payload = json.dumps(event).encode()
    return APIClient().post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=_sign(payload),
    )


@pytest.fixture(autouse=True)
def _stripe(settings, monkeypatch):
    settings.STRIPE_WEBHOOK_SECRET = WEBHOOK_SECRET
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"

    def _forbidden(*args, **kwargs):
        raise AssertionError("An expired session must not call the Stripe API")

    monkeypatch.setattr(EXPIRE_SESSION, _forbidden)
    monkeypatch.setattr(
        "apps.integrations.payments.stripe.retrieve_payment_method", _forbidden
    )


def _order(order_id="OID_EXP", status="PENDING_PAYMENT", payment_status="UNPAID", data=None):
    return Order.objects.create(
        id=order_id,
        number=f"N-{order_id}",
        status=status,
        payment_status=payment_status,
        data=data or {"totals": {"total": 100.0}},
    )


def _payment(payment_id, order, session_id, status="PENDING"):
    return Payment.objects.create(
        id=payment_id,
        order=order,
        provider="stripe",
        provider_id=session_id,
        status=status,
        amount=Decimal("100.00"),
        data={"sessionId": session_id},
    )


@pytest.mark.django_db
def test_expired_session_cancels_the_pending_order_and_its_payment(
    django_capture_on_commit_callbacks,
):
    order = _order()
    _payment("PAY_EXP", order, "cs_exp")

    with django_capture_on_commit_callbacks(execute=True):
        response = _post_expired("cs_exp", order.pk)

    assert response.status_code == 200
    assert response.json() == {"received": True}
    payment = Payment.objects.get(pk="PAY_EXP")
    assert payment.status == "CANCELLED"
    assert payment.data["cancelReason"] == "SESSION_EXPIRED"
    order.refresh_from_db()
    assert order.status == "CANCELLED"
    assert order.payment_status == "UNPAID"
    assert order.data["cancelReason"] == "PAYMENT_EXPIRED"
    assert activity_count(action="ORDER_EXPIRED", entity_id=order.pk) == 1


@pytest.mark.django_db
def test_expired_session_is_idempotent(django_capture_on_commit_callbacks):
    order = _order()
    _payment("PAY_EXP", order, "cs_exp")

    with django_capture_on_commit_callbacks(execute=True):
        assert _post_expired("cs_exp", order.pk).status_code == 200
        assert _post_expired("cs_exp", order.pk).status_code == 200

    assert activity_count(action="ORDER_EXPIRED", entity_id=order.pk) == 1
    assert Order.objects.get(pk=order.pk).status == "CANCELLED"


@pytest.mark.django_db
def test_expired_session_leaves_a_paid_order_alone():
    order = _order(status="OPEN", payment_status="PAID")
    _payment("PAY_OLD", order, "cs_old")
    _payment("PAY_OK", order, "cs_ok", status="PAID")

    response = _post_expired("cs_old", order.pk)

    assert response.status_code == 200
    order.refresh_from_db()
    assert (order.status, order.payment_status) == ("OPEN", "PAID")
    assert activity_count(action="ORDER_EXPIRED") == 0


@pytest.mark.django_db
def test_expired_session_keeps_the_order_when_another_session_is_still_open():
    order = _order()
    _payment("PAY_OLD", order, "cs_old")
    _payment("PAY_NEW", order, "cs_new")

    response = _post_expired("cs_old", order.pk)

    assert response.status_code == 200
    assert Payment.objects.get(pk="PAY_OLD").status == "CANCELLED"
    assert Payment.objects.get(pk="PAY_NEW").status == "PENDING"
    assert Order.objects.get(pk=order.pk).status == "PENDING_PAYMENT"
    assert activity_count(action="ORDER_EXPIRED") == 0


@pytest.mark.django_db
def test_expired_session_does_not_cancel_an_order_that_is_not_pending_payment():
    # Un pedido del panel (`OPEN`) cobrado por link: vencer el link no lo anula.
    order = _order(status="OPEN")
    _payment("PAY_LINK", order, "cs_link")

    response = _post_expired("cs_link", order.pk)

    assert response.status_code == 200
    assert Payment.objects.get(pk="PAY_LINK").status == "CANCELLED"
    assert Order.objects.get(pk=order.pk).status == "OPEN"
    assert activity_count(action="ORDER_EXPIRED") == 0


@pytest.mark.django_db
def test_unknown_expired_session_is_acknowledged_without_changes():
    order = _order()
    _payment("PAY_EXP", order, "cs_exp")

    response = _post_expired("cs_unknown", order.pk)

    assert response.status_code == 200
    assert Order.objects.get(pk=order.pk).status == "PENDING_PAYMENT"
    assert Payment.objects.get(pk="PAY_EXP").status == "PENDING"


@pytest.mark.django_db
def test_a_quote_whose_order_expired_can_be_paid_again(
    monkeypatch, django_capture_on_commit_callbacks
):
    items = [{"productId": "p1", "title": "Pump", "quantity": 1, "unitPrice": 100.0}]
    totals = {"subtotal": 100.0, "core": 0, "shipping": 0, "tax": 0, "total": 100.0}
    quote = Quote.objects.create(
        id="QID_EXP",
        number="Q48001",
        status="CONVERTED",
        expires_at=timezone.now() + timezone.timedelta(days=30),
        data={
            "publicToken": "tok_exp",
            "items": items,
            "totals": totals,
            "orderNumber": "N-OID_EXP",
        },
    )
    order = _order(data={"quoteNumber": quote.number, "items": items, "totals": totals})
    _payment("PAY_EXP", order, "cs_exp")

    with django_capture_on_commit_callbacks(execute=True):
        assert _post_expired("cs_exp", order.pk).status_code == 200

    assert APIClient().get("/api/quote/public/tok_exp/details/").json()["payable"] is True
    monkeypatch.setattr(
        CREATE_SESSION, lambda **kwargs: {"id": "cs_again", "url": "https://pay/cs_again"}
    )
    response = APIClient().post("/api/quote/public/tok_exp/checkout/")

    assert response.status_code == 200
    assert response.json()["url"] == "https://pay/cs_again"
    assert response.json()["orderNumber"] != order.number
