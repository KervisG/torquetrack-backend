"""Flujo de cobro con Authorize.net: `GET /api/payments/<id>/pay/`,
`POST /api/webhooks/authorize-net/` y el vencimiento de pagos pendientes.

Se parchean `create_hosted_payment_token` y `get_transaction` del adaptador;
la firma del webhook se calcula con un HMAC-SHA512 real. Un test por regla.
"""
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import Order, Payment
from apps.checkout.tasks import expire_pending_payments
from apps.integrations.exceptions import ProviderError
from tests.factories import activity_count

ADAPTER = "apps.integrations.payments.authorize_net"
SIGNATURE_KEY = "anet_signature_fake"


@pytest.fixture(autouse=True)
def _gateway(settings, db):
    settings.AUTHORIZE_NET_API_LOGIN_ID = "anet_login_fake"
    settings.AUTHORIZE_NET_TRANSACTION_KEY = "anet_key_fake"
    settings.AUTHORIZE_NET_SIGNATURE_KEY = SIGNATURE_KEY
    settings.RESEND_API_KEY = ""
    cache.clear()
    yield
    cache.clear()


def _pending_order(order_id="ord_f1", status="PENDING_PAYMENT", total="120.00"):
    order = Order.objects.create(
        id=order_id,
        number=f"N-{order_id}",
        status=status,
        payment_status="UNPAID",
        data={"totals": {"total": float(total)}, "customer": {"email": "buyer@example.com"}},
    )
    payment = Payment.objects.create(
        id=f"PAY{order_id.upper()}",
        order=order,
        provider="authorize_net",
        status="PENDING",
        amount=Decimal(total),
    )
    return order, payment


def _webhook(event_type, trans_id="60001"):
    body = json.dumps(
        {
            "notificationId": "n-1",
            "eventType": event_type,
            "payload": {"entityName": "transaction", "id": trans_id},
        }
    ).encode()
    signature = hmac.new(SIGNATURE_KEY.encode(), body, hashlib.sha512).hexdigest().upper()
    return APIClient().post(
        "/api/webhooks/authorize-net/",
        body,
        content_type="application/json",
        HTTP_X_ANET_SIGNATURE=f"sha512={signature}",
    )


def _transaction(monkeypatch, **overrides):
    details = {
        "id": "60001",
        "type": "authCaptureTransaction",
        "status": "capturedPendingSettlement",
        "responseCode": 1,
        "amount": Decimal("120.00"),
        "invoiceNumber": "PAYORD_F1",
        "refTransId": None,
        "cardType": "Visa",
        "last4": "1111",
        "email": "buyer@example.com",
        **overrides,
    }
    monkeypatch.setattr(f"{ADAPTER}.get_transaction", lambda trans_id: details)


# --- S5: puente al formulario --------------------------------------------


def test_payment_page_posts_a_fresh_token_to_the_hosted_form(monkeypatch):
    _, payment = _pending_order()
    captured = {}

    def _token(**kwargs):
        captured.update(kwargs)
        return {"token": "tok_abc", "formUrl": "https://test.authorize.net/payment/payment"}

    monkeypatch.setattr(f"{ADAPTER}.create_hosted_payment_token", _token)

    response = APIClient().get(f"/api/payments/{payment.pk}/pay/")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'action="https://test.authorize.net/payment/payment"' in html
    assert 'name="token" value="tok_abc"' in html
    assert response["Cache-Control"] == "no-store"
    assert captured["invoice_number"] == payment.pk
    assert captured["amount"] == Decimal("120.00")


@pytest.mark.parametrize(("status", "code"), [("CANCELLED", 410), ("PAID", 302)])
def test_payment_page_never_reopens_a_closed_payment(monkeypatch, status, code):
    _, payment = _pending_order()
    Payment.objects.filter(pk=payment.pk).update(status=status)

    def _boom(**kwargs):
        raise AssertionError("No token for a payment that is not pending")

    monkeypatch.setattr(f"{ADAPTER}.create_hosted_payment_token", _boom)

    response = APIClient().get(f"/api/payments/{payment.pk}/pay/")

    assert response.status_code == code


# --- S6: webhook ------------------------------------------------------------


def test_webhook_with_an_invalid_signature_changes_nothing(monkeypatch):
    _pending_order()

    response = APIClient().post(
        "/api/webhooks/authorize-net/",
        b'{"eventType": "net.authorize.payment.authcapture.created"}',
        content_type="application/json",
        HTTP_X_ANET_SIGNATURE="sha512=" + "0" * 128,
    )

    assert response.status_code == 400
    assert Order.objects.get().payment_status == "UNPAID"


def test_captured_transaction_marks_the_order_paid_once(monkeypatch):
    _pending_order()
    _transaction(monkeypatch)

    first = _webhook("net.authorize.payment.authcapture.created")
    replay = _webhook("net.authorize.payment.authcapture.created")

    assert first.status_code == replay.status_code == 200
    order = Order.objects.get()
    assert order.status == "OPEN"
    assert order.payment_status == "PAID"
    assert order.data["payment"]["transactionId"] == "60001"
    payment = Payment.objects.get()
    assert payment.status == "PAID"
    assert payment.provider_id == "60001"
    assert activity_count(action="PAYMENT_PAID", entity_id="ord_f1") == 1


def test_a_different_charged_amount_does_not_pay_the_order(monkeypatch):
    _pending_order()
    _transaction(monkeypatch, amount=Decimal("1.00"))

    assert _webhook("net.authorize.payment.authcapture.created").status_code == 200

    assert Order.objects.get().payment_status == "UNPAID"
    assert activity_count(action="PAYMENT_AMOUNT_MISMATCH", entity_id="ord_f1") == 1


def test_fraud_hold_flags_the_order_without_paying_it(monkeypatch):
    _pending_order()
    _transaction(monkeypatch, status="FDSPendingReview")

    assert _webhook("net.authorize.payment.fraud.held").status_code == 200

    order = Order.objects.get()
    assert order.payment_status == "UNPAID"
    assert order.data["fraudWarning"]["id"] == "60001"


def test_unreadable_transaction_answers_503_so_the_gateway_retries(monkeypatch):
    _pending_order()

    def _down(trans_id):
        raise ProviderError("timeout")

    monkeypatch.setattr(f"{ADAPTER}.get_transaction", _down)

    assert _webhook("net.authorize.payment.authcapture.created").status_code == 503


# --- S8: vencimiento ----------------------------------------------------------


def test_stale_pending_payment_expires_and_cancels_the_store_order():
    _, payment = _pending_order()
    Payment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(hours=25))
    _pending_order(order_id="ord_fresh")

    cancelled = expire_pending_payments.delay().get()

    assert cancelled == 1
    assert Order.objects.get(pk="ord_f1").status == "CANCELLED"
    assert Order.objects.get(pk="ord_fresh").status == "PENDING_PAYMENT"
    assert activity_count(action="ORDER_EXPIRED", entity_id="ord_f1") == 1
