"""Avisos de fraude en `POST /api/webhooks/stripe/`:
`radar.early_fraud_warning.created` y `charge.dispute.created`.

La firma se verifica con el adaptador real (HMAC local, sin red). Ningún aviso
llama a la API de Stripe ni reembolsa solo: el pedido queda marcado y la
bitácora avisa al staff, que decide si reembolsa antes del contracargo. Los dos
eventos son idempotentes por el id del aviso o de la disputa.
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


def _sign(payload: bytes) -> str:
    ts = int(time.time())
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return f"t={ts},v1={signature}"


def _post_event(event):
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

    def _no_network(*args, **kwargs):
        raise AssertionError("A fraud notice must not call Stripe")

    monkeypatch.setattr("apps.integrations.payments.stripe.create_refund", _no_network)
    monkeypatch.setattr("apps.integrations.payments.stripe.retrieve_payment_method", _no_network)


def _paid_order(order_id="ord_f1", payment_intent="pi_f1"):
    order = Order.objects.create(
        id=order_id,
        number=f"N-{order_id}",
        status="OPEN",
        payment_status="PAID",
        data={"payment": {"provider": "stripe", "paymentIntent": payment_intent}},
    )
    Payment.objects.create(
        id=f"PAY_{order_id}",
        order=order,
        provider="stripe",
        provider_id=f"cs_{order_id}",
        status="PAID",
        amount=Decimal("250.00"),
        data={"sessionId": f"cs_{order_id}", "payment_intent": payment_intent},
    )
    return order


def _warning_event(warning_id="issfr_1", payment_intent="pi_f1"):
    return {
        "id": f"evt_{warning_id}",
        "type": "radar.early_fraud_warning.created",
        "data": {
            "object": {
                "id": warning_id,
                "object": "radar.early_fraud_warning",
                "actionable": True,
                "charge": "ch_f1",
                "fraud_type": "made_with_stolen_card",
                "payment_intent": payment_intent,
            }
        },
    }


def _dispute_event(dispute_id="dp_1", payment_intent="pi_f1"):
    return {
        "id": f"evt_{dispute_id}",
        "type": "charge.dispute.created",
        "data": {
            "object": {
                "id": dispute_id,
                "object": "dispute",
                "amount": 25000,
                "charge": "ch_f1",
                "payment_intent": payment_intent,
                "reason": "fraudulent",
                "status": "needs_response",
                "evidence_details": {"due_by": 1767225600},
            }
        },
    }


@pytest.mark.django_db
def test_early_fraud_warning_flags_the_order_and_logs_it():
    order = _paid_order()

    response = _post_event(_warning_event())

    assert response.status_code == 200
    order.refresh_from_db()
    warning = order.data["fraudWarning"]
    assert warning["id"] == "issfr_1"
    assert warning["fraudType"] == "made_with_stolen_card"
    assert warning["actionable"] is True
    assert warning["chargeId"] == "ch_f1"
    assert "receivedAt" in warning
    # El cobro sigue tal cual: reembolsar es decisión del staff.
    assert order.payment_status == "PAID"
    assert order.data["payment"]["paymentIntent"] == "pi_f1"
    assert activity_count(entity_id="ord_f1", action="FRAUD_WARNING_RECEIVED") == 1


@pytest.mark.django_db
def test_a_resent_fraud_warning_is_recorded_once():
    _paid_order()

    _post_event(_warning_event())
    _post_event(_warning_event())

    assert activity_count(entity_id="ord_f1", action="FRAUD_WARNING_RECEIVED") == 1


@pytest.mark.django_db
def test_dispute_flags_the_order_and_logs_it():
    order = _paid_order()

    response = _post_event(_dispute_event())

    assert response.status_code == 200
    order.refresh_from_db()
    dispute = order.data["dispute"]
    assert dispute["id"] == "dp_1"
    assert dispute["reason"] == "fraudulent"
    assert dispute["amount"] == 250.0
    assert dispute["chargeId"] == "ch_f1"
    assert dispute["evidenceDueBy"] == "2026-01-01T00:00:00+00:00"
    assert "openedAt" in dispute
    assert activity_count(entity_id="ord_f1", action="DISPUTE_OPENED") == 1


@pytest.mark.django_db
def test_a_resent_dispute_is_recorded_once():
    _paid_order()

    _post_event(_dispute_event())
    _post_event(_dispute_event())

    assert activity_count(entity_id="ord_f1", action="DISPUTE_OPENED") == 1


@pytest.mark.django_db
@pytest.mark.parametrize("event", [_warning_event, _dispute_event])
def test_a_notice_for_an_unknown_payment_is_acknowledged_and_ignored(event):
    order = _paid_order()

    response = _post_event(event(payment_intent="pi_someone_else"))

    assert response.status_code == 200
    order.refresh_from_db()
    assert "fraudWarning" not in order.data
    assert "dispute" not in order.data
