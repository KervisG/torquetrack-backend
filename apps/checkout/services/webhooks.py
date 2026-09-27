"""Conciliación de los eventos del webhook de Stripe."""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import Payment
from apps.checkout.services.payments import (
    CHARGED_PAYMENT_STATUSES,
    cancel_pending_payment,
    get_stripe_payment_method,
    lock_order_and_payment,
)
from apps.checkout.services.refunds import sync_stripe_refund
from apps.common.numbers import money, money_decimal

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
    Stripe: el pago queda PAID y la bitácora lo marca para reembolso.
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

        expected_cents = int(money_decimal(payment.amount) * 100)
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
        payment.status = "PAID"
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
        payment.save(update_fields=["status", "updated_at", "data"])

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
        if core_amount > 0 and not order_data.get("coreCase"):
            paid_patch["coreCase"] = {
                "status": "AWAITING CORE",
                "amount": core_amount,
                "createdAt": now.isoformat(),
                "createdBy": "stripe",
            }
        order.status = "OPEN"
        order.payment_status = "PAID"
        order.updated_at = now
        order.data = {**order_data, **paid_patch}
        order.save(update_fields=["status", "payment_status", "updated_at", "data"])

        # Las otras sesiones abiertas del pedido ya no deben cobrarse.
        superseded = Payment.objects.select_for_update().filter(
            order=order, provider="stripe", status="PENDING"
        )
        for other in superseded:
            cancel_pending_payment(other, "SUPERSEDED", data={"supersededBy": session_id})

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
        if payment.status != "PENDING":
            return
        payment.status = "FAILED"
        payment.updated_at = now
        payment.save(update_fields=["status", "updated_at"])
        if order is not None and order.payment_status not in (*CHARGED_PAYMENT_STATUSES, "FAILED"):
            order.payment_status = "FAILED"
            order.updated_at = now
            order.save(update_fields=["payment_status", "updated_at"])


def _refund_payment(payment_intent) -> Payment | None:
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
        logger.warning("Stripe refund for payment intent %s matches no payment", payment_intent)
        return None
    return payment


def reconcile_stripe_refund(refund_obj: dict, payment_intent=None) -> None:
    """`refund.created`, `refund.updated` y `refund.failed`: crea o actualiza
    la fila `Refund` (idempotente por `stripe_refund_id`) y recalcula el
    estado del pago y del pedido, con el mismo bloqueo pedido → pago que el
    cobro."""
    payment = _refund_payment(refund_obj.get("payment_intent") or payment_intent)
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
