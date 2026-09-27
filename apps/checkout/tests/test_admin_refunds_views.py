"""`POST /api/admin/orders/<order_id>/refunds/` y los reembolsos en el
listado del panel (`GET /api/admin/orders/`).

Se parchea el adaptador `apps.integrations.payments.stripe.create_refund`,
nunca el SDK. Los caminos que no deben llegar a Stripe lo parchean con una
función que lanza `AssertionError`. Reglas que se assertean a propósito: el
saldo cuenta los reembolsos PENDING, la fila `Refund` existe antes de llamar a
Stripe y su id es la `idempotency_key`, y el texto de Stripe nunca llega al
cliente.
"""
import logging
import threading
from decimal import Decimal

import pytest
from django.db import connections

from apps.checkout.models import Order, Payment, Refund
from apps.integrations.exceptions import ProviderError
from tests.factories import activity_count, create_staff_user, session_client

CREATE_REFUND = "apps.integrations.payments.stripe.create_refund"
STRIPE_REQUEST_FAILED = "Stripe request failed; see server logs."
INVALID_AMOUNT = "Refund amount must be a positive number with at most two decimals"


def _staff_client(user_id="usr_refunder", permissions=("payments.refund",)):
    create_staff_user(user_id, permissions=list(permissions))
    client, _ = session_client(user_id)
    return client


def _paid_order(
    order_id="ord_r1",
    amount="100.00",
    payment_status="PAID",
    payment_intent="pi_r1",
    status="OPEN",
):
    order = Order.objects.create(
        id=order_id,
        number=f"N-{order_id}",
        status=status,
        payment_status=payment_status,
        data={
            "totals": {"total": float(amount)},
            "payment": {"provider": "stripe", "paymentIntent": payment_intent},
        },
    )
    Payment.objects.create(
        id=f"PAY_{order_id}",
        order=order,
        provider="stripe",
        provider_id=f"cs_{order_id}",
        status="PAID" if payment_status != "UNPAID" else "PENDING",
        amount=Decimal(amount),
        data={"sessionId": f"cs_{order_id}", "payment_intent": payment_intent},
    )
    return order


def _fake_stripe(monkeypatch, status="succeeded"):
    """Registra cada llamada y responde como Stripe con un id nuevo."""
    calls = []

    def _create(*, payment_intent, amount_cents, idempotency_key, metadata):
        calls.append(
            {
                "payment_intent": payment_intent,
                "amount_cents": amount_cents,
                "idempotency_key": idempotency_key,
                "metadata": metadata,
                # La fila ya tiene que existir cuando se llama a Stripe.
                "row_exists": Refund.objects.filter(pk=idempotency_key).exists(),
            }
        )
        return {"id": f"re_{len(calls)}", "status": status, "amount": amount_cents}

    monkeypatch.setattr(CREATE_REFUND, _create)
    return calls


def _forbid_stripe(monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("Stripe must not be called")

    monkeypatch.setattr(CREATE_REFUND, _boom)


def _refund(client, order_id="ord_r1", body=None):
    return client.post(f"/api/admin/orders/{order_id}/refunds/", body or {}, format="json")


# --- permisos y estado del pedido -----------------------------------------


@pytest.mark.django_db
def test_refund_requires_payments_refund_permission(monkeypatch):
    _forbid_stripe(monkeypatch)
    _paid_order()
    client = _staff_client(permissions=("orders.view", "payments.take"))

    response = _refund(client)

    assert response.status_code == 403
    assert not Refund.objects.exists()


@pytest.mark.django_db
def test_refund_of_an_unknown_order_is_404(monkeypatch):
    _forbid_stripe(monkeypatch)
    client = _staff_client()

    response = _refund(client, order_id="ord_missing")

    assert response.status_code == 404
    assert response.json() == {"error": "Order not found"}


@pytest.mark.django_db
@pytest.mark.parametrize("payment_status", ["UNPAID", "FAILED", "REFUNDED"])
def test_refund_of_an_order_without_a_refundable_charge_is_409(monkeypatch, payment_status):
    _forbid_stripe(monkeypatch)
    _paid_order(payment_status=payment_status)
    client = _staff_client()

    response = _refund(client)

    assert response.status_code == 409
    assert response.json() == {"error": "Only paid orders can be refunded"}
    assert not Refund.objects.exists()


@pytest.mark.django_db
def test_refund_of_a_paid_order_without_payment_intent_is_409(monkeypatch):
    _forbid_stripe(monkeypatch)
    _paid_order(payment_intent=None)
    client = _staff_client()

    response = _refund(client)

    assert response.status_code == 409
    assert response.json() == {"error": "Order has no Stripe charge to refund"}


# --- validación del body -------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("amount", [0, -5, "abc", True, 10.005, "NaN", "Infinity", [], {}])
def test_refund_rejects_an_invalid_amount(monkeypatch, amount):
    _forbid_stripe(monkeypatch)
    _paid_order()
    client = _staff_client()

    response = _refund(client, body={"amount": amount})

    assert response.status_code == 400
    assert response.json() == {"error": INVALID_AMOUNT}
    assert not Refund.objects.exists()


@pytest.mark.django_db
def test_refund_rejects_an_amount_above_the_balance(monkeypatch):
    _forbid_stripe(monkeypatch)
    _paid_order()
    client = _staff_client()

    response = _refund(client, body={"amount": 100.01})

    assert response.status_code == 400
    assert response.json() == {
        "error": "Refund amount exceeds the refundable balance of $100.00"
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "reason, error",
    [
        (42, "Refund reason must be text"),
        ("x" * 501, "Refund reason must be 500 characters or fewer"),
    ],
)
def test_refund_rejects_an_invalid_reason(monkeypatch, reason, error):
    _forbid_stripe(monkeypatch)
    _paid_order()
    client = _staff_client()

    response = _refund(client, body={"reason": reason})

    assert response.status_code == 400
    assert response.json() == {"error": error}


# --- camino feliz --------------------------------------------------------


@pytest.mark.django_db
def test_refund_without_amount_refunds_the_whole_balance(monkeypatch):
    calls = _fake_stripe(monkeypatch)
    _paid_order()
    client = _staff_client()

    response = _refund(client, body={"reason": "Customer returned the pump"})

    assert response.status_code == 201
    body = response.json()
    refund = Refund.objects.get()
    assert body == {
        "id": refund.pk,
        "paymentId": "PAY_ord_r1",
        "amount": 100.0,
        "status": "SUCCEEDED",
        "reason": "Customer returned the pump",
        "createdBy": "usr_refunder@example.com",
        "createdAt": body["createdAt"],
    }
    assert refund.stripe_refund_id == "re_1"
    assert refund.amount == Decimal("100.00")
    assert calls == [
        {
            "payment_intent": "pi_r1",
            "amount_cents": 10000,
            "idempotency_key": refund.pk,
            "metadata": {"refund_id": refund.pk, "order_id": "ord_r1", "order_number": "N-ord_r1"},
            "row_exists": True,
        }
    ]
    order = Order.objects.get(pk="ord_r1")
    assert order.payment_status == "REFUNDED"
    # El estado del pedido no se decide aquí: lo sigue manejando el staff.
    assert order.status == "OPEN"
    assert Payment.objects.get(pk="PAY_ord_r1").status == "REFUNDED"
    assert activity_count(action="REFUND_CREATED", entity_id="ord_r1") == 1


@pytest.mark.django_db
def test_refund_response_shows_the_stripe_id_with_payments_transaction_id(monkeypatch):
    _fake_stripe(monkeypatch)
    _paid_order()
    client = _staff_client(permissions=("payments.refund", "payments.transaction_id"))

    response = _refund(client, body={"amount": "25.50"})

    assert response.status_code == 201
    assert response.json()["stripeRefundId"] == "re_1"
    assert response.json()["amount"] == 25.5


@pytest.mark.django_db
def test_partial_refunds_accumulate_until_the_order_is_refunded(monkeypatch):
    calls = _fake_stripe(monkeypatch)
    _paid_order()
    client = _staff_client()

    first = _refund(client, body={"amount": 30})
    assert first.status_code == 201
    assert Order.objects.get(pk="ord_r1").payment_status == "PARTIALLY_REFUNDED"
    assert Payment.objects.get(pk="PAY_ord_r1").status == "PARTIALLY_REFUNDED"

    over = _refund(client, body={"amount": 70.01})
    assert over.status_code == 400
    assert over.json() == {"error": "Refund amount exceeds the refundable balance of $70.00"}

    rest = _refund(client)
    assert rest.status_code == 201
    assert rest.json()["amount"] == 70.0
    assert Order.objects.get(pk="ord_r1").payment_status == "REFUNDED"

    again = _refund(client)
    assert again.status_code == 409
    assert [call["amount_cents"] for call in calls] == [3000, 7000]
    # Dos filas, dos claves distintas: cada reembolso es su propia operación.
    assert len({call["idempotency_key"] for call in calls}) == 2


@pytest.mark.django_db
def test_a_pending_refund_holds_its_amount_out_of_the_balance(monkeypatch):
    _fake_stripe(monkeypatch, status="pending")
    _paid_order()
    client = _staff_client()

    response = _refund(client, body={"amount": 40})

    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    # Todavía no hay dinero devuelto: el pedido sigue cobrado entero.
    assert Order.objects.get(pk="ord_r1").payment_status == "PAID"

    over = _refund(client, body={"amount": 60.01})
    assert over.status_code == 400
    assert over.json() == {"error": "Refund amount exceeds the refundable balance of $60.00"}


@pytest.mark.django_db
def test_no_balance_left_while_refunds_are_pending_is_409(monkeypatch):
    _fake_stripe(monkeypatch, status="pending")
    _paid_order()
    client = _staff_client()
    assert _refund(client).status_code == 201

    response = _refund(client)

    assert response.status_code == 409
    assert response.json() == {"error": "Order has no refundable balance"}


# --- fallo del proveedor ---------------------------------------------------


@pytest.mark.django_db
def test_provider_failure_marks_the_refund_failed_and_hides_stripe_text(monkeypatch, caplog):
    def _raise(**kwargs):
        raise ProviderError("Charge ch_secret has already been refunded")

    monkeypatch.setattr(CREATE_REFUND, _raise)
    _paid_order()
    client = _staff_client()

    with caplog.at_level(logging.WARNING, logger="apps.checkout.services.refunds"):
        response = _refund(client, body={"amount": 10})

    assert response.status_code == 502
    assert response.json() == {"error": STRIPE_REQUEST_FAILED}
    assert "ch_secret" not in response.content.decode()
    assert "ch_secret" in caplog.text
    refund = Refund.objects.get()
    assert refund.status == "FAILED"
    assert refund.stripe_refund_id is None
    assert Order.objects.get(pk="ord_r1").payment_status == "PAID"
    assert activity_count(action="REFUND_FAILED", entity_id="ord_r1") == 1
    assert activity_count(action="REFUND_CREATED", entity_id="ord_r1") == 0


@pytest.mark.django_db
def test_a_failed_refund_gives_the_balance_back(monkeypatch):
    def _raise(**kwargs):
        raise ProviderError("Stripe is unreachable")

    monkeypatch.setattr(CREATE_REFUND, _raise)
    _paid_order()
    client = _staff_client()
    assert _refund(client).status_code == 502

    _fake_stripe(monkeypatch)
    response = _refund(client)

    assert response.status_code == 201
    assert response.json()["amount"] == 100.0


# --- concurrencia ------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_full_refunds_never_exceed_the_balance(monkeypatch):
    """El primer request queda dentro de Stripe mientras llega el segundo; la
    fila PENDING ya confirmada le quita el saldo y el segundo no llama."""
    barrier = threading.Barrier(2, timeout=2)
    calls = []

    def _slow_create(*, payment_intent, amount_cents, idempotency_key, metadata):
        calls.append(amount_cents)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return {"id": f"re_{len(calls)}", "status": "succeeded", "amount": amount_cents}

    monkeypatch.setattr(CREATE_REFUND, _slow_create)
    _paid_order()
    create_staff_user("usr_race", permissions=["payments.refund"])
    clients = [session_client("usr_race")[0] for _ in range(2)]
    statuses = []

    def _post(client):
        try:
            statuses.append(_refund(client).status_code)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=_post, args=(client,)) for client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert sorted(statuses) == [201, 409]
    assert calls == [10000]
    assert Refund.objects.count() == 1


# --- listado del panel -----------------------------------------------------


@pytest.mark.django_db
def test_order_list_includes_refunds_and_balances(monkeypatch):
    _fake_stripe(monkeypatch)
    _paid_order()
    refunder = _staff_client()
    assert _refund(refunder, body={"amount": 30, "reason": "Damaged box"}).status_code == 201
    create_staff_user("usr_viewer", permissions=["orders.view"])
    viewer, _ = session_client("usr_viewer")

    response = viewer.get("/api/admin/orders/")

    assert response.status_code == 200
    order = response.json()[0]
    assert order["amountRefunded"] == 30.0
    assert order["refundableAmount"] == 70.0
    assert len(order["refunds"]) == 1
    refund = order["refunds"][0]
    assert refund["amount"] == 30.0
    assert refund["status"] == "SUCCEEDED"
    assert refund["reason"] == "Damaged box"
    assert refund["paymentId"] == "PAY_ord_r1"
    # Ver el id de Stripe exige `payments.transaction_id`.
    assert "stripeRefundId" not in refund
    assert "re_1" not in response.content.decode()


@pytest.mark.django_db
def test_order_list_of_an_unpaid_order_has_no_refundable_amount():
    _paid_order(payment_status="UNPAID")
    create_staff_user("usr_viewer", permissions=["orders.view"])
    viewer, _ = session_client("usr_viewer")

    order = viewer.get("/api/admin/orders/").json()[0]

    assert order["refunds"] == []
    assert order["amountRefunded"] == 0.0
    assert order["refundableAmount"] == 0.0
