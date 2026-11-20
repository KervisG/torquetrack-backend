"""Reembolsos con Authorize.net: único lugar que pide un reembolso, crea
filas `Refund` (también las que llegan del Merchant Interface por webhook) y
recalcula el estado de reembolso del pago y del pedido.

Authorize.net no reembolsa una transacción hasta que se liquida (en general
dentro de 24 horas). Antes de eso solo se puede anular (`voidTransaction`), y
una anulación siempre es por el total. Por eso el panel relee la transacción
antes de abrir el reembolso: sin liquidar → void (solo total); liquidada →
refund (total o parcial).

El reembolso del panel va en dos transacciones cortas con la llamada a la
pasarela en el medio, sin bloqueo: la primera valida el saldo y confirma la
fila PENDING (así un segundo clic ya la cuenta), la segunda guarda lo que
respondió Authorize.net. Si el webhook llega entre las dos, reconoce la fila
por el `invoiceNumber` (el id del `Refund`) o, en un void, por el pago.
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
    PAYMENT_REQUEST_FAILED,
    PROVIDER,
    PROVIDER_ACTOR,
    lock_order_and_payment,
    transaction_id,
)
from apps.common.ids import random_id
from apps.common.numbers import CENT, money
from apps.integrations.exceptions import ProviderError
from apps.integrations.payments import authorize_net

logger = logging.getLogger(__name__)

INVALID_REFUND_AMOUNT = "Refund amount must be a positive number with at most two decimals"
PARTIAL_BEFORE_SETTLEMENT = (
    "This payment has not settled yet, so it can only be voided for the full amount. "
    "Partial refunds are available once it settles (usually within 24 hours)."
)
NOT_REFUNDABLE_NOW = "This payment cannot be refunded in its current state"
MAX_REASON_LENGTH = 500

# Solo desde estos estados del pedido se puede pedir un reembolso.
REFUNDABLE_ORDER_STATUSES = (OrderPaymentStatus.PAID, OrderPaymentStatus.PARTIALLY_REFUNDED)
# Los que retienen saldo: un PENDING todavía puede salir.
HELD_REFUND_STATUSES = (RefundStatus.PENDING, RefundStatus.SUCCEEDED)
FINAL_REFUND_STATUSES = (RefundStatus.SUCCEEDED, RefundStatus.FAILED, RefundStatus.CANCELED)

MODE_VOID = "VOID"
MODE_REFUND = "REFUND"
# `transactionStatus` del cobro que decide cómo se devuelve.
UNSETTLED_CHARGE_STATUSES = ("capturedPendingSettlement", "FDSAuthorizedPendingReview")
SETTLED_CHARGE_STATUSES = ("settledSuccessfully",)
# `transactionStatus` de una transacción de reembolso aprobada.
APPROVED_REFUND_STATUSES = ("refundPendingSettlement", "refundSettledSuccessfully")


def void_refund_id(trans_id: str) -> str:
    """Un void no crea transacción nueva: se identifica por el cobro anulado."""
    return f"VOID-{trans_id}"


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
        row["providerRefundId"] = refund.provider_refund_id
    return row


def charged_payment(order: Order, payments) -> Payment | None:
    """El pago que saldó el pedido: el de la transacción que guardó el
    webhook en `order.data.payment`. Un cobro duplicado del mismo pedido no
    cuenta, así reembolsarlo no cambia el estado del pedido."""
    candidates = [
        payment
        for payment in payments
        if payment.status in CHARGED_PAYMENT_STATUSES and transaction_id(payment)
    ]
    expected = ((order.data or {}).get("payment") or {}).get("transactionId")
    if expected:
        return next((p for p in candidates if transaction_id(p) == expected), None)
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
        "providerRefundId": refund.provider_refund_id,
        **extra,
    }


def _provider_payments(order: Order):
    return Payment.objects.filter(order=order, provider=PROVIDER).order_by("created_at")


def _refund_plan(order_id: str) -> tuple[dict | None, dict | None]:
    """Relee el cobro en Authorize.net, sin bloqueo, para saber si se anula o
    se reembolsa. `(error, None)` o `(None, plan)`; `plan` es `None` cuando no
    hay cobro (lo informa `_open_refund` con su error de siempre)."""
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return None, None
    payment = charged_payment(order, list(_provider_payments(order)))
    if payment is None:
        return None, None
    trans_id = transaction_id(payment)
    try:
        details = authorize_net.get_transaction(trans_id)
    except ProviderError as exc:
        logger.warning(
            "Authorize.net lookup of %s for order %s failed: %s", trans_id, order_id, exc
        )
        return {"error": PAYMENT_REQUEST_FAILED, "status": 502}, None
    status = details.get("status")
    if status in UNSETTLED_CHARGE_STATUSES:
        mode = MODE_VOID
    elif status in SETTLED_CHARGE_STATUSES:
        mode = MODE_REFUND
    else:
        logger.warning("Order %s charge %s is %s; not refundable", order_id, trans_id, status)
        return {"error": NOT_REFUNDABLE_NOW, "status": 409}, None
    return None, {
        "paymentId": payment.pk,
        "transactionId": trans_id,
        "mode": mode,
        "last4": details.get("last4") or (payment.data or {}).get("last4"),
    }


def _open_refund(
    order_id: str, body: dict, actor_email: str, plan: dict | None
) -> tuple[dict | None, tuple | None]:
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
        payments = list(_provider_payments(order).select_for_update())
        payment = charged_payment(order, payments)
        if payment is None:
            return {"error": "Order has no card charge to refund", "status": 409}, None
        if plan is None or plan["paymentId"] != payment.pk:
            # Otro evento cambió el cobro entre la lectura y el bloqueo.
            return {"error": NOT_REFUNDABLE_NOW, "status": 409}, None

        balance = refundable_balance(payment, payment.refunds.all())
        if balance <= 0:
            return {"error": "Order has no refundable balance", "status": 409}, None
        amount = balance if requested is None else requested
        if amount > balance:
            return {
                "error": f"Refund amount exceeds the refundable balance of ${balance:.2f}",
                "status": 400,
            }, None
        if plan["mode"] == MODE_VOID and amount != payment.amount:
            return {"error": PARTIAL_BEFORE_SETTLEMENT, "status": 409}, None
        if plan["mode"] == MODE_REFUND and not plan.get("last4"):
            return {"error": NOT_REFUNDABLE_NOW, "status": 409}, None

        refund = Refund.objects.create(
            id=random_id("RFD"),
            payment=payment,
            amount=amount,
            status=RefundStatus.PENDING,
            reason=reason,
            created_by=actor_email,
            data={"source": "ADMIN_PANEL", "mode": plan["mode"]},
        )
    return None, (order, payment, refund)


def _call_provider(plan: dict, refund: Refund) -> tuple[str, bool]:
    """`(provider_refund_id, approved)`; lanza `ProviderError`."""
    if plan["mode"] == MODE_VOID:
        result = authorize_net.void_transaction(plan["transactionId"])
        return void_refund_id(plan["transactionId"]), result["approved"]
    result = authorize_net.refund_transaction(
        trans_id=plan["transactionId"],
        amount=refund.amount,
        last4=plan["last4"],
        invoice_number=refund.pk,
    )
    return result["id"], result["approved"]


def refund_order(
    order_id: str,
    body: dict,
    actor_email: str,
    *,
    can_view_transaction_ids: bool = False,
) -> tuple[dict, int]:
    """`POST /api/admin/orders/<id>/refunds/`. Sin `amount` reembolsa el
    saldo. El saldo es lo cobrado menos los reembolsos PENDING y SUCCEEDED."""
    error, plan = _refund_plan(order_id)
    if error:
        return {"error": error["error"]}, error["status"]
    error, opened = _open_refund(order_id, body, actor_email, plan)
    if error:
        return {"error": error["error"]}, error.get("status", 400)
    order, payment, refund = opened

    try:
        provider_refund_id, approved = _call_provider(plan, refund)
    except ProviderError as exc:
        logger.warning("Authorize.net refund %s for order %s failed: %s", refund.pk, order.pk, exc)
        return _fail_refund(refund), 502

    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        # El webhook pudo llegar antes y ya dejarla en su estado final.
        if refund.provider_refund_id is None and provider_refund_id:
            refund.provider_refund_id = provider_refund_id
        if refund.status == RefundStatus.PENDING:
            refund.status = RefundStatus.SUCCEEDED if approved else RefundStatus.FAILED
        refund.updated_at = timezone.now()
        refund.save(update_fields=["provider_refund_id", "status", "updated_at"])
        if order is not None:
            apply_refund_totals(order, payment)

    record_activity(
        actor=actor_email,
        action="REFUND_CREATED" if refund.status != RefundStatus.FAILED else "REFUND_FAILED",
        entity_type="ORDER",
        entity_id=order_id,
        data=_activity(refund, order),
    )
    if refund.status == RefundStatus.FAILED:
        return {"error": "The payment provider declined the refund"}, 502
    return serialize_refund(refund, can_view_transaction_ids), 201


def _fail_refund(refund: Refund) -> dict:
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        # Un timeout no dice si Authorize.net lo creó: si el webhook ya lo
        # trajo, manda lo que dijo la pasarela.
        if refund.status == RefundStatus.PENDING and refund.provider_refund_id is None:
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
    return {"error": PAYMENT_REQUEST_FAILED}


def _save_synced_refund(
    order: Order,
    payment: Payment,
    refund: Refund | None,
    *,
    provider_refund_id: str,
    amount: Decimal,
    status: str,
    source: str,
) -> None:
    """Crea o actualiza la fila y recalcula totales; un estado final que ya
    informó la pasarela no vuelve a PENDING. Sí corrige un FAILED local, que
    solo significa que nuestra llamada no obtuvo respuesta."""
    if refund is None:
        refund = Refund.objects.create(
            id=random_id("RFD"),
            payment=payment,
            amount=amount,
            status=status,
            reason="",
            provider_refund_id=provider_refund_id,
            created_by=PROVIDER_ACTOR,
            data={"source": source},
        )
        apply_refund_totals(order, payment)
        record_activity(
            actor=PROVIDER_ACTOR,
            action="REFUND_CREATED",
            entity_type="ORDER",
            entity_id=order.pk,
            data=_activity(refund, order),
        )
        return

    previous = refund.status
    stale = (
        status == RefundStatus.PENDING
        and previous in FINAL_REFUND_STATUSES
        and refund.provider_refund_id is not None
    )
    refund.provider_refund_id = provider_refund_id
    if not stale:
        refund.status = status
    refund.updated_at = timezone.now()
    refund.save(update_fields=["provider_refund_id", "status", "updated_at"])
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
            actor=PROVIDER_ACTOR,
            action=action,
            entity_type="ORDER",
            entity_id=order.pk,
            data=_activity(refund, order, previousStatus=previous),
        )


def sync_provider_refund(order: Order, payment: Payment, details: dict) -> None:
    """Fila de una transacción `refundTransaction` (webhook `refund.created`).
    Llamar con el pedido y el pago bloqueados."""
    amount = details.get("amount")
    if not details.get("id") or amount is None or amount <= 0:
        logger.warning("Ignoring malformed Authorize.net refund %s", details.get("id"))
        return
    approved = str(details.get("responseCode")) == "1" and (
        details.get("status") in APPROVED_REFUND_STATUSES
    )
    refund = (
        Refund.objects.select_for_update().filter(provider_refund_id=details["id"]).first()
        or Refund.objects.select_for_update()
        .filter(
            pk=details.get("invoiceNumber") or "",
            payment=payment,
            provider_refund_id__isnull=True,
        )
        .first()
    )
    _save_synced_refund(
        order,
        payment,
        refund,
        provider_refund_id=details["id"],
        amount=amount,
        status=RefundStatus.SUCCEEDED if approved else RefundStatus.FAILED,
        source="MERCHANT_INTERFACE",
    )


def sync_provider_void(order: Order, payment: Payment) -> None:
    """Anulación del cobro (webhook `void.created`): reembolso total.
    Llamar con el pedido y el pago bloqueados."""
    key = void_refund_id(transaction_id(payment))
    refund = (
        Refund.objects.select_for_update().filter(provider_refund_id=key).first()
        or Refund.objects.select_for_update()
        .filter(payment=payment, provider_refund_id__isnull=True, data__mode=MODE_VOID)
        .exclude(status=RefundStatus.CANCELED)
        .first()
    )
    _save_synced_refund(
        order,
        payment,
        refund,
        provider_refund_id=key,
        amount=payment.amount,
        status=RefundStatus.SUCCEEDED,
        source="MERCHANT_INTERFACE",
    )
