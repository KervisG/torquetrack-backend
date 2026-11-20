"""`POST /api/admin/orders/<order_id>/refunds/` y los reembolsos en el
listado del panel (`GET /api/admin/orders/`).

Se parchean las funciones del adaptador `apps.integrations.payments.authorize_net`
(`get_transaction`, `void_transaction`, `refund_transaction`), nunca
`requests`. Un tests por regla: el comportamiento previo del panel
(permiso, validación, saldo, fallo de la pasarela) y la regla nueva de
Authorize.net (sin liquidar → void solo por el total; liquidada → refund).
"""
from decimal import Decimal

import pytest

from apps.checkout.models import Order, Payment, Refund
from apps.integrations.exceptions import ProviderError
from tests.factories import activity_count, create_staff_user, session_client

ADAPTER = "apps.integrations.payments.authorize_net"
PROVIDER_FAILED = "Payment provider request failed; see server logs."
PARTIAL_BEFORE_SETTLEMENT = (
    "This payment has not settled yet, so it can only be voided for the full amount. "
    "Partial refunds are available once it settles (usually within 24 hours)."
)


def _staff_client(user_id="usr_refunder", permissions=("payments.refund",)):
    create_staff_user(user_id, permissions=list(permissions))
    client, _ = session_client(user_id)
    return client


def _paid_order(order_id="ord_r1", amount="100.00", payment_status="PAID"):
    order = Order.objects.create(
        id=order_id,
        number=f"N-{order_id}",
        status="OPEN",
        payment_status=payment_status,
        data={
            "totals": {"total": float(amount)},
            "payment": {"provider": "authorize_net", "transactionId": "60001"},
        },
    )
    Payment.objects.create(
        id=f"PAY_{order_id}",
        order=order,
        provider="authorize_net",
        provider_id="60001",
        status="PAID" if payment_status != "UNPAID" else "PENDING",
        amount=Decimal(amount),
        data={"transactionId": "60001", "last4": "1111"},
    )
    return order


def _gateway(monkeypatch, status="settledSuccessfully", approved=True):
    """Pasarela falsa: registra cada llamada de void y refund."""
    calls = []
    monkeypatch.setattr(
        f"{ADAPTER}.get_transaction",
        lambda trans_id: {"id": trans_id, "status": status, "last4": "1111"},
    )

    def _void(trans_id):
        calls.append(("void", trans_id))
        return {"id": trans_id, "approved": approved}

    def _refund(*, trans_id, amount, last4, invoice_number):
        calls.append(("refund", trans_id, amount, last4, invoice_number))
        return {"id": f"7000{len(calls)}", "approved": approved}

    monkeypatch.setattr(f"{ADAPTER}.void_transaction", _void)
    monkeypatch.setattr(f"{ADAPTER}.refund_transaction", _refund)
    return calls


def _refund(client, order_id="ord_r1", body=None):
    return client.post(f"/api/admin/orders/{order_id}/refunds/", body or {}, format="json")


# --- comportamiento previo del panel -------------------------------------


@pytest.mark.django_db
def test_refund_requires_payments_refund_permission(monkeypatch):
    calls = _gateway(monkeypatch)
    _paid_order()

    response = _refund(_staff_client(permissions=("orders.view",)))

    assert response.status_code == 403
    assert calls == []
    assert not Refund.objects.exists()


@pytest.mark.django_db
def test_refund_validates_the_amount_and_the_balance(monkeypatch):
    calls = _gateway(monkeypatch)
    _paid_order()
    client = _staff_client()

    invalid = _refund(client, body={"amount": "abc"})
    above = _refund(client, body={"amount": 150})

    assert invalid.status_code == 400
    assert invalid.json() == {
        "error": "Refund amount must be a positive number with at most two decimals"
    }
    assert above.status_code == 400
    assert above.json() == {"error": "Refund amount exceeds the refundable balance of $100.00"}
    assert calls == []
    assert not Refund.objects.exists()


@pytest.mark.django_db
def test_refund_of_an_unpaid_order_is_409(monkeypatch):
    calls = _gateway(monkeypatch)
    _paid_order(payment_status="UNPAID")

    response = _refund(_staff_client())

    assert response.status_code == 409
    assert response.json() == {"error": "Only paid orders can be refunded"}
    assert calls == []


@pytest.mark.django_db
def test_provider_failure_marks_the_refund_failed_and_hides_the_provider_text(monkeypatch):
    _gateway(monkeypatch)

    def _raise(**kwargs):
        raise ProviderError("54: internal detail")

    monkeypatch.setattr(f"{ADAPTER}.refund_transaction", _raise)
    _paid_order()

    response = _refund(_staff_client(), body={"amount": 10})

    assert response.status_code == 502
    assert response.json() == {"error": PROVIDER_FAILED}
    assert Refund.objects.get().status == "FAILED"
    assert Order.objects.get().payment_status == "PAID"
    assert activity_count(action="REFUND_FAILED", entity_id="ord_r1") == 1


# --- reglas de Authorize.net ----------------------------------------------


@pytest.mark.django_db
def test_settled_payment_is_refunded_partially_with_the_card_last4(monkeypatch):
    calls = _gateway(monkeypatch, status="settledSuccessfully")
    _paid_order()

    response = _refund(_staff_client(), body={"amount": 30, "reason": "Damaged box"})

    assert response.status_code == 201
    refund = Refund.objects.get()
    assert calls == [("refund", "60001", Decimal("30.00"), "1111", refund.pk)]
    assert refund.status == "SUCCEEDED"
    assert refund.provider_refund_id == "70001"
    assert Order.objects.get().payment_status == "PARTIALLY_REFUNDED"
    assert activity_count(action="REFUND_CREATED", entity_id="ord_r1") == 1


@pytest.mark.django_db
def test_unsettled_payment_is_voided_for_the_full_amount(monkeypatch):
    calls = _gateway(monkeypatch, status="capturedPendingSettlement")
    _paid_order()

    response = _refund(_staff_client())

    assert response.status_code == 201
    assert calls == [("void", "60001")]
    refund = Refund.objects.get()
    assert refund.amount == Decimal("100.00")
    assert refund.provider_refund_id == "VOID-60001"
    assert Order.objects.get().payment_status == "REFUNDED"


@pytest.mark.django_db
def test_unsettled_payment_rejects_a_partial_refund(monkeypatch):
    calls = _gateway(monkeypatch, status="capturedPendingSettlement")
    _paid_order()

    response = _refund(_staff_client(), body={"amount": 30})

    assert response.status_code == 409
    assert response.json() == {"error": PARTIAL_BEFORE_SETTLEMENT}
    assert calls == []
    assert not Refund.objects.exists()


@pytest.mark.django_db
def test_declined_refund_is_failed_and_gives_the_balance_back(monkeypatch):
    _gateway(monkeypatch, approved=False)
    _paid_order()

    response = _refund(_staff_client(), body={"amount": 30})

    assert response.status_code == 502
    assert response.json() == {"error": "The payment provider declined the refund"}
    assert Refund.objects.get().status == "FAILED"
    assert Order.objects.get().payment_status == "PAID"


@pytest.mark.django_db
def test_order_list_hides_the_provider_refund_id_without_permission(monkeypatch):
    _gateway(monkeypatch)
    _paid_order()
    assert _refund(_staff_client(), body={"amount": 30}).status_code == 201
    create_staff_user("usr_viewer", permissions=["orders.view"])
    viewer, _ = session_client("usr_viewer")

    order = viewer.get("/api/admin/orders/").json()[0]

    assert order["amountRefunded"] == 30.0
    assert order["refundableAmount"] == 70.0
    assert "providerRefundId" not in order["refunds"][0]
    assert "transactionId" not in order["payment"]
