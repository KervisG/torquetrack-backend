"""Reembolsos de Stripe: único lugar que pide un reembolso, crea filas
`Refund` (también las que llegan del dashboard por webhook) y recalcula el
estado de reembolso del pago y del pedido.

El reembolso del panel va en dos transacciones cortas con la llamada a Stripe
en el medio, sin bloqueo: la primera valida el saldo y confirma la fila
PENDING (así un segundo clic ya la cuenta), la segunda guarda lo que
respondió Stripe. Si el webhook llega entre las dos, reconoce la fila por
`metadata.refund_id`.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import (
    Order,
    OrderPaymentStatus,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
)
from apps.checkout.services.payments import (
    CHARGED_PAYMENT_STATUSES,
    STRIPE_REQUEST_FAILED,
    lock_order_and_payment,
)
from apps.common.ids import random_id
from apps.common.numbers import CENT, money, to_cents
from apps.integrations.exceptions import ProviderError
from apps.integrations.payments import stripe as stripe_payments

logger = logging.getLogger(__name__)

INVALID_REFUND_AMOUNT = "Refund amount must be a positive number with at most two decimals"
# Los valores de metadata de Stripe tienen tope de 500 caracteres.
MAX_REASON_LENGTH = 500

# Solo desde estos estados del pedido se puede pedir un reembolso.
REFUNDABLE_ORDER_STATUSES = (OrderPaymentStatus.PAID, OrderPaymentStatus.PARTIALLY_REFUNDED)
# Los que retienen saldo: un PENDING todavía puede salir.
HELD_REFUND_STATUSES = (RefundStatus.PENDING, RefundStatus.SUCCEEDED)
FINAL_REFUND_STATUSES = (RefundStatus.SUCCEEDED, RefundStatus.FAILED, RefundStatus.CANCELED)
# `requires_action` espera al cliente: para el saldo es igual que `pending`.
STRIPE_REFUND_STATUSES = {
    "pending": RefundStatus.PENDING,
    "requires_action": RefundStatus.PENDING,
    "succeeded": RefundStatus.SUCCEEDED,
    "failed": RefundStatus.FAILED,
    "canceled": RefundStatus.CANCELED,
}


def serialize_refund(refund: Refund, can_view_transaction_ids: bool) -> dict:
    row = {
        "id": refund.pk,
        "paymentId": refund.payment_id,
        "amount": money(refund.amount),
        "status": refund.status,
        "reason": refund.reason,
        "createdBy": refund.created_by,
        "createdAt": refund.created_at,
    }
    if can_view_transaction_ids:
        row["stripeRefundId"] = refund.stripe_refund_id
    return row


def _payment_intent(payment: Payment) -> str | None:
    return (payment.data or {}).get("payment_intent")


def charged_payment(order: Order, payments) -> Payment | None:
    """El pago que saldó el pedido: el del PaymentIntent que guardó el
    webhook en `order.data.payment`. Un cobro duplicado del mismo pedido no
    cuenta, así reembolsarlo no cambia el estado del pedido."""
    candidates = [
        payment
        for payment in payments
        if payment.status in CHARGED_PAYMENT_STATUSES and _payment_intent(payment)
    ]
    expected = ((order.data or {}).get("payment") or {}).get("paymentIntent")
    if expected:
        return next((p for p in candidates if _payment_intent(p) == expected), None)
    return candidates[0] if candidates else None


def refundable_balance(payment: Payment, refunds) -> Decimal:
    held = sum(
        (refund.amount for refund in refunds if refund.status in HELD_REFUND_STATUSES),
        Decimal("0"),
    )
    return max(payment.amount - held, Decimal("0"))


def order_refund_summary(order: Order, payments) -> dict:
    """Reembolsos del pedido para el panel, a partir de los pagos ya
    precargados con sus `refunds`."""
    refunds = sorted(
        (refund for payment in payments for refund in payment.refunds.all()),
        key=lambda refund: refund.created_at,
    )
    refunded = sum(
        (refund.amount for refund in refunds if refund.status == RefundStatus.SUCCEEDED),
        Decimal("0"),
    )
    balance = Decimal("0")
    payment = charged_payment(order, payments)
    if payment is not None and order.payment_status in REFUNDABLE_ORDER_STATUSES:
        balance = refundable_balance(payment, payment.refunds.all())
    return {"refunds": refunds, "amountRefunded": refunded, "refundableAmount": balance}


def _charged_status(payment: Payment) -> str:
    refunded = payment.refunds.filter(status=RefundStatus.SUCCEEDED).aggregate(
        total=Sum("amount", default=Decimal("0"))
    )["total"]
    if refunded >= payment.amount:
        return PaymentStatus.REFUNDED
    return PaymentStatus.PARTIALLY_REFUNDED if refunded > 0 else PaymentStatus.PAID


def apply_refund_totals(order: Order, payment: Payment) -> None:
    """Recalcula el estado del pago y, si es el que saldó el pedido, el
    `payment_status` del pedido. Solo cuenta lo reembolsado con éxito. Llamar
    con el pedido y el pago bloqueados. `order.status` no se toca: cerrar un
    pedido reembolsado es una decisión del staff."""
    if payment.status not in CHARGED_PAYMENT_STATUSES:
        return
    status = _charged_status(payment)
    now = timezone.now()
    if payment.status != status:
        payment.status = status
        payment.updated_at = now
        payment.save(update_fields=["status", "updated_at"])
    primary = charged_payment(order, [payment])
    if (
        primary is not None
        and order.payment_status in CHARGED_PAYMENT_STATUSES
        and order.payment_status != status
    ):
        order.payment_status = status
        order.updated_at = now
        order.save(update_fields=["payment_status", "updated_at"])


def _parse_amount(value) -> Decimal | None:
    """`Decimal` positivo con hasta dos decimales, o `None`. `bool` es un
    `int` en Python y no es un monto."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(CENT):
        return None
    return amount.quantize(CENT)


def _parse_reason(value) -> tuple[str | None, str | None]:
    """`(reason, error)`."""
    if value is None:
        return "", None
    if not isinstance(value, str):
        return None, "Refund reason must be text"
    reason = value.strip()
    if len(reason) > MAX_REASON_LENGTH:
        return None, f"Refund reason must be {MAX_REASON_LENGTH} characters or fewer"
    return reason, None


def _activity(refund: Refund, order: Order, **extra) -> dict:
    return {
        "number": order.number,
        "refundId": refund.pk,
        "paymentId": refund.payment_id,
        "amount": money(refund.amount),
        "status": refund.status,
        "stripeRefundId": refund.stripe_refund_id,
        **extra,
    }


def _open_refund(order_id: str, body: dict, actor_email: str) -> tuple[dict | None, tuple | None]:
    """Primera transacción: `(error, None)` o `(None, (order, payment, refund))`."""
    reason, error = _parse_reason(body.get("reason"))
    if error:
        return {"error": error}, None
    requested = None
    if body.get("amount") is not None:
        requested = _parse_amount(body["amount"])
        if requested is None:
            return {"error": INVALID_REFUND_AMOUNT, "status": 400}, None

    with transaction.atomic():
        order = Order.objects.select_for_update().filter(pk=order_id).first()
        if order is None:
            return {"error": "Order not found", "status": 404}, None
        if order.payment_status not in REFUNDABLE_ORDER_STATUSES:
            return {"error": "Only paid orders can be refunded", "status": 409}, None
        payments = list(
            Payment.objects.select_for_update()
            .filter(order=order, provider="stripe")
            .order_by("created_at")
        )
        payment = charged_payment(order, payments)
        if payment is None:
            return {"error": "Order has no Stripe charge to refund", "status": 409}, None

        balance = refundable_balance(payment, payment.refunds.all())
        if balance <= 0:
            return {"error": "Order has no refundable balance", "status": 409}, None
        amount = balance if requested is None else requested
        if amount > balance:
            return {
                "error": f"Refund amount exceeds the refundable balance of ${balance:.2f}",
                "status": 400,
            }, None

        refund = Refund.objects.create(
            id=random_id("RFD"),
            payment=payment,
            amount=amount,
            status=RefundStatus.PENDING,
            reason=reason,
            created_by=actor_email,
            data={"source": "ADMIN_PANEL"},
        )
    return None, (order, payment, refund)


def refund_order(
    order_id: str,
    body: dict,
    actor_email: str,
    *,
    can_view_transaction_ids: bool = False,
) -> tuple[dict, int]:
    """`POST /api/admin/orders/<id>/refunds/`. Sin `amount` reembolsa el
    saldo. El saldo es lo cobrado menos los reembolsos PENDING y SUCCEEDED."""
    error, opened = _open_refund(order_id, body, actor_email)
    if error:
        return {"error": error["error"]}, error.get("status", 400)
    order, payment, refund = opened

    try:
        result = stripe_payments.create_refund(
            payment_intent=_payment_intent(payment),
            amount_cents=to_cents(refund.amount),
            idempotency_key=refund.pk,
            metadata={"refund_id": refund.pk, "order_id": order.pk, "order_number": order.number},
        )
    except ProviderError as exc:
        logger.warning("Stripe refund %s for order %s failed: %s", refund.pk, order.pk, exc)
        return _fail_refund(refund), 502

    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        # El webhook pudo llegar antes y ya dejarla en su estado final.
        if refund.stripe_refund_id is None:
            refund.stripe_refund_id = result["id"]
        if refund.status == RefundStatus.PENDING:
            refund.status = STRIPE_REFUND_STATUSES.get(result.get("status"), RefundStatus.PENDING)
        refund.updated_at = timezone.now()
        refund.save(update_fields=["stripe_refund_id", "status", "updated_at"])
        if order is not None:
            apply_refund_totals(order, payment)

    record_activity(
        actor=actor_email,
        action="REFUND_CREATED",
        entity_type="ORDER",
        entity_id=order_id,
        data=_activity(refund, order),
    )
    return serialize_refund(refund, can_view_transaction_ids), 201


def _fail_refund(refund: Refund) -> dict:
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        # Un timeout no dice si Stripe lo creó: si el webhook ya lo trajo,
        # manda lo que dijo Stripe.
        if refund.status == RefundStatus.PENDING and refund.stripe_refund_id is None:
            refund.status = RefundStatus.FAILED
            refund.updated_at = timezone.now()
            refund.save(update_fields=["status", "updated_at"])
    order = refund.payment.order
    record_activity(
        actor=refund.created_by,
        action="REFUND_FAILED",
        entity_type="ORDER",
        entity_id=order.pk if order else None,
        data=_activity(refund, order) if order else {"refundId": refund.pk},
    )
    return {"error": STRIPE_REQUEST_FAILED}


def _stripe_amount(refund_obj: dict) -> Decimal | None:
    cents = refund_obj.get("amount")
    if isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0:
        return None
    return (Decimal(cents) / 100).quantize(CENT)


def _find_refund(payment: Payment, refund_obj: dict) -> Refund | None:
    refund = Refund.objects.select_for_update().filter(stripe_refund_id=refund_obj["id"]).first()
    if refund is not None:
        return refund
    local_id = (refund_obj.get("metadata") or {}).get("refund_id")
    if not local_id:
        return None
    return (
        Refund.objects.select_for_update()
        .filter(pk=local_id, payment=payment, stripe_refund_id__isnull=True)
        .first()
    )


def sync_stripe_refund(order: Order, payment: Payment, refund_obj: dict) -> None:
    """Crea o actualiza la fila del reembolso de Stripe y recalcula los
    totales. Llamar con el pedido y el pago bloqueados (webhook).

    Un `pending` atrasado no pisa un estado final que ya informó Stripe; sí
    corrige un FAILED local, que solo significa que nuestra llamada no
    obtuvo respuesta."""
    status = STRIPE_REFUND_STATUSES.get(refund_obj.get("status"))
    amount = _stripe_amount(refund_obj)
    if not refund_obj.get("id") or status is None or amount is None:
        logger.warning("Ignoring malformed Stripe refund %s", refund_obj.get("id"))
        return

    refund = _find_refund(payment, refund_obj)
    now = timezone.now()
    if refund is None:
        refund = Refund.objects.create(
            id=random_id("RFD"),
            payment=payment,
            amount=amount,
            status=status,
            reason=refund_obj.get("reason") or "",
            stripe_refund_id=refund_obj["id"],
            created_by="stripe",
            data={"source": "STRIPE_DASHBOARD"},
        )
        apply_refund_totals(order, payment)
        record_activity(
            actor="stripe",
            action="REFUND_CREATED",
            entity_type="ORDER",
            entity_id=order.pk,
            data=_activity(refund, order),
        )
        return

    reported_by_stripe = refund.stripe_refund_id is not None
    previous = refund.status
    stale = (
        status == RefundStatus.PENDING
        and previous in FINAL_REFUND_STATUSES
        and reported_by_stripe
    )
    refund.stripe_refund_id = refund_obj["id"]
    if not stale:
        refund.status = status
    failure = refund_obj.get("failure_reason")
    if failure:
        refund.data = {**(refund.data or {}), "failureReason": failure}
    refund.updated_at = now
    refund.save(update_fields=["stripe_refund_id", "status", "data", "updated_at"])
    apply_refund_totals(order, payment)

    if refund.status == previous:
        return
    action = {
        RefundStatus.SUCCEEDED: "REFUND_SUCCEEDED",
        RefundStatus.FAILED: "REFUND_FAILED",
        RefundStatus.CANCELED: "REFUND_FAILED",
    }.get(refund.status)
    if action:
        record_activity(
            actor="stripe",
            action=action,
            entity_type="ORDER",
            entity_id=order.pk,
            data=_activity(refund, order, previousStatus=previous),
        )
