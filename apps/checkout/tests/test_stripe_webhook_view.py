"""Tests de `POST /api/webhooks/stripe`.

La verificación de firma pasa por el adaptador real
(`apps.integrations.payments.stripe.construct_webhook_event`), que usa el SDK
oficial: es un chequeo HMAC local, sin red ni API key real, así que el test
calcula una firma válida igual que Stripe (esquema `t=<ts>,v1=<hmac>`).
`retrieve_payment_method` del adaptador (marca/últimos 4 de la tarjeta del
pedido pagado) SÍ se parchea, porque llamaría a la API real de Stripe.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.checkout.models import Order, Payment
from tests.factories import activity_count

WEBHOOK_SECRET = "whsec_test_fake_not_real"


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET, timestamp=None) -> str:
    """Replica el esquema de firma de Stripe: `t=<unix ts>,v1=hmac_sha256(
    secret, f"{t}.{payload}")`."""
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


def _insert_order(order_id, number, status, payment_status, data, customer_id=None):
    Order.objects.create(
        id=order_id,
        number=number,
        customer_id=customer_id,
        status=status,
        payment_status=payment_status,
        data=data,
    )


def _insert_payment(payment_id, order_id, status, data):
    Payment.objects.create(
        id=payment_id,
        order_id=order_id,
        provider="stripe",
        status=status,
        amount=Decimal("239.99"),
        data=data,
    )


def _checkout_completed_event(order_id, event_id="evt_test_1", payment_intent="pi_test_1"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_1",
                "payment_intent": payment_intent,
                "payment_status": "paid",
                "amount_total": 23999,
                "client_reference_id": order_id,
                "metadata": {"order_id": order_id, "order_number": "O10001"},
                "customer_details": {"email": "buyer@example.com"},
            }
        },
    }


@pytest.fixture(autouse=True)
def _webhook_secret(settings, monkeypatch):
    settings.STRIPE_WEBHOOK_SECRET = WEBHOOK_SECRET
    settings.STRIPE_SECRET_KEY = ""  # no payment-method enrichment call by default
    return settings


@pytest.mark.django_db
def test_returns_503_when_webhook_secret_not_configured(settings):
    settings.STRIPE_WEBHOOK_SECRET = ""

    response = APIClient().post(
        "/api/webhooks/stripe/",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=deadbeef",
    )

    assert response.status_code == 503


@pytest.mark.django_db
def test_invalid_signature_is_rejected_with_no_state_change():
    _insert_order("ord_bad_sig", "O10001", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    payload = json.dumps(_checkout_completed_event("ord_bad_sig")).encode()

    response = APIClient().post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=" + "0" * 64,
    )

    assert response.status_code == 400
    order = Order.objects.get(pk="ord_bad_sig")
    assert order.status == "PENDING_PAYMENT"
    assert order.payment_status == "UNPAID"


@pytest.mark.django_db
def test_missing_signature_header_is_rejected():
    payload = json.dumps(_checkout_completed_event("ord_missing_sig")).encode()

    response = APIClient().post(
        "/api/webhooks/stripe/", data=payload, content_type="application/json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_valid_signature_marks_order_paid_and_reconciles_payment(monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.payments.stripe.retrieve_payment_method",
        lambda payment_intent_id: {"brand": "visa", "last4": "4242", "funding": "credit"},
    )
    _insert_order(
        "ord_paid_1",
        "O10001",
        "PENDING_PAYMENT",
        "UNPAID",
        {"totals": {"core": 0}},
    )
    _insert_payment("pay_1", "ord_paid_1", "PENDING", {"sessionId": "cs_test_1"})

    payload = json.dumps(_checkout_completed_event("ord_paid_1")).encode()
    signature = _sign(payload)

    response = APIClient().post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=signature,
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}

    order = Order.objects.get(pk="ord_paid_1")
    assert order.status == "OPEN"
    assert order.payment_status == "PAID"
    assert order.data["payment"]["brand"] == "visa"
    assert order.data["payment"]["last4"] == "4242"

    payment = Payment.objects.get(pk="pay_1")
    assert payment.status == "PAID"
    assert payment.provider_id == "cs_test_1"
    assert payment.data["customer_email"] == "buyer@example.com"

    assert activity_count(entity_id="ord_paid_1", action="PAYMENT_PAID") == 1


@pytest.mark.django_db
def test_core_charge_opens_core_case_when_core_amount_present(monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.payments.stripe.retrieve_payment_method", lambda payment_intent_id: None
    )
    _insert_order("ord_core_1", "O10002", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 50.0}})
    _insert_payment("pay_core_1", "ord_core_1", "PENDING", {"sessionId": "cs_test_2"})

    payload = json.dumps(_checkout_completed_event("ord_core_1")).encode()
    response = APIClient().post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=_sign(payload),
    )

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_core_1")
    assert order.data["coreCase"]["status"] == "AWAITING CORE"
    assert order.data["coreCase"]["amount"] == 50.0


@pytest.mark.django_db
def test_replaying_the_same_event_id_is_idempotent(monkeypatch):
    """Stripe can and does resend webhook events; a second delivery of the
    same (or an equivalent) success event for an already-paid order must
    not duplicate the audit log entry or re-run the payment reconciliation."""
    monkeypatch.setattr(
        "apps.integrations.payments.stripe.retrieve_payment_method",
        lambda payment_intent_id: {"brand": "visa", "last4": "4242", "funding": "credit"},
    )
    _insert_order("ord_replay_1", "O10003", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_replay_1", "ord_replay_1", "PENDING", {"sessionId": "cs_test_3"})

    event = _checkout_completed_event("ord_replay_1", event_id="evt_replay_1")
    payload = json.dumps(event).encode()
    signature = _sign(payload)
    client = APIClient()

    first = client.post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=signature,
    )
    second = client.post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=_sign(payload, timestamp=int(time.time())),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert activity_count(entity_id="ord_replay_1", action="PAYMENT_PAID") == 1
    order = Order.objects.get(pk="ord_replay_1")
    assert order.status == "OPEN"
    assert order.payment_status == "PAID"


@pytest.mark.django_db
def test_async_payment_failed_marks_order_and_payment_failed():
    _insert_order("ord_failed_1", "O10004", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_failed_1", "ord_failed_1", "PENDING", {"sessionId": "cs_test_4"})

    event = _checkout_completed_event("ord_failed_1")
    event["type"] = "checkout.session.async_payment_failed"
    payload = json.dumps(event).encode()

    response = APIClient().post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=_sign(payload),
    )

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_failed_1")
    assert order.payment_status == "FAILED"
    payment = Payment.objects.get(pk="pay_failed_1")
    assert payment.status == "FAILED"


@pytest.mark.django_db
def test_client_reference_id_fallback_used_when_metadata_order_id_missing(monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.payments.stripe.retrieve_payment_method", lambda payment_intent_id: None
    )
    _insert_order("ord_fallback_1", "O10005", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_fallback_1", "ord_fallback_1", "PENDING", {"sessionId": "cs_test_5"})

    event = _checkout_completed_event("ord_fallback_1")
    event["data"]["object"]["metadata"] = {}
    payload = json.dumps(event).encode()

    response = APIClient().post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=_sign(payload),
    )

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_fallback_1")
    assert order.payment_status == "PAID"
