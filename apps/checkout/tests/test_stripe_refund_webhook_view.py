"""Eventos de reembolso en `POST /api/webhooks/stripe/`: `refund.created`,
`refund.updated`, `refund.failed` y `charge.refunded`.

La firma se verifica con el adaptador real (HMAC local, sin red). Ningún
evento de reembolso debe llamar a la API de Stripe, así que
`create_refund` y `retrieve_payment_method` se parchean para que lancen.
Reglas que se assertean a propósito: la sincronización es idempotente por
`stripe_refund_id`, un reembolso nuestro se reconoce por `metadata.refund_id`
aunque todavía no se haya guardado su id de Stripe, y un `pending` atrasado
no pisa un estado final.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.checkout.models import Order, Payment, Refund
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


def _paid_order(order_id="ord_w1", amount="100.00", payment_intent="pi_w1"):
    order = Order.objects.create(
        id=order_id,
        number=f"N-{order_id}",
        status="OPEN",
        payment_status="PAID",
        data={"payment": {"provider": "stripe", "paymentIntent": payment_intent}},
    )
    payment = Payment.objects.create(
        id=f"PAY_{order_id}",
        order=order,
        provider="stripe",
        provider_id=f"cs_{order_id}",
        status="PAID",
        amount=Decimal(amount),
        data={"sessionId": f"cs_{order_id}", "payment_intent": payment_intent},
    )
    return order, payment


def _refund_event(
    event_type="refund.created",
    refund_id="re_dash_1",
    amount=4000,
    status="succeeded",
    payment_intent="pi_w1",
    metadata=None,
):
    return {
        "id": f"evt_{refund_id}_{status}",
        "type": event_type,
        "data": {
            "object": {
                "id": refund_id,
                "object": "refund",
                "amount": amount,
                "status": status,
                "payment_intent": payment_intent,
                "charge": "ch_w1",
                "reason": "requested_by_customer",
                "metadata": metadata or {},
            }
        },
    }


@pytest.fixture(autouse=True)
def _webhook_setup(settings, monkeypatch):
    settings.STRIPE_WEBHOOK_SECRET = WEBHOOK_SECRET
    settings.STRIPE_SECRET_KEY = ""

    def _boom(*args, **kwargs):
        raise AssertionError("Refund events must not call Stripe")

    monkeypatch.setattr("apps.integrations.payments.stripe.create_refund", _boom)
    monkeypatch.setattr("apps.integrations.payments.stripe.retrieve_payment_method", _boom)


@pytest.mark.django_db
def test_refund_created_in_the_dashboard_is_recorded_as_a_stripe_refund():
    _paid_order()

    response = _post_event(_refund_event())

    assert response.status_code == 200
    refund = Refund.objects.get()
    assert refund.stripe_refund_id == "re_dash_1"
    assert refund.payment_id == "PAY_ord_w1"
    assert refund.amount == Decimal("40.00")
    assert refund.status == "SUCCEEDED"
    assert refund.created_by == "stripe"
    assert Order.objects.get(pk="ord_w1").payment_status == "PARTIALLY_REFUNDED"
    assert Payment.objects.get(pk="PAY_ord_w1").status == "PARTIALLY_REFUNDED"
    assert activity_count(action="REFUND_CREATED", actor_id="stripe", entity_id="ord_w1") == 1


@pytest.mark.django_db
def test_a_repeated_refund_event_does_not_duplicate_the_refund():
    _paid_order()
    event = _refund_event()

    assert _post_event(event).status_code == 200
    assert _post_event(event).status_code == 200
    updated = _refund_event(event_type="refund.updated")
    assert _post_event(updated).status_code == 200

    assert Refund.objects.count() == 1
    assert activity_count(action="REFUND_CREATED", entity_id="ord_w1") == 1
    assert Order.objects.get(pk="ord_w1").payment_status == "PARTIALLY_REFUNDED"


@pytest.mark.django_db
def test_refund_updated_to_succeeded_completes_a_pending_refund():
    _, payment = _paid_order()
    Refund.objects.create(
        id="RFD_PENDING",
        payment=payment,
        amount=Decimal("100.00"),
        status="PENDING",
        stripe_refund_id="re_ours_1",
        created_by="staff@example.com",
    )

    response = _post_event(
        _refund_event(event_type="refund.updated", refund_id="re_ours_1", amount=10000)
    )

    assert response.status_code == 200
    assert Refund.objects.get(pk="RFD_PENDING").status == "SUCCEEDED"
    assert Refund.objects.count() == 1
    assert Order.objects.get(pk="ord_w1").payment_status == "REFUNDED"
    assert activity_count(action="REFUND_SUCCEEDED", entity_id="ord_w1") == 1


@pytest.mark.django_db
def test_our_refund_is_matched_by_metadata_before_its_stripe_id_is_saved():
    _, payment = _paid_order()
    Refund.objects.create(
        id="RFD_OURS",
        payment=payment,
        amount=Decimal("25.00"),
        status="PENDING",
        created_by="staff@example.com",
    )

    response = _post_event(
        _refund_event(refund_id="re_ours_2", amount=2500, metadata={"refund_id": "RFD_OURS"})
    )

    assert response.status_code == 200
    refund = Refund.objects.get()
    assert refund.pk == "RFD_OURS"
    assert refund.stripe_refund_id == "re_ours_2"
    assert refund.status == "SUCCEEDED"
    assert refund.created_by == "staff@example.com"
    assert activity_count(action="REFUND_CREATED", entity_id="ord_w1") == 0


@pytest.mark.django_db
def test_refund_failed_gives_the_balance_back():
    order, payment = _paid_order()
    order.payment_status = "REFUNDED"
    order.save(update_fields=["payment_status"])
    payment.status = "REFUNDED"
    payment.save(update_fields=["status"])
    Refund.objects.create(
        id="RFD_DONE",
        payment=payment,
        amount=Decimal("100.00"),
        status="SUCCEEDED",
        stripe_refund_id="re_fail_1",
        created_by="staff@example.com",
    )

    response = _post_event(
        _refund_event(
            event_type="refund.failed", refund_id="re_fail_1", amount=10000, status="failed"
        )
    )

    assert response.status_code == 200
    assert Refund.objects.get(pk="RFD_DONE").status == "FAILED"
    assert Order.objects.get(pk="ord_w1").payment_status == "PAID"
    assert Payment.objects.get(pk="PAY_ord_w1").status == "PAID"
    assert activity_count(action="REFUND_FAILED", actor_id="stripe", entity_id="ord_w1") == 1


@pytest.mark.django_db
def test_a_late_pending_event_does_not_undo_a_succeeded_refund():
    _paid_order()
    assert _post_event(_refund_event(refund_id="re_late", amount=10000)).status_code == 200

    late = _refund_event(
        event_type="refund.updated", refund_id="re_late", amount=10000, status="pending"
    )
    assert _post_event(late).status_code == 200

    assert Refund.objects.get().status == "SUCCEEDED"
    assert Order.objects.get(pk="ord_w1").payment_status == "REFUNDED"


@pytest.mark.django_db
def test_refund_of_an_unknown_payment_intent_is_ignored_with_200():
    _paid_order()

    response = _post_event(_refund_event(payment_intent="pi_someone_else"))

    assert response.status_code == 200
    assert not Refund.objects.exists()
    assert Order.objects.get(pk="ord_w1").payment_status == "PAID"


@pytest.mark.django_db
def test_charge_refunded_syncs_the_refunds_it_carries():
    _paid_order()
    event = {
        "id": "evt_charge_refunded",
        "type": "charge.refunded",
        "data": {
            "object": {
                "id": "ch_w1",
                "object": "charge",
                "payment_intent": "pi_w1",
                "amount_refunded": 10000,
                "refunds": {
                    "object": "list",
                    "data": [
                        {"id": "re_c1", "amount": 6000, "status": "succeeded", "metadata": {}},
                        {"id": "re_c2", "amount": 4000, "status": "succeeded", "metadata": {}},
                    ],
                },
            }
        },
    }

    assert _post_event(event).status_code == 200
    assert _post_event(event).status_code == 200

    assert set(Refund.objects.values_list("stripe_refund_id", flat=True)) == {"re_c1", "re_c2"}
    assert Order.objects.get(pk="ord_w1").payment_status == "REFUNDED"


@pytest.mark.django_db
def test_charge_refunded_without_the_refund_list_changes_nothing():
    # Desde la API 2022-11-15 la lista `refunds` no viene en el evento; los
    # eventos `refund.*` son los que sincronizan.
    _paid_order()
    event = {
        "id": "evt_charge_refunded_2",
        "type": "charge.refunded",
        "data": {"object": {"id": "ch_w1", "payment_intent": "pi_w1", "amount_refunded": 5000}},
    }

    assert _post_event(event).status_code == 200
    assert not Refund.objects.exists()
    assert Order.objects.get(pk="ord_w1").payment_status == "PAID"


@pytest.mark.django_db
def test_a_replayed_checkout_event_does_not_mark_a_refunded_order_paid_again():
    order, payment = _paid_order()
    order.payment_status = "REFUNDED"
    order.save(update_fields=["payment_status"])
    payment.status = "REFUNDED"
    payment.amount = Decimal("239.99")
    payment.save(update_fields=["status", "amount"])
    event = {
        "id": "evt_replay",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_ord_w1",
                "payment_intent": "pi_w1",
                "payment_status": "paid",
                "amount_total": 23999,
                "client_reference_id": "ord_w1",
                "metadata": {"order_id": "ord_w1"},
            }
        },
    }

    assert _post_event(event).status_code == 200

    assert Order.objects.get(pk="ord_w1").payment_status == "REFUNDED"
    assert Payment.objects.get(pk="PAY_ord_w1").status == "REFUNDED"
    assert activity_count(action="PAYMENT_PAID", entity_id="ord_w1") == 0
