"""La firma se verifica con el adaptador real (HMAC local, sin red); solo se
parchea `retrieve_payment_method`, que llamaría a la API de Stripe."""
import hashlib
import hmac
import json
import threading
import time
from decimal import Decimal

import pytest
from django.db import connections
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
        provider_id=data.get("sessionId"),
        status=status,
        amount=Decimal("239.99"),
        data=data,
    )


def _checkout_completed_event(
    order_id, event_id="evt_test_1", payment_intent="pi_test_1", session_id="cs_test_1"
):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
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
    settings.STRIPE_SECRET_KEY = ""  # sin key no se consulta la tarjeta
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

    payload = json.dumps(_checkout_completed_event("ord_core_1", session_id="cs_test_2")).encode()
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
    """Stripe reenvía eventos: una segunda entrega no duplica la bitácora ni
    vuelve a conciliar el pago."""
    monkeypatch.setattr(
        "apps.integrations.payments.stripe.retrieve_payment_method",
        lambda payment_intent_id: {"brand": "visa", "last4": "4242", "funding": "credit"},
    )
    _insert_order("ord_replay_1", "O10003", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_replay_1", "ord_replay_1", "PENDING", {"sessionId": "cs_test_3"})

    event = _checkout_completed_event(
        "ord_replay_1", event_id="evt_replay_1", session_id="cs_test_3"
    )
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

    event = _checkout_completed_event("ord_failed_1", session_id="cs_test_4")
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

    event = _checkout_completed_event("ord_fallback_1", session_id="cs_test_5")
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


def _post_event(event):
    payload = json.dumps(event).encode()
    return APIClient().post(
        "/api/webhooks/stripe/",
        data=payload,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=_sign(payload),
    )


def _no_card_details(monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.payments.stripe.retrieve_payment_method", lambda payment_intent_id: None
    )


@pytest.mark.django_db
def test_marks_the_payment_of_the_completed_session_not_the_first_pending(monkeypatch):
    # Checkout del cliente y link de pago del staff: dos sesiones abiertas.
    _no_card_details(monkeypatch)
    _insert_order("ord_two_1", "O10010", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_checkout", "ord_two_1", "PENDING", {"sessionId": "cs_checkout"})
    _insert_payment("pay_link", "ord_two_1", "PENDING", {"sessionId": "cs_link"})

    response = _post_event(_checkout_completed_event("ord_two_1", session_id="cs_link"))

    assert response.status_code == 200
    paid = Payment.objects.get(pk="pay_link")
    assert paid.status == "PAID"
    assert paid.provider_id == "cs_link"
    superseded = Payment.objects.get(pk="pay_checkout")
    assert superseded.status == "CANCELLED"
    assert superseded.provider_id == "cs_checkout"
    assert superseded.data["supersededBy"] == "cs_link"
    assert Order.objects.get(pk="ord_two_1").payment_status == "PAID"


@pytest.mark.django_db
def test_unknown_session_is_acknowledged_without_touching_the_order(monkeypatch, caplog):
    _no_card_details(monkeypatch)
    _insert_order("ord_unknown_1", "O10011", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_known", "ord_unknown_1", "PENDING", {"sessionId": "cs_known"})

    response = _post_event(_checkout_completed_event("ord_unknown_1", session_id="cs_forgotten"))

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_unknown_1")
    assert order.payment_status == "UNPAID"
    assert Payment.objects.get(pk="pay_known").status == "PENDING"
    assert activity_count(entity_id="ord_unknown_1", action="PAYMENT_PAID") == 0
    assert "cs_forgotten" in caplog.text


@pytest.mark.django_db
def test_session_of_another_order_is_not_reconciled(monkeypatch):
    _no_card_details(monkeypatch)
    _insert_order("ord_a", "O10012", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_order("ord_b", "O10013", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_b", "ord_b", "PENDING", {"sessionId": "cs_b"})

    response = _post_event(_checkout_completed_event("ord_a", session_id="cs_b"))

    assert response.status_code == 200
    assert Order.objects.get(pk="ord_a").payment_status == "UNPAID"
    assert Order.objects.get(pk="ord_b").payment_status == "UNPAID"
    assert Payment.objects.get(pk="pay_b").status == "PENDING"


@pytest.mark.django_db
def test_second_session_paid_on_an_already_paid_order_is_flagged_for_refund(monkeypatch):
    # El cliente pagó dos sesiones: el cobro existe en Stripe, así que el
    # pago queda PAID y la bitácora avisa al staff en lugar de ignorarlo.
    _no_card_details(monkeypatch)
    _insert_order("ord_dup_1", "O10014", "OPEN", "PAID", {"totals": {"core": 0}})
    _insert_payment("pay_first", "ord_dup_1", "PAID", {"sessionId": "cs_first"})
    _insert_payment("pay_second", "ord_dup_1", "CANCELLED", {"sessionId": "cs_second"})

    response = _post_event(_checkout_completed_event("ord_dup_1", session_id="cs_second"))

    assert response.status_code == 200
    assert Payment.objects.get(pk="pay_second").status == "PAID"
    assert activity_count(entity_id="ord_dup_1", action="PAYMENT_PAID") == 0
    assert activity_count(entity_id="ord_dup_1", action="DUPLICATE_PAYMENT_RECEIVED") == 1


@pytest.mark.django_db
def test_async_payment_failed_only_fails_the_session_payment():
    _insert_order("ord_failed_2", "O10015", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_async", "ord_failed_2", "PENDING", {"sessionId": "cs_async"})
    _insert_payment("pay_other", "ord_failed_2", "PENDING", {"sessionId": "cs_other"})

    event = _checkout_completed_event("ord_failed_2", session_id="cs_async")
    event["type"] = "checkout.session.async_payment_failed"
    response = _post_event(event)

    assert response.status_code == 200
    assert Payment.objects.get(pk="pay_async").status == "FAILED"
    assert Payment.objects.get(pk="pay_other").status == "PENDING"
    assert Order.objects.get(pk="ord_failed_2").payment_status == "FAILED"


@pytest.mark.django_db
def test_async_failure_never_downgrades_a_paid_order():
    _insert_order("ord_paid_2", "O10016", "OPEN", "PAID", {"totals": {"core": 0}})
    _insert_payment("pay_paid", "ord_paid_2", "PAID", {"sessionId": "cs_paid"})
    _insert_payment("pay_late", "ord_paid_2", "PENDING", {"sessionId": "cs_late"})

    event = _checkout_completed_event("ord_paid_2", session_id="cs_late")
    event["type"] = "checkout.session.async_payment_failed"
    _post_event(event)

    assert Order.objects.get(pk="ord_paid_2").payment_status == "PAID"
    assert Payment.objects.get(pk="pay_late").status == "FAILED"


@pytest.mark.django_db(transaction=True)
def test_concurrent_success_events_reconcile_once(monkeypatch):
    """`checkout.session.completed` y `async_payment_succeeded` pueden llegar
    a la vez. La barrera hace que ambos requests pasen la lectura sin
    bloqueo antes de conciliar; el bloqueo de fila deja un solo registro."""
    barrier = threading.Barrier(2, timeout=5)

    def _card(payment_intent_id):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return {"brand": "visa", "last4": "4242", "funding": "credit"}

    monkeypatch.setattr("apps.integrations.payments.stripe.retrieve_payment_method", _card)
    _insert_order("ord_race_1", "O10017", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_race", "ord_race_1", "PENDING", {"sessionId": "cs_race"})

    completed = _checkout_completed_event("ord_race_1", session_id="cs_race")
    succeeded = _checkout_completed_event("ord_race_1", session_id="cs_race", event_id="evt_2")
    succeeded["type"] = "checkout.session.async_payment_succeeded"
    statuses = []

    def _deliver(event):
        try:
            statuses.append(_post_event(event).status_code)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=_deliver, args=(event,)) for event in (completed, succeeded)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert statuses == [200, 200]
    assert activity_count(entity_id="ord_race_1", action="PAYMENT_PAID") == 1
    assert Payment.objects.get(pk="pay_race").status == "PAID"


@pytest.mark.django_db
def test_completed_session_not_yet_paid_leaves_the_order_pending(monkeypatch):
    # Con un medio asíncrono (ACH) `completed` llega con `payment_status`
    # "unpaid": el cobro se confirma después con `async_payment_succeeded`.
    _no_card_details(monkeypatch)
    _insert_order("ord_async_1", "O10020", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_async_1", "ord_async_1", "PENDING", {"sessionId": "cs_async_1"})

    event = _checkout_completed_event("ord_async_1", session_id="cs_async_1")
    event["data"]["object"]["payment_status"] = "unpaid"
    response = _post_event(event)

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_async_1")
    assert order.payment_status == "UNPAID"
    assert order.status == "PENDING_PAYMENT"
    assert Payment.objects.get(pk="pay_async_1").status == "PENDING"
    assert activity_count(entity_id="ord_async_1", action="PAYMENT_PAID") == 0


@pytest.mark.django_db
def test_async_payment_succeeded_marks_the_order_paid_once(monkeypatch):
    _no_card_details(monkeypatch)
    _insert_order("ord_async_2", "O10021", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_async_2", "ord_async_2", "PENDING", {"sessionId": "cs_async_2"})

    completed = _checkout_completed_event("ord_async_2", session_id="cs_async_2")
    completed["data"]["object"]["payment_status"] = "unpaid"
    succeeded = _checkout_completed_event("ord_async_2", session_id="cs_async_2", event_id="evt_s")
    succeeded["type"] = "checkout.session.async_payment_succeeded"

    assert _post_event(completed).status_code == 200
    assert _post_event(succeeded).status_code == 200
    assert _post_event(succeeded).status_code == 200

    order = Order.objects.get(pk="ord_async_2")
    assert order.payment_status == "PAID"
    assert order.status == "OPEN"
    assert Payment.objects.get(pk="pay_async_2").status == "PAID"
    assert activity_count(entity_id="ord_async_2", action="PAYMENT_PAID") == 1


@pytest.mark.django_db
def test_amount_mismatch_is_logged_and_the_order_is_not_marked_paid(monkeypatch):
    _no_card_details(monkeypatch)
    _insert_order("ord_amount_1", "O10022", "PENDING_PAYMENT", "UNPAID", {"totals": {"core": 0}})
    _insert_payment("pay_amount_1", "ord_amount_1", "PENDING", {"sessionId": "cs_amount_1"})

    event = _checkout_completed_event("ord_amount_1", session_id="cs_amount_1")
    event["data"]["object"]["amount_total"] = 100
    response = _post_event(event)

    # 200 para que Stripe no reintente: el desajuste lo revisa el staff.
    assert response.status_code == 200
    order = Order.objects.get(pk="ord_amount_1")
    assert order.payment_status == "UNPAID"
    assert Payment.objects.get(pk="pay_amount_1").status == "PENDING"
    assert activity_count(entity_id="ord_amount_1", action="PAYMENT_PAID") == 0
    assert activity_count(entity_id="ord_amount_1", action="PAYMENT_AMOUNT_MISMATCH") == 1


@pytest.mark.django_db
@pytest.mark.parametrize("closed_status", ["CANCELLED", "REJECTED"])
def test_payment_on_a_closed_order_is_recorded_without_reopening_it(
    monkeypatch, caplog, closed_status
):
    # El cliente pagó una sesión que quedó abierta después de cerrar el
    # pedido: el dinero entró, así que el pago queda cobrado para que el
    # staff lo reembolse, pero el pedido no vuelve a OPEN.
    _no_card_details(monkeypatch)
    _insert_order("ord_closed_1", "O10030", closed_status, "UNPAID", {"totals": {"core": 50}})
    _insert_payment("pay_closed_1", "ord_closed_1", "CANCELLED", {"sessionId": "cs_closed_1"})

    response = _post_event(_checkout_completed_event("ord_closed_1", session_id="cs_closed_1"))

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_closed_1")
    assert order.status == closed_status
    assert order.payment_status == "PAID"
    assert "coreCase" not in order.data
    assert Payment.objects.get(pk="pay_closed_1").status == "PAID"
    assert activity_count(entity_id="ord_closed_1", action="PAYMENT_PAID") == 0
    assert activity_count(entity_id="ord_closed_1", action="PAYMENT_ON_CLOSED_ORDER") == 1
    assert "ord_closed_1" in caplog.text
