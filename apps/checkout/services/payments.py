"""Pagos con Authorize.net (Accept Hosted): único lugar que abre, registra,
cancela y vence pagos, así el monto, su redondeo y el `invoiceNumber` que
concilia el webhook salen de un solo lugar.

Abrir un pago no llama a Authorize.net: el `Payment` nace PENDING y su `url`
apunta al puente `GET /api/payments/<id>/pay/`, que pide el token del
formulario recién al abrirse. El token vence a los 15 minutos; un link de
pago enviado por correo sigue sirviendo mientras el pago esté PENDING.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.catalog.services.pricing import price_lines
from apps.checkout.models import Order, OrderStatus, Payment, PaymentStatus
from apps.common.ids import random_id
from apps.common.links import app_url
from apps.common.numbers import money_decimal
from apps.integrations.exceptions import ProviderNotConfigured
from apps.integrations.payments import authorize_net

logger = logging.getLogger(__name__)

PROVIDER = "authorize_net"
# Actor de la bitácora para lo que confirma la pasarela (webhook, vencimiento).
PROVIDER_ACTOR = "authorize_net"
# Estados de un pago (y de `order.payment_status`) en los que la pasarela ya
# cobró. Un reembolso no convierte el cobro en "no pagado": el pedido no se
# vuelve a cobrar ni el webhook lo marca PAID otra vez.
CHARGED_PAYMENT_STATUSES = (
    PaymentStatus.PAID,
    PaymentStatus.PARTIALLY_REFUNDED,
    PaymentStatus.REFUNDED,
)
# Estados en los que el pedido ya no se va a cobrar ni despachar. Vive aquí
# porque lo usan el panel y el webhook, y `webhooks` no importa `admin`.
CLOSED_ORDER_STATUSES = {OrderStatus.CANCELLED, OrderStatus.REJECTED}
# El staff sabe que falló la pasarela (cobro, reembolso), pero el texto del
# proveedor queda en el log.
PAYMENT_REQUEST_FAILED = "Payment provider request failed; see server logs."
# Lo mismo que duraba una Checkout Session de Stripe: pasado este plazo un
# pago PENDING vence y su pedido de la tienda se cancela.
PENDING_PAYMENT_TTL = timedelta(hours=24)


def transaction_id(payment: Payment) -> str | None:
    """Id de la transacción de Authorize.net que cobró este pago."""
    return payment.provider_id or (payment.data or {}).get("transactionId") or None


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _address(customer: dict) -> dict | None:
    """Dirección del pedido para precargar facturación y envío del form, así
    el AVS la compara con la tarjeta. La tienda solo envía dentro de EE. UU."""
    name, street = _text(customer.get("name")), _text(customer.get("address1"))
    if not name or not street:
        return None
    first, _, last = name.partition(" ")
    line2 = _text(customer.get("address2"))
    return {
        "firstName": first,
        "lastName": last.strip(),
        "address": f"{street} {line2}".strip(),
        "city": _text(customer.get("city")),
        "state": _text(customer.get("state")),
        "zip": _text(customer.get("zip")),
    }


def _line_items(order_data: dict) -> list[dict]:
    """Las líneas guardadas ya pasaron por `price_lines` (checkout, solicitud
    o panel); se leen con la misma regla para que el detalle coincida con el
    `total` que guarda el `Payment`."""
    priced = price_lines(order_data.get("items") or [], allow_custom_price=True, max_quantity=None)
    lines = []
    for index, line in enumerate(priced.lines, start=1):
        title = line.item.get("title") or line.item.get("partNumber") or "Diesel Part"
        item_id = str(line.item.get("partNumber") or line.item.get("productId") or f"LINE{index}")
        lines.append(
            {"id": item_id, "name": title, "quantity": line.quantity, "unitPrice": line.unit_price}
        )
        if line.core_charge > 0:
            lines.append(
                {
                    "id": f"CORE-{item_id}",
                    "name": f"Core charge - {title}",
                    "quantity": line.quantity,
                    "unitPrice": line.core_charge,
                }
            )
    return lines


def payment_page_url(payment: Payment) -> str:
    return app_url(f"/api/payments/{quote(payment.pk)}/pay/")


def start_payment(order: Order, *, data: dict | None = None) -> tuple[Payment, dict]:
    """Única forma de abrir un cobro. Devuelve `(payment, {"id", "url"})`.

    No llama a la pasarela; sin credenciales lanza `ProviderNotConfigured` sin
    dejar ningún `Payment`. Un pedido tiene un solo pago cobrable: el anterior
    (otro link, otro intento de checkout) se cancela al crear el nuevo.
    """
    if not authorize_net.is_configured():
        raise ProviderNotConfigured("Authorize.net credentials are not set")
    order_data = order.data or {}
    with transaction.atomic():
        payment = Payment.objects.create(
            id=random_id("PAY"),
            order=order,
            provider=PROVIDER,
            provider_id=None,
            status=PaymentStatus.PENDING,
            amount=money_decimal((order_data.get("totals") or {}).get("total")),
            data={**(data or {})},
        )
        previous = (
            Payment.objects.select_for_update()
            .filter(order=order, status=PaymentStatus.PENDING)
            .exclude(pk=payment.pk)
        )
        for other in previous:
            cancel_pending_payment(other, "REPLACED", data={"replacedBy": payment.pk})
    return payment, {"id": payment.pk, "url": payment_page_url(payment)}


def create_payment_form(payment: Payment) -> dict:
    """Token de Accept Hosted para un pago PENDING. Devuelve `{"token",
    "formUrl"}`; lanza `ProviderError` o `ProviderNotConfigured`.

    El id y el número salen de las columnas del pedido, no del jsonb: un `id`
    guardado en `data` no puede desviar el cobro hacia otro pedido.
    """
    order = payment.order
    order_data = order.data or {}
    totals = order_data.get("totals") or {}
    customer = order_data.get("customer") or {}
    return authorize_net.create_hosted_payment_token(
        invoice_number=payment.pk,
        description=f"TorqueTrack Order {order.number}",
        amount=payment.amount,
        line_items=_line_items(order_data),
        tax=money_decimal(totals.get("tax")),
        shipping=money_decimal(totals.get("shipping")),
        customer_email=customer.get("email") or None,
        address=_address(customer),
        return_url=app_url(f"/checkout-success?order_id={quote(str(order.pk))}"),
        cancel_url=app_url("/checkout?canceled=1"),
    )


def lock_order_and_payment(payment: Payment) -> tuple[Order | None, Payment]:
    """Bloquea primero el pedido y después el pago, siempre en ese orden
    (webhook, reembolsos, vencimiento), y relee el pago ya bloqueado para ver
    lo que otro evento acaba de confirmar."""
    order = Order.objects.select_for_update().filter(pk=payment.order_id).first()
    return order, Payment.objects.select_for_update().get(pk=payment.pk)


def cancel_pending_payment(payment: Payment, reason: str, *, data: dict | None = None) -> None:
    """Única forma de cancelar un pago PENDING. Desde ese momento el puente
    ya no entrega el formulario. Un form abierto antes (token vigente hasta
    15 minutos) todavía puede cobrarse: el webhook lo concilia y, si el
    pedido ya estaba pagado, lo marca para reembolso
    (`DUPLICATE_PAYMENT_RECEIVED`).
    """
    if payment.status != PaymentStatus.PENDING:
        return
    payment.status = PaymentStatus.CANCELLED
    payment.updated_at = timezone.now()
    payment.data = {**(payment.data or {}), "cancelReason": reason, **(data or {})}
    payment.save(update_fields=["status", "updated_at", "data"])


def cancel_pending_payments(order: Order, reason: str) -> None:
    with transaction.atomic():
        for payment in Payment.objects.select_for_update().filter(
            order=order, status=PaymentStatus.PENDING
        ):
            cancel_pending_payment(payment, reason)


def cancel_unpaid_order(order: Order, reason: str) -> None:
    """El número queda emitido en el pedido cancelado: la serie no se reutiliza ni se salta."""
    with transaction.atomic():
        order.status = OrderStatus.CANCELLED
        order.data = {**(order.data or {}), "cancelReason": reason}
        order.updated_at = timezone.now()
        order.save(update_fields=["status", "data", "updated_at"])
        cancel_pending_payments(order, reason)


def expire_pending_payment(payment: Payment) -> bool:
    """Vence un pago PENDING que nadie pagó (`PAYMENT_EXPIRED`).

    El pedido se cancela con `cancel_unpaid_order` solo si sigue
    `PENDING_PAYMENT`, sin cobrar y sin otro pago pendiente: un pedido pagado,
    uno del panel (`OPEN`) o uno con un link más nuevo no se toca. Con el
    pedido cancelado, una cotización vuelve a poder pagarse porque
    `checkout_from_quote` ignora los pedidos `CANCELLED`. Devuelve `True` si
    canceló el pedido. Idempotente.
    """
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if payment.status != PaymentStatus.PENDING:
            return False
        payment.status = PaymentStatus.CANCELLED
        payment.updated_at = timezone.now()
        payment.data = {**(payment.data or {}), "cancelReason": "PAYMENT_EXPIRED"}
        payment.save(update_fields=["status", "updated_at", "data"])

        if order is None or order.status != OrderStatus.PENDING_PAYMENT:
            return False
        if order.payment_status in CHARGED_PAYMENT_STATUSES:
            return False
        if Payment.objects.filter(order=order, status=PaymentStatus.PENDING).exists():
            return False
        cancel_unpaid_order(order, "PAYMENT_EXPIRED")

    record_activity(
        actor=PROVIDER_ACTOR,
        action="ORDER_EXPIRED",
        entity_type="ORDER",
        entity_id=order.pk,
        data={"paymentId": payment.pk},
    )
    return True


def expire_stale_payments(now=None) -> int:
    """Vence los pagos PENDING con más de `PENDING_PAYMENT_TTL`. Devuelve
    cuántos pedidos canceló."""
    cutoff = (now or timezone.now()) - PENDING_PAYMENT_TTL
    stale = list(Payment.objects.filter(status=PaymentStatus.PENDING, created_at__lt=cutoff))
    return sum(1 for payment in stale if expire_pending_payment(payment))
