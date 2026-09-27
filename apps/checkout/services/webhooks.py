"""Conciliación de los eventos del webhook de Stripe."""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import Order, Payment
from apps.checkout.services.payments import cancel_pending_payment, get_stripe_payment_method
from apps.common.numbers import money

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


def _locked_order_and_payment(payment: Payment) -> tuple[Order | None, Payment]:
    """Bloquea primero el pedido y después el pago, siempre en ese orden, y
    relee el pago ya bloqueado para ver lo que otro evento acaba de
    confirmar."""
    order = Order.objects.select_for_update().filter(pk=payment.order_id).first()
    return order, Payment.objects.select_for_update().get(pk=payment.pk)


def reconcile_paid_session(session_obj: dict) -> None:
    """`checkout.session.completed` / `async_payment_succeeded`.

    Marca PAID el pago de ESA sesión y el pedido, y cancela las demás
    sesiones pendientes del pedido. Es idempotente: un reenvío del mismo
    evento, o dos eventos de éxito concurrentes, registran una sola vez. Si
    el pedido ya estaba pagado por otra sesión, el cobro igual existe en
    Stripe: el pago queda PAID y la bitácora lo marca para reembolso.
    """
    payment = _session_payment(session_obj)
    if payment is None or payment.status == "PAID":
        return

    # Fuera del bloqueo: es una llamada de red y es solo decorativa.
    method = get_stripe_payment_method(session_obj.get("payment_intent")) or {}
    session_id = session_obj.get("id")
    now = timezone.now()

    with transaction.atomic():
        order, payment = _locked_order_and_payment(payment)
        if order is None or payment.status == "PAID":
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
        if order.payment_status == "PAID":
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
        order, payment = _locked_order_and_payment(payment)
        if payment.status != "PENDING":
            return
        payment.status = "FAILED"
        payment.updated_at = now
        payment.save(update_fields=["status", "updated_at"])
        if order is not None and order.payment_status not in ("PAID", "FAILED"):
            order.payment_status = "FAILED"
            order.updated_at = now
            order.save(update_fields=["payment_status", "updated_at"])
