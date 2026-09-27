"""Pagos de Stripe: único lugar que abre, registra, cancela y expira pagos,
así el monto, su redondeo y el `provider_id` que concilia el webhook salen de
un solo lugar."""
from __future__ import annotations

import logging
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from apps.checkout.models import Order, Payment
from apps.common.ids import random_id
from apps.common.links import app_url
from apps.common.numbers import money, money_decimal, to_number
from apps.integrations.exceptions import ProviderError
from apps.integrations.payments import stripe as stripe_payments

logger = logging.getLogger(__name__)

# Estados de un pago (y de `order.payment_status`) en los que Stripe ya
# cobró. Un reembolso no convierte el cobro en "no pagado": el pedido no se
# vuelve a cobrar ni el webhook lo marca PAID otra vez.
CHARGED_PAYMENT_STATUSES = ("PAID", "PARTIALLY_REFUNDED", "REFUNDED")
# El staff sabe que falló Stripe (link de pago, cobro, reembolso), pero el
# texto del proveedor queda en el log.
STRIPE_REQUEST_FAILED = "Stripe request failed; see server logs."


def _line(name: str, unit_price: float, qty: int) -> dict:
    return {"name": name, "unit_amount": int(money_decimal(unit_price) * 100), "quantity": qty}


def _create_checkout_session(order: dict) -> dict:
    """Devuelve `{"id", "url"}`; lanza `ProviderError` o `ProviderNotConfigured`."""
    items = order.get("items") or []
    totals = order.get("totals") or {}
    line_items = []
    for item in items:
        qty = max(1, int(to_number(item.get("qty") or item.get("quantity"), 1)))
        price = money(item.get("price") if item.get("price") is not None else item.get("unitPrice"))
        core = money(item.get("coreCharge"))
        title = item.get("title") or item.get("partNumber") or "Diesel Part"
        line_items.append(_line(title, price, qty))
        if core > 0:
            line_items.append(_line(f"Core charge — {title}", core, qty))

    for name, value in (
        ("Shipping", money(totals.get("shipping"))),
        ("Sales Tax", money(totals.get("tax"))),
    ):
        if value > 0:
            line_items.append(_line(name, value, 1))

    order_id = str(order["id"])
    return stripe_payments.create_checkout_session(
        client_reference_id=order_id,
        line_items=line_items,
        success_url=app_url(
            f"/checkout-success.html?session_id={{CHECKOUT_SESSION_ID}}&order_id={quote(order_id)}"
        ),
        cancel_url=app_url("/checkout.html?canceled=1"),
        metadata={"order_id": order_id, "order_number": order["number"]},
        customer_email=(order.get("customer") or {}).get("email") or None,
    )


def start_stripe_payment(order: Order, *, data: dict | None = None) -> tuple[Payment, dict]:
    """Única forma de cobrar con Stripe, así el monto, su redondeo y el
    `provider_id` que busca el webhook (el id de la sesión) salen de un solo
    lugar. Si Stripe falla lanza `ProviderError` sin dejar ningún `Payment`.
    """
    order_data = order.data or {}
    # El id y el número van al final: un `id` guardado en el jsonb no puede
    # desviar la sesión hacia otro pedido.
    session = _create_checkout_session({**order_data, "id": order.pk, "number": order.number})
    with transaction.atomic():
        payment = Payment.objects.create(
            id=random_id("PAY"),
            order=order,
            provider="stripe",
            provider_id=session["id"],
            status="PENDING",
            amount=money_decimal((order_data.get("totals") or {}).get("total")),
            data={"sessionId": session["id"], **(data or {})},
        )
        # Un pedido tiene una sola sesión cobrable: la anterior (otro link,
        # otro intento de checkout) se expira solo cuando la nueva ya existe.
        previous = (
            Payment.objects.select_for_update()
            .filter(order=order, provider="stripe", status="PENDING")
            .exclude(pk=payment.pk)
        )
        for other in previous:
            cancel_pending_payment(other, "REPLACED", data={"replacedBy": session["id"]})
    return payment, session


def lock_order_and_payment(payment: Payment) -> tuple[Order | None, Payment]:
    """Bloquea primero el pedido y después el pago, siempre en ese orden
    (webhook, reembolsos), y relee el pago ya bloqueado para ver lo que otro
    evento acaba de confirmar."""
    order = Order.objects.select_for_update().filter(pk=payment.order_id).first()
    return order, Payment.objects.select_for_update().get(pk=payment.pk)


def cancel_pending_payment(payment: Payment, reason: str, *, data: dict | None = None) -> None:
    """Única forma de cancelar un pago PENDING, porque además expira su
    Checkout Session para que el cliente ya no pueda pagarla.

    La expiración corre en `on_commit`: si la transacción hace rollback, la
    sesión sigue viva igual que el pago. Un error de Stripe solo se registra;
    en el peor caso el cliente paga una sesión cancelada y el webhook la marca
    para reembolso (`DUPLICATE_PAYMENT_RECEIVED`).
    """
    if payment.status != "PENDING":
        return
    payment.status = "CANCELLED"
    payment.updated_at = timezone.now()
    payment.data = {**(payment.data or {}), "cancelReason": reason, **(data or {})}
    payment.save(update_fields=["status", "updated_at", "data"])

    if payment.provider == "stripe" and payment.provider_id:
        session_id, payment_id = payment.provider_id, payment.pk
        transaction.on_commit(lambda: _expire_stripe_session(session_id, payment_id))


def _expire_stripe_session(session_id: str, payment_id: str) -> None:
    try:
        result = stripe_payments.expire_checkout_session(session_id)
    except ProviderError as exc:
        logger.warning(
            "Could not expire Stripe session %s of cancelled payment %s: %s",
            session_id,
            payment_id,
            exc,
        )
        return
    if result.get("status") == "complete":
        # Se pagó antes de poder expirarla; el webhook la concilia y, si el
        # pedido ya estaba pagado, la marca para reembolso.
        logger.warning(
            "Stripe session %s of cancelled payment %s was already complete",
            session_id,
            payment_id,
        )


def cancel_pending_payments(order: Order, reason: str) -> None:
    with transaction.atomic():
        for payment in Payment.objects.select_for_update().filter(order=order, status="PENDING"):
            cancel_pending_payment(payment, reason)


def cancel_unpaid_order(order: Order, reason: str) -> None:
    """El número queda emitido en el pedido cancelado: la serie no se reutiliza ni se salta."""
    with transaction.atomic():
        order.status = "CANCELLED"
        order.data = {**(order.data or {}), "cancelReason": reason}
        order.updated_at = timezone.now()
        order.save(update_fields=["status", "data", "updated_at"])
        cancel_pending_payments(order, reason)


def get_stripe_payment_method(payment_intent_id) -> dict | None:
    """Dato decorativo: sin key, sin PaymentIntent o con Stripe caído devuelve
    `None` y el webhook concilia igual."""
    if not payment_intent_id:
        return None
    try:
        return stripe_payments.retrieve_payment_method(payment_intent_id)
    except ProviderError:
        return None
