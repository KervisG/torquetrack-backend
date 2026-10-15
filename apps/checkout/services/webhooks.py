"""Conciliación de los eventos del webhook de Stripe."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import (
    CoreStatus,
    OrderPaymentStatus,
    OrderStatus,
    Payment,
    PaymentStatus,
)
from apps.checkout.services.payments import (
    CHARGED_PAYMENT_STATUSES,
    CLOSED_ORDER_STATUSES,
    cancel_pending_payment,
    cancel_unpaid_order,
    get_stripe_payment_method,
    lock_order_and_payment,
)
from apps.checkout.services.refunds import sync_stripe_refund
from apps.checkout.services.workflow_emails import notify_core_opened
from apps.common.numbers import money, to_cents

logger = logging.getLogger(__name__)


def _session_payment(session_obj: dict) -> Payment | None:
    """`Payment` de la Checkout Session del evento, o `None` si la sesión no
    es nuestra o no coincide con el pedido de su metadata."""
    session_id = session_obj.get("id")
    metadata = session_obj.get("metadata") or {}
    order_id = metadata.get("order_id") or session_obj.get("client_reference_id")
    payment = (
        Payment.objects.filter(provider="stripe", provider_id=session_id).first()
        if session_id
        else None
    )
    if payment is None or payment.order_id is None or (order_id and payment.order_id != order_id):
        # Se responde 200 igual: reintentar no va a hacer aparecer el pago.
        logger.warning(
            "Stripe session %s for order %s does not match any payment", session_id, order_id
        )
        return None
    return payment


def reconcile_paid_session(session_obj: dict) -> None:
    """`checkout.session.completed` / `async_payment_succeeded`.

    Marca PAID el pago de ESA sesión y el pedido, y cancela las demás
    sesiones pendientes del pedido. Es idempotente: un reenvío del mismo
    evento, o dos eventos de éxito concurrentes, registran una sola vez. Si
    el pedido ya estaba pagado por otra sesión, el cobro igual existe en
    Stripe: el pago queda PAID y la bitácora lo marca para reembolso. Lo
    mismo con un pedido cancelado o rechazado, que además conserva su estado
    (`PAYMENT_ON_CLOSED_ORDER`).
    """
    if session_obj.get("payment_status") != "paid":
        # Un medio asíncrono completa la sesión antes de cobrar; el cobro se
        # confirma con `async_payment_succeeded`, que vuelve a pasar por aquí.
        return
    payment = _session_payment(session_obj)
    # Un pago reembolsado sigue cobrado: un reenvío del evento no lo repaga.
    if payment is None or payment.status in CHARGED_PAYMENT_STATUSES:
        return

    # Fuera del bloqueo: es una llamada de red y es solo decorativa.
    method = get_stripe_payment_method(session_obj.get("payment_intent")) or {}
    session_id = session_obj.get("id")
    now = timezone.now()

    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if order is None or payment.status in CHARGED_PAYMENT_STATUSES:
            return

        expected_cents = to_cents(payment.amount)
        if session_obj.get("amount_total") != expected_cents:
            # Cobrar otro monto no salda el pedido: queda pendiente para que
            # el staff lo revise. Se responde 200 igual porque un reintento
            # de Stripe no lo resuelve.
            logger.warning(
                "Stripe session %s charged %s cents; payment %s expects %s",
                session_id,
                session_obj.get("amount_total"),
                payment.pk,
                expected_cents,
            )
            record_activity(
                actor="stripe",
                action="PAYMENT_AMOUNT_MISMATCH",
                entity_type="ORDER",
                entity_id=order.pk,
                data={
                    "sessionId": session_id,
                    "paymentId": payment.pk,
                    "amountTotal": session_obj.get("amount_total"),
                    "expectedAmount": expected_cents,
                },
            )
            return

        customer_details = session_obj.get("customer_details") or {}
        payment.status = PaymentStatus.PAID
        payment.paid_at = now
        payment.updated_at = now
        payment.data = {
            **(payment.data or {}),
            "payment_intent": session_obj.get("payment_intent"),
            "payment_status": session_obj.get("payment_status"),
            "customer_email": customer_details.get("email") or session_obj.get("customer_email"),
            "brand": method.get("brand"),
            "last4": method.get("last4"),
            "funding": method.get("funding"),
        }
        payment.save(update_fields=["status", "paid_at", "updated_at", "data"])

        activity = {
            "sessionId": session_id,
            "paymentIntent": session_obj.get("payment_intent"),
            "amountTotal": session_obj.get("amount_total"),
            "brand": method.get("brand"),
            "last4": method.get("last4"),
        }
        if order.payment_status in CHARGED_PAYMENT_STATUSES:
            record_activity(
                actor="stripe",
                action="DUPLICATE_PAYMENT_RECEIVED",
                entity_type="ORDER",
                entity_id=order.pk,
                data={**activity, "paymentId": payment.pk},
            )
            return

        # Un pedido cancelado o rechazado no se reabre: el cobro queda
        # registrado para que el staff lo reembolse.
        closed = order.status in CLOSED_ORDER_STATUSES
        order_data = order.data or {}
        paid_patch = {
            "payment": {
                "provider": "stripe",
                "brand": method.get("brand"),
                "last4": method.get("last4"),
                "paymentIntent": session_obj.get("payment_intent"),
                "paidAt": now.isoformat(),
            }
        }
        core_amount = money((order_data.get("totals") or {}).get("core"))
        if core_amount > 0 and not order_data.get("coreCase") and not closed:
            paid_patch["coreCase"] = {
                "status": CoreStatus.AWAITING_CORE,
                "amount": core_amount,
                "createdAt": now.isoformat(),
                "createdBy": "stripe",
            }
        if not closed:
            order.status = OrderStatus.OPEN
        order.payment_status = OrderPaymentStatus.PAID
        order.updated_at = now
        order.data = {**order_data, **paid_patch}
        order.save(update_fields=["status", "payment_status", "updated_at", "data"])
        if "coreCase" in paid_patch:
            # Recién con el pago confirmado: si la transacción hace rollback,
            # nadie recibe un aviso de un core que no existe.
            transaction.on_commit(lambda: notify_core_opened(order))

        # Las otras sesiones abiertas del pedido ya no deben cobrarse.
        superseded = Payment.objects.select_for_update().filter(
            order=order, provider="stripe", status=PaymentStatus.PENDING
        )
        for other in superseded:
            cancel_pending_payment(other, "SUPERSEDED", data={"supersededBy": session_id})

        if closed:
            logger.warning(
                "Stripe session %s paid %s cents on %s order %s (payment %s); refund required",
                session_id,
                session_obj.get("amount_total"),
                order.status,
                order.pk,
                payment.pk,
            )
            record_activity(
                actor="stripe",
                action="PAYMENT_ON_CLOSED_ORDER",
                entity_type="ORDER",
                entity_id=order.pk,
                data={**activity, "paymentId": payment.pk, "orderStatus": order.status},
            )
            return

        record_activity(
            actor="stripe",
            action="PAYMENT_PAID",
            entity_type="ORDER",
            entity_id=order.pk,
            data=activity,
        )


def reconcile_failed_session(session_obj: dict) -> None:
    """`checkout.session.async_payment_failed`: falla el pago de esa sesión;
    el pedido pasa a FAILED salvo que otra sesión ya lo haya pagado."""
    payment = _session_payment(session_obj)
    if payment is None:
        return

    now = timezone.now()
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if payment.status != PaymentStatus.PENDING:
            return
        payment.status = PaymentStatus.FAILED
        payment.updated_at = now
        payment.save(update_fields=["status", "updated_at"])
        if order is not None and order.payment_status not in (
            *CHARGED_PAYMENT_STATUSES,
            OrderPaymentStatus.FAILED,
        ):
            order.payment_status = OrderPaymentStatus.FAILED
            order.updated_at = now
            order.save(update_fields=["payment_status", "updated_at"])


def reconcile_expired_session(session_obj: dict) -> None:
    """`checkout.session.expired`: Stripe cerró una sesión que nadie pagó.

    El `Payment` PENDING de esa sesión pasa a CANCELLED (`SESSION_EXPIRED`)
    sin llamar a Stripe: la sesión ya está vencida. El pedido se cancela
    (`PAYMENT_EXPIRED`, bitácora `ORDER_EXPIRED`) con `cancel_unpaid_order`,
    la misma regla que usa el resto del checkout, solo si sigue
    `PENDING_PAYMENT`, sin cobrar y sin otra sesión pendiente: un pedido
    pagado, uno del panel (`OPEN`) o uno con un link más nuevo no se toca.
    Idempotente: un reenvío encuentra el pago ya cancelado y no hace nada.
    Con el pedido cancelado, una cotización vuelve a poder pagarse porque
    `checkout_from_quote` ignora los pedidos `CANCELLED`.
    """
    payment = _session_payment(session_obj)
    if payment is None:
        return

    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if payment.status != PaymentStatus.PENDING:
            return
        payment.status = PaymentStatus.CANCELLED
        payment.updated_at = timezone.now()
        payment.data = {**(payment.data or {}), "cancelReason": "SESSION_EXPIRED"}
        payment.save(update_fields=["status", "updated_at", "data"])

        if order is None or order.status != OrderStatus.PENDING_PAYMENT:
            return
        if order.payment_status in CHARGED_PAYMENT_STATUSES:
            return
        if Payment.objects.filter(order=order, status=PaymentStatus.PENDING).exists():
            return
        cancel_unpaid_order(order, "PAYMENT_EXPIRED")

    record_activity(
        actor="stripe",
        action="ORDER_EXPIRED",
        entity_type="ORDER",
        entity_id=order.pk,
        data={"sessionId": session_obj.get("id"), "paymentId": payment.pk},
    )


def _intent_payment(payment_intent, event_name: str) -> Payment | None:
    """`Payment` cobrado del PaymentIntent, o `None` si no es nuestro."""
    payment = (
        Payment.objects.filter(provider="stripe", data__payment_intent=payment_intent)
        .order_by("created_at")
        .first()
        if payment_intent
        else None
    )
    if payment is None or payment.order_id is None:
        # Se responde 200 igual: reintentar no va a hacer aparecer el pago.
        logger.warning(
            "Stripe %s for payment intent %s matches no payment", event_name, payment_intent
        )
        return None
    return payment


def reconcile_stripe_refund(refund_obj: dict, payment_intent=None) -> None:
    """`refund.created`, `refund.updated` y `refund.failed`: crea o actualiza
    la fila `Refund` (idempotente por `stripe_refund_id`) y recalcula el
    estado del pago y del pedido, con el mismo bloqueo pedido → pago que el
    cobro."""
    payment = _intent_payment(refund_obj.get("payment_intent") or payment_intent, "refund")
    if payment is None:
        return
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if order is None:
            return
        sync_stripe_refund(order, payment, refund_obj)


def reconcile_refunded_charge(charge_obj: dict) -> None:
    """`charge.refunded`: sincroniza los reembolsos que trae el cargo. Desde
    la API 2022-11-15 la lista `refunds` no viene en el evento; en ese caso
    no hay nada que hacer y sincronizan los eventos `refund.*`."""
    refunds = (charge_obj.get("refunds") or {}).get("data") or []
    for refund_obj in refunds:
        reconcile_stripe_refund(refund_obj, payment_intent=charge_obj.get("payment_intent"))


def _flag_order(notice_obj: dict, *, key: str, action: str, event_name: str, patch: dict) -> None:
    """Guarda el aviso en `order.data[key]` y lo registra en la bitácora.

    No reembolsa ni cambia el estado del pedido: el staff decide si devuelve
    el cobro (un reembolso a tiempo evita el contracargo) o si responde la
    disputa. Idempotente por el id del aviso: un reenvío no duplica la bitácora.
    """
    payment = _intent_payment(notice_obj.get("payment_intent"), event_name)
    if payment is None:
        return
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if order is None:
            return
        order_data = order.data or {}
        if (order_data.get(key) or {}).get("id") == notice_obj.get("id"):
            return
        logger.warning(
            "Stripe %s %s on order %s (payment %s)",
            event_name,
            notice_obj.get("id"),
            order.pk,
            payment.pk,
        )
        order.data = {**order_data, key: patch}
        order.updated_at = timezone.now()
        order.save(update_fields=["data", "updated_at"])
        record_activity(
            actor="stripe",
            action=action,
            entity_type="ORDER",
            entity_id=order.pk,
            data={
                **patch,
                "paymentId": payment.pk,
                "paymentIntent": notice_obj.get("payment_intent"),
            },
        )


def reconcile_early_fraud_warning(warning_obj: dict) -> None:
    """`radar.early_fraud_warning.created`: el banco avisa que el cobro
    probablemente es fraude y es muy posible que llegue un contracargo."""
    _flag_order(
        warning_obj,
        key="fraudWarning",
        action="FRAUD_WARNING_RECEIVED",
        event_name="early fraud warning",
        patch={
            "id": warning_obj.get("id"),
            "fraudType": warning_obj.get("fraud_type"),
            "actionable": bool(warning_obj.get("actionable")),
            "chargeId": warning_obj.get("charge"),
            "receivedAt": timezone.now().isoformat(),
        },
    )


def reconcile_dispute_created(dispute_obj: dict) -> None:
    """`charge.dispute.created`: el titular abrió un contracargo. Stripe ya
    retuvo el monto; `evidenceDueBy` es el plazo para responder."""
    due_by = (dispute_obj.get("evidence_details") or {}).get("due_by")
    _flag_order(
        dispute_obj,
        key="dispute",
        action="DISPUTE_OPENED",
        event_name="dispute",
        patch={
            "id": dispute_obj.get("id"),
            "reason": dispute_obj.get("reason"),
            "amount": money(Decimal(dispute_obj.get("amount") or 0) / 100),
            "chargeId": dispute_obj.get("charge"),
            "evidenceDueBy": (
                datetime.fromtimestamp(due_by, tz=UTC).isoformat() if due_by else None
            ),
            "openedAt": timezone.now().isoformat(),
        },
    )
