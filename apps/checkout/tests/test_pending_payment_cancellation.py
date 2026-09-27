"""La expiración corre en `on_commit`, por eso los tests usan
`django_capture_on_commit_callbacks(execute=True)`: sin commit la sesión de
Stripe nunca se expira."""
import logging

import pytest
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import Order, Payment
from apps.checkout.services import (
    cancel_pending_payment,
    reconcile_paid_session,
    start_stripe_payment,
)
from apps.integrations.exceptions import ProviderError
from apps.quotes.models import Quote
from tests.factories import create_staff_user, session_client

EXPIRE_SESSION = "apps.integrations.payments.stripe.expire_checkout_session"
CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"


@pytest.fixture(autouse=True)
def _stripe(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    settings.RESEND_API_KEY = ""


@pytest.fixture
def expired(monkeypatch):
    """Ids de las sesiones que el dominio mandó expirar, en orden."""
    calls = []

    def _expire(session_id):
        calls.append(session_id)
        return {"id": session_id, "status": "expired", "alreadyClosed": False}

    monkeypatch.setattr(EXPIRE_SESSION, _expire)
    return calls


def _order(order_id="OID_1", number="O40001", **fields):
    return Order.objects.create(
        id=order_id,
        number=number,
        status=fields.pop("status", "PENDING_PAYMENT"),
        payment_status=fields.pop("payment_status", "UNPAID"),
        data=fields.pop("data", {"totals": {"total": 100.0}}),
        **fields,
    )


def _pending(payment_id, order, session_id, provider="stripe"):
    return Payment.objects.create(
        id=payment_id,
        order=order,
        provider=provider,
        provider_id=session_id,
        status="PENDING",
        amount=100,
        data={"sessionId": session_id},
    )


# --- cancel_pending_payment -------------------------------------------------


@pytest.mark.django_db
def test_cancel_marks_the_payment_and_expires_its_session_after_commit(
    expired, django_capture_on_commit_callbacks
):
    payment = _pending("PAY_1", _order(), "cs_open")

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            cancel_pending_payment(payment, "TEST_REASON", data={"by": "test"})
            # Dentro de la transacción la sesión sigue viva.
            assert expired == []

    assert expired == ["cs_open"]
    payment.refresh_from_db()
    assert payment.status == "CANCELLED"
    assert payment.data == {"sessionId": "cs_open", "cancelReason": "TEST_REASON", "by": "test"}


@pytest.mark.django_db
def test_a_rolled_back_cancellation_never_expires_the_session(
    expired, django_capture_on_commit_callbacks
):
    payment = _pending("PAY_1", _order(), "cs_live")

    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                cancel_pending_payment(payment, "TEST_REASON")
                raise RuntimeError("rollback")

    assert expired == []
    assert Payment.objects.get(pk="PAY_1").status == "PENDING"


@pytest.mark.django_db
def test_a_stripe_error_while_expiring_is_logged_and_swallowed(
    monkeypatch, caplog, django_capture_on_commit_callbacks
):
    def _fail(session_id):
        raise ProviderError("Stripe is unreachable")

    monkeypatch.setattr(EXPIRE_SESSION, _fail)
    payment = _pending("PAY_1", _order(), "cs_open")

    with caplog.at_level(logging.WARNING, logger="apps.checkout.services.payments"):
        with django_capture_on_commit_callbacks(execute=True):
            cancel_pending_payment(payment, "TEST_REASON")

    assert Payment.objects.get(pk="PAY_1").status == "CANCELLED"
    assert "cs_open" in caplog.text
    assert "Stripe is unreachable" in caplog.text


@pytest.mark.django_db
def test_a_session_already_completed_is_logged_for_follow_up(
    monkeypatch, caplog, django_capture_on_commit_callbacks
):
    monkeypatch.setattr(
        EXPIRE_SESSION,
        lambda session_id: {"id": session_id, "status": "complete", "alreadyClosed": True},
    )
    payment = _pending("PAY_1", _order(), "cs_paid")

    with caplog.at_level(logging.WARNING, logger="apps.checkout.services.payments"):
        with django_capture_on_commit_callbacks(execute=True):
            cancel_pending_payment(payment, "TEST_REASON")

    assert "cs_paid" in caplog.text
    assert "complete" in caplog.text


@pytest.mark.django_db
def test_a_payment_that_is_no_longer_pending_is_left_alone(
    expired, django_capture_on_commit_callbacks
):
    payment = _pending("PAY_1", _order(), "cs_paid")
    Payment.objects.filter(pk="PAY_1").update(status="PAID")
    payment.refresh_from_db()

    with django_capture_on_commit_callbacks(execute=True):
        cancel_pending_payment(payment, "TEST_REASON")

    assert expired == []
    assert Payment.objects.get(pk="PAY_1").status == "PAID"


@pytest.mark.django_db
def test_a_non_stripe_payment_is_cancelled_without_calling_stripe(
    monkeypatch, django_capture_on_commit_callbacks
):
    def _boom(session_id):
        raise AssertionError("Stripe must not be called for a non-Stripe payment")

    monkeypatch.setattr(EXPIRE_SESSION, _boom)
    payment = _pending("PAY_1", _order(), "cash_1", provider="cash")

    with django_capture_on_commit_callbacks(execute=True):
        cancel_pending_payment(payment, "TEST_REASON")

    assert Payment.objects.get(pk="PAY_1").status == "CANCELLED"


# --- Cada camino que cancela un pago pendiente --------------------------------


@pytest.mark.django_db
def test_webhook_payment_expires_the_other_open_sessions(
    expired, django_capture_on_commit_callbacks
):
    order = _order()
    _pending("PAY_CHECKOUT", order, "cs_checkout")
    _pending("PAY_LINK", order, "cs_link")

    with django_capture_on_commit_callbacks(execute=True):
        reconcile_paid_session(
            {
                "id": "cs_link",
                "metadata": {"order_id": "OID_1"},
                "payment_status": "paid",
                "amount_total": 10000,
            }
        )

    assert expired == ["cs_checkout"]
    superseded = Payment.objects.get(pk="PAY_CHECKOUT")
    assert superseded.status == "CANCELLED"
    assert superseded.data["supersededBy"] == "cs_link"
    assert Payment.objects.get(pk="PAY_LINK").status == "PAID"


@pytest.mark.django_db
def test_a_new_payment_link_expires_the_previous_open_session(
    expired, monkeypatch, django_capture_on_commit_callbacks
):
    order = _order()
    _pending("PAY_OLD", order, "cs_old")
    monkeypatch.setattr(
        CREATE_SESSION, lambda **kwargs: {"id": "cs_new", "url": "https://pay/cs_new"}
    )

    with django_capture_on_commit_callbacks(execute=True):
        payment, _ = start_stripe_payment(order)

    assert expired == ["cs_old"]
    old = Payment.objects.get(pk="PAY_OLD")
    assert old.status == "CANCELLED"
    assert old.data["replacedBy"] == "cs_new"
    assert Payment.objects.get(pk=payment.pk).status == "PENDING"


@pytest.mark.django_db
def test_a_failed_new_session_keeps_the_previous_one_open(
    expired, monkeypatch, django_capture_on_commit_callbacks
):
    order = _order()
    _pending("PAY_OLD", order, "cs_old")

    def _fail(**kwargs):
        raise ProviderError("Stripe is unreachable")

    monkeypatch.setattr(CREATE_SESSION, _fail)

    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(ProviderError):
            start_stripe_payment(order)

    assert expired == []
    assert Payment.objects.get(pk="PAY_OLD").status == "PENDING"


@pytest.mark.django_db
def test_admin_payment_link_succeeds_even_if_expiring_the_old_session_fails(
    monkeypatch, django_capture_on_commit_callbacks
):
    def _fail(session_id):
        raise ProviderError("Stripe is unreachable")

    monkeypatch.setattr(EXPIRE_SESSION, _fail)
    monkeypatch.setattr(
        CREATE_SESSION, lambda **kwargs: {"id": "cs_new", "url": "https://pay/cs_new"}
    )
    create_staff_user("U_LINK", permissions=["payments.take"])
    client, _ = session_client("U_LINK")
    order = _order()
    _pending("PAY_OLD", order, "cs_old")

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post("/api/admin/orders/OID_1/payment-link/")

    assert response.status_code == 200
    assert response.json()["url"] == "https://pay/cs_new"
    assert Payment.objects.get(pk="PAY_OLD").status == "CANCELLED"


@pytest.mark.django_db
def test_quote_checkout_with_changed_totals_expires_the_stale_session(
    expired, monkeypatch, django_capture_on_commit_callbacks
):
    items = [{"productId": "p1", "title": "Pump", "quantity": 1, "unitPrice": 50.0}]
    totals = {"subtotal": 50.0, "core": 0, "shipping": 0, "tax": 0, "total": 50.0}
    Quote.objects.create(
        id="QID_1",
        number="Q40001",
        status="ACTIVE",
        expires_at=timezone.now() + timezone.timedelta(days=30),
        data={"publicToken": "tok_stale", "items": items, "totals": totals},
    )
    stale = _order(
        data={"quoteNumber": "Q40001", "items": items, "totals": {**totals, "total": 1.0}}
    )
    _pending("PAY_STALE", stale, "cs_stale")
    monkeypatch.setattr(
        CREATE_SESSION, lambda **kwargs: {"id": "cs_fresh", "url": "https://pay/cs_fresh"}
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = APIClient().post("/api/quote/public/tok_stale/checkout/")

    assert response.status_code == 200
    assert expired == ["cs_stale"]
    assert Payment.objects.get(pk="PAY_STALE").data["cancelReason"] == "QUOTE_CHANGED"


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["CANCELLED", "REJECTED"])
def test_admin_cancelling_the_order_expires_its_open_sessions(
    expired, django_capture_on_commit_callbacks, status
):
    create_staff_user("U_CANCEL", permissions=["orders.cancel", "orders.status"])
    client, _ = session_client("U_CANCEL")
    _pending("PAY_OPEN", _order(), "cs_open")

    with django_capture_on_commit_callbacks(execute=True):
        response = client.patch("/api/admin/orders/OID_1/", {"status": status}, format="json")

    assert response.status_code == 200
    assert expired == ["cs_open"]
    assert Payment.objects.get(pk="PAY_OPEN").status == "CANCELLED"


@pytest.mark.django_db
def test_admin_status_change_that_keeps_the_order_alive_keeps_its_sessions(
    expired, django_capture_on_commit_callbacks
):
    create_staff_user("U_STATUS", permissions=["orders.status"])
    client, _ = session_client("U_STATUS")
    _pending("PAY_OPEN", _order(), "cs_open")

    with django_capture_on_commit_callbacks(execute=True):
        response = client.patch("/api/admin/orders/OID_1/", {"status": "PROCESSING"}, format="json")

    assert response.status_code == 200
    assert expired == []
    assert Payment.objects.get(pk="PAY_OPEN").status == "PENDING"


@pytest.mark.django_db
def test_admin_deleting_an_unpaid_order_expires_its_open_sessions(
    expired, django_capture_on_commit_callbacks
):
    create_staff_user("U_DELETE", permissions=["orders.cancel"])
    client, _ = session_client("U_DELETE")
    _pending("PAY_OPEN", _order(), "cs_open")

    with django_capture_on_commit_callbacks(execute=True):
        response = client.delete("/api/admin/orders/OID_1/")

    assert response.status_code == 200
    assert expired == ["cs_open"]
    assert not Order.objects.filter(pk="OID_1").exists()
