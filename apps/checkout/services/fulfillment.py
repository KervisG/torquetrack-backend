"""Envío de los pedidos desde el panel: estado de fulfillment, transportista,
guía y el correo "has shipped" al cliente.

El envío vive en columnas propias de `Order`, separado de `Order.status`:
avanzarlo no cierra ni reabre el pedido, y el panel sigue cambiando `status`
por su lado (`patch_admin_order`)."""
from __future__ import annotations

import logging
import re

from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html

from apps.audit.services import record_activity
from apps.authentication.utils.background import run_in_background
from apps.checkout.models import Carrier, FulfillmentStatus, Order, OrderPaymentStatus
from apps.checkout.services.payments import CHARGED_PAYMENT_STATUSES, CLOSED_ORDER_STATUSES
from apps.integrations.email import resend

logger = logging.getLogger(__name__)

# Solo hacia adelante. `UNFULFILLED -> SHIPPED` se permite porque muchos
# pedidos se despachan el mismo día sin pasar por "preparing"; `DELIVERED`
# exige haber pasado por `SHIPPED`, que es donde queda la guía.
FULFILLMENT_TRANSITIONS = {
    FulfillmentStatus.UNFULFILLED: {FulfillmentStatus.PREPARING, FulfillmentStatus.SHIPPED},
    FulfillmentStatus.PREPARING: {FulfillmentStatus.SHIPPED},
    FulfillmentStatus.SHIPPED: {FulfillmentStatus.DELIVERED},
    FulfillmentStatus.DELIVERED: set(),
}
# La guía va sin escapar dentro de la URL del transportista y del correo:
# limitarla a letras, dígitos y guiones deja fuera cualquier inyección.
TRACKING_NUMBER_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")

INVALID_STATUS = "Invalid fulfillment status"
INVALID_CARRIER = f"Carrier must be one of {', '.join(Carrier.values)}"
TRACKING_REQUIRED = "Tracking number is required to ship an order"
INVALID_TRACKING = "Tracking number must be 1 to 64 letters, digits or hyphens"
SHIPMENT_FIELDS_NOT_ALLOWED = (
    "Carrier and tracking number can only be set when marking an order SHIPPED"
)
ORDER_NOT_FOUND = "Order not found"
NOT_PAID = "Only paid orders can be fulfilled"
CLOSED = "Closed orders cannot be fulfilled"
SAME_TRACKING = "Order already shipped with this tracking number"


def _parse_payload(payload) -> tuple[dict | None, str | None]:
    """`(cambio, None)` con el estado, transportista y guía normalizados, o
    `(None, mensaje)` para un 400."""
    if not isinstance(payload, dict):
        return None, INVALID_STATUS
    status = str(payload.get("status") or "").strip().upper()
    if status not in FulfillmentStatus.values:
        return None, INVALID_STATUS

    raw_carrier = payload.get("carrier")
    raw_tracking = payload.get("trackingNumber")
    if status != FulfillmentStatus.SHIPPED:
        if raw_carrier not in (None, "") or raw_tracking not in (None, ""):
            return None, SHIPMENT_FIELDS_NOT_ALLOWED
        return {"status": FulfillmentStatus(status)}, None

    carrier = str(raw_carrier or "").strip().upper()
    if carrier not in Carrier.values:
        return None, INVALID_CARRIER
    if raw_tracking in (None, ""):
        return None, TRACKING_REQUIRED
    if not isinstance(raw_tracking, str):
        return None, INVALID_TRACKING
    tracking = raw_tracking.strip()
    if not TRACKING_NUMBER_PATTERN.fullmatch(tracking):
        return None, INVALID_TRACKING
    return {
        "status": FulfillmentStatus.SHIPPED,
        "carrier": Carrier(carrier),
        "trackingNumber": tracking,
    }, None


def _transition_error(order: Order, change: dict) -> str | None:
    current = FulfillmentStatus(order.fulfillment_status)
    target = change["status"]
    if current == target == FulfillmentStatus.SHIPPED:
        # Corregir la guía estando SHIPPED está permitido; repetir la misma no.
        unchanged = (
            order.carrier == change["carrier"]
            and order.tracking_number == change["trackingNumber"]
        )
        return SAME_TRACKING if unchanged else None
    if current == target:
        return f"Fulfillment is already {current}"
    if target not in FULFILLMENT_TRANSITIONS[current]:
        return f"Cannot move fulfillment from {current} to {target}"
    return None


def serialize_fulfillment(order: Order) -> dict:
    return {"id": order.pk, "number": order.number, **order.fulfillment_summary()}


def update_order_fulfillment(order_id: str, payload, actor_email: str) -> tuple[dict, int]:
    change, error = _parse_payload(payload)
    if error:
        return {"error": error}, 400

    with transaction.atomic():
        # Misma fila bloqueada que usan el webhook y el cambio de estado: un
        # reembolso o una cancelación que llegan a la vez no quedan a medias
        # frente al despacho.
        order = (
            Order.objects.select_for_update(of=("self",))
            .select_related("customer")
            .filter(pk=order_id)
            .first()
        )
        if order is None:
            return {"error": ORDER_NOT_FOUND}, 404
        if order.status in CLOSED_ORDER_STATUSES:
            return {"error": CLOSED}, 409
        # Un reembolso total deja el cobro en REFUNDED: ya no hay nada que
        # despachar, aunque cuente como "cobrado" para no volver a cobrarlo.
        if (
            order.payment_status not in CHARGED_PAYMENT_STATUSES
            or order.payment_status == OrderPaymentStatus.REFUNDED
        ):
            return {"error": NOT_PAID}, 409
        error = _transition_error(order, change)
        if error:
            return {"error": error}, 409

        previous_status = order.fulfillment_status
        previous_tracking = order.tracking_number
        now = timezone.now()
        target = change["status"]
        order.fulfillment_status = target
        fields = ["fulfillment_status", "updated_at"]
        if target == FulfillmentStatus.SHIPPED:
            order.carrier = change["carrier"]
            order.tracking_number = change["trackingNumber"]
            fields += ["carrier", "tracking_number"]
            # La fecha de despacho es la del primer envío: corregir la guía no
            # la mueve.
            if order.shipped_at is None:
                order.shipped_at = now
                fields.append("shipped_at")
        elif target == FulfillmentStatus.DELIVERED:
            order.delivered_at = now
            fields.append("delivered_at")
        order.updated_at = now
        order.save(update_fields=fields)

        data = {
            "number": order.number,
            "previousStatus": previous_status,
            "status": target,
            "carrier": order.carrier,
            "trackingNumber": order.tracking_number,
        }
        is_correction = previous_status == target == FulfillmentStatus.SHIPPED
        if is_correction:
            data["previousTrackingNumber"] = previous_tracking
        record_activity(
            actor=actor_email,
            action="FULFILLMENT_UPDATED",
            entity_type="ORDER",
            entity_id=order.pk,
            data=data,
        )

    if target == FulfillmentStatus.SHIPPED:
        _send_shipped_email(order, is_correction)
    return serialize_fulfillment(order), 200


def _customer_email(order: Order) -> str:
    snapshot = (order.data or {}).get("customer") or {}
    email = snapshot.get("email")
    if not email and order.customer is not None:
        email = order.customer.email
    return str(email or "").strip()


def _shipped_email_html(order: Order, is_correction: bool) -> str:
    name = str(((order.data or {}).get("customer") or {}).get("name") or "").strip()
    greeting = format_html("<p>Hi {},</p>", name) if name else ""
    update_note = (
        format_html("<p>{}</p>", "The tracking information for this shipment was updated.")
        if is_correction
        else ""
    )
    url = order.tracking_url
    link = format_html('<p><a href="{}">Track your package</a></p>', url) if url else ""
    return format_html(
        "<h2>Order {} has shipped</h2>"
        "{}"
        "<p>Your TorqueTrack order is on its way.</p>"
        "{}"
        "<p>Carrier: {}<br>Tracking number: {}</p>"
        "{}",
        order.number,
        greeting,
        update_note,
        Carrier(order.carrier).label,
        order.tracking_number,
        link,
    )


def _deliver_shipped_email(number: str, email: str, subject: str, html: str) -> None:
    result = resend.send_email(to=email, subject=subject, html=html)
    if not result.get("sent"):
        # Sin el email del cliente en el log: basta el número del pedido.
        logger.warning("Shipment email for order %s not sent: %s", number, result.get("reason"))


def _send_shipped_email(order: Order, is_correction: bool) -> None:
    """El correo se arma aquí, ya confirmada la transacción, y sale en un hilo
    aparte: el panel no espera a Resend y el hilo no toca la base."""
    email = _customer_email(order)
    if not email:
        logger.info("Order %s shipped without a customer email", order.number)
        return
    run_in_background(
        _deliver_shipped_email,
        order.number,
        email,
        f"Your TorqueTrack order {order.number} has shipped",
        _shipped_email_html(order, is_correction),
    )
