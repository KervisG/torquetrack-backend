"""Correo de recuperación de carrito abandonado; lo corre la tarea
`send_cart_recovery_emails` cada hora (`CELERY_BEAT_SCHEDULE`).

Abandonado es lo mismo que ve el panel (`abandoned_carts`, la regla de
`classify_cart`). Solo se escribe a una cuenta activa: un carrito invitado no
tiene email. Sale una sola vez por carrito (`Cart.recovery_email_sent_at`);
un carrito que se vacía se borra, así que una compra nueva empieza con otra
fila y otra marca.
"""
import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.html import format_html, format_html_join

from apps.cart.models import Cart
from apps.cart.services.admin import abandoned_carts
from apps.common.emails import branded_email_html
from apps.common.links import app_url
from apps.integrations.email import resend

logger = logging.getLogger(__name__)

# Un carrito abandonado hace más tiempo ya no se recupera con un correo y, sin
# este tope, el primer despliegue le escribiría a todos los carritos viejos.
RECOVERY_MAX_AGE = timedelta(days=7)

# Ruta del carrito en el SPA.
CART_PATH = "/cart"

RECOVERY_SUBJECT = "You left something in your TorqueTrack cart"


def _recovery_candidates(now):
    return (
        abandoned_carts(now)
        .filter(
            user__isnull=False,
            user__active=True,
            recovery_email_sent_at__isnull=True,
            updated_at__gte=now - RECOVERY_MAX_AGE,
        )
        .exclude(user__email="")
        .select_related("user")
        .order_by("updated_at")
    )


def _recovery_email_html(cart: Cart) -> str:
    first_name, _ = cart.user.given_names()
    greeting = format_html("<p>Hi {},</p>", first_name) if first_name else ""
    items = [item for item in (cart.data or {}).get("items") or [] if isinstance(item, dict)]
    rows = format_html_join(
        "",
        "<li>{} {} &times; {}</li>",
        (
            (
                item.get("title") or item.get("partNumber") or item.get("id") or "Item",
                f"({item['partNumber']})" if item.get("partNumber") else "",
                item.get("qty") or 1,
            )
            for item in items
        ),
    )
    body = format_html(
        "<h2>Your cart is waiting</h2>"
        "{}"
        "<p>You left these parts in your TorqueTrack cart:</p>"
        "<ul>{}</ul>"
        '<p><a href="{}">View your cart</a></p>'
        "<p>Prices are confirmed at checkout.</p>",
        greeting,
        rows,
        app_url(CART_PATH),
    )
    return branded_email_html(body)


def send_abandoned_cart_emails(now=None) -> int:
    """Manda el correo a cada carrito que califica y devuelve cuántos salieron.

    La marca se toma con un UPDATE condicional antes de enviar: dos corridas a
    la vez (beat duplicado o un reintento con `acks_late`) no escriben dos
    veces. `update()` no toca `updated_at`, así el carrito sigue abandonado.
    Si Resend no lo envía, la marca se libera y la próxima corrida reintenta.
    """
    now = now or timezone.now()
    sent = 0
    for cart in _recovery_candidates(now):
        claimed = Cart.objects.filter(pk=cart.pk, recovery_email_sent_at__isnull=True).update(
            recovery_email_sent_at=now
        )
        if not claimed:
            continue
        result = resend.send_email(
            to=cart.user.email, subject=RECOVERY_SUBJECT, html=_recovery_email_html(cart)
        )
        if not result.get("sent"):
            Cart.objects.filter(pk=cart.pk, recovery_email_sent_at=now).update(
                recovery_email_sent_at=None
            )
            # Sin el email del cliente en el log: basta el id del carrito.
            logger.warning(
                "Cart recovery email for cart %s not sent: %s", cart.pk, result.get("reason")
            )
            continue
        sent += 1
    return sent
