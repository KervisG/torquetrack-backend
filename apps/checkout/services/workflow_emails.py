"""Correos de los casos de core y de devolución de un pedido.

El equipo recibe el aviso en `CORES_EMAIL` o `RETURNS_EMAIL`, y el cliente
recibe cada cambio de estado con la respuesta dirigida a ese mismo buzón. Sin
el buzón configurado no sale el aviso interno y la respuesta del cliente cae
en `REPLY_TO_EMAIL`. Los correos se arman aquí y salen en un hilo aparte: ni
el panel ni el webhook de Stripe esperan a Resend.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils.html import format_html

from apps.authentication.utils.background import run_in_background
from apps.checkout.models import CoreStatus, Order, ReturnStatus
from apps.common.emails import branded_email_html
from apps.common.numbers import money_decimal
from apps.integrations.email import resend

logger = logging.getLogger(__name__)

# Qué le decimos al cliente en cada estado. No promete plazos ni condiciones:
# esas las da el equipo al responder.
_CORE_MESSAGES = {
    CoreStatus.AWAITING_CORE: "We are waiting for your core.",
    CoreStatus.IN_TRANSIT: "Your core is on its way to us.",
    CoreStatus.RECEIVED: "We received your core.",
    CoreStatus.INSPECTING: "Your core is being inspected.",
    CoreStatus.ACCEPTED: "Your core passed inspection. We will refund your core charge.",
    CoreStatus.REJECTED: (
        "Your core did not pass inspection, so the core charge cannot be refunded."
    ),
    CoreStatus.REFUNDED: "Your core charge was refunded.",
}
_RETURN_MESSAGES = {
    ReturnStatus.REQUESTED: "We received your return request.",
    ReturnStatus.APPROVED: "Your return was approved.",
    ReturnStatus.IN_TRANSIT: "Your return is on its way to us.",
    ReturnStatus.RECEIVED: "We received your return.",
    ReturnStatus.INSPECTING: "Your return is being inspected.",
    ReturnStatus.REFUNDED: "Your return was refunded.",
    ReturnStatus.REJECTED: "Your return was not accepted.",
}
_QUESTIONS = "Reply to this email if you have any questions."


def _customer(order: Order) -> dict:
    snapshot = (order.data or {}).get("customer") or {}
    email = snapshot.get("email")
    if not email and order.customer is not None:
        email = order.customer.email
    return {"name": str(snapshot.get("name") or "").strip(), "email": str(email or "").strip()}


def _amount(case: dict) -> str:
    amount = money_decimal(case.get("amount") or 0)
    return f"${amount:,.2f}" if amount > 0 else ""


def _deliver(number: str, kind: str, *, to: str, subject: str, html: str, reply_to) -> None:
    result = resend.send_email(to=to, subject=subject, html=html, reply_to=reply_to)
    if not result.get("sent"):
        # Sin el email del destinatario en el log: basta el número del pedido.
        logger.warning("%s email for order %s not sent: %s", kind, number, result.get("reason"))


def _send(order: Order, kind: str, *, to: str, subject: str, body, reply_to=None) -> None:
    run_in_background(
        _deliver,
        order.number,
        kind,
        to=to,
        subject=subject,
        html=branded_email_html(body),
        reply_to=reply_to or None,
    )


def _notify_team(order: Order, kind: str, mailbox: str, subject: str, detail) -> None:
    if not mailbox:
        return
    customer = _customer(order)
    body = format_html(
        "<h2>{}</h2><p>Customer: {} {}</p>{}",
        subject,
        customer["name"] or "—",
        customer["email"],
        detail,
    )
    _send(order, kind, to=mailbox, subject=subject, body=body, reply_to=customer["email"])


def _notify_customer(order: Order, kind: str, mailbox: str, subject: str, message) -> None:
    customer = _customer(order)
    if not customer["email"]:
        logger.info("Order %s has no customer email for a %s update", order.number, kind)
        return
    greeting = format_html("<p>Hi {},</p>", customer["name"]) if customer["name"] else ""
    body = format_html(
        "<h2>Order {}</h2>{}<p>{}</p><p>{}</p>", order.number, greeting, message, _QUESTIONS
    )
    _send(
        order,
        kind,
        to=customer["email"],
        subject=subject,
        body=body,
        reply_to=mailbox or settings.REPLY_TO_EMAIL,
    )


def notify_core_opened(order: Order) -> None:
    """Un pedido pagado con core charge: el equipo sabe que espera una pieza
    y el cliente, cómo recuperar su dinero."""
    case = (order.data or {}).get("coreCase") or {}
    amount = _amount(case)
    _notify_team(
        order,
        "Core",
        settings.CORES_EMAIL,
        f"Core expected for Order {order.number}",
        format_html("<p>Core charge: {}</p>", amount or "—"),
    )
    _notify_customer(
        order,
        "Core",
        settings.CORES_EMAIL,
        f"Your core return for TorqueTrack Order {order.number}",
        format_html(
            "Your order includes a refundable core charge{}. Send us your old part and we "
            "refund it once it passes inspection. Reply to this email and we will send you "
            "the return instructions.",
            format_html(" of {}", amount) if amount else "",
        ),
    )


def _status(case) -> str:
    return str((case or {}).get("status") or "").upper()


def notify_workflow_changes(order: Order, previous: dict, patch: dict) -> None:
    """Después de guardar un cambio del panel: escribe solo por lo que cambió
    de estado. `previous` es `Order.data` antes del cambio."""
    core = patch.get("coreCase")
    if core and _status(core) != _status(previous.get("coreCase")):
        message = _CORE_MESSAGES[CoreStatus(_status(core))]
        amount = _amount(core) if _status(core) == CoreStatus.REFUNDED else ""
        _notify_customer(
            order,
            "Core",
            settings.CORES_EMAIL,
            f"Core update for TorqueTrack Order {order.number}",
            format_html("{} Amount: {}.", message, amount) if amount else message,
        )

    returned = patch.get("returnCase")
    if returned and _status(returned) != _status(previous.get("returnCase")):
        if not previous.get("returnCase"):
            _notify_team(
                order,
                "Return",
                settings.RETURNS_EMAIL,
                f"Return opened for Order {order.number}",
                format_html(
                    "<p>Status: {}</p><p>Reason: {}</p>",
                    _status(returned),
                    str(returned.get("reason") or "—"),
                ),
            )
        _notify_customer(
            order,
            "Return",
            settings.RETURNS_EMAIL,
            f"Return update for TorqueTrack Order {order.number}",
            _RETURN_MESSAGES[ReturnStatus(_status(returned))],
        )
