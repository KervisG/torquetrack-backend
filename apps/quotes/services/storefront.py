"""Cotizaciones del storefront: solicitud, enlace público y checkout."""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from apps.catalog.services.pricing import (
    STOREFRONT_QUANTITY_ERROR,
    InvalidQuantity,
    UnpricedProducts,
    build_totals,
    price_lines,
    serialize_totals,
)
from apps.checkout.models import Order
from apps.checkout.services import (
    CHARGED_PAYMENT_STATUSES,
    PAYMENT_START_FAILED,
    cancel_unpaid_order,
    next_order_number,
    start_stripe_payment,
)
from apps.common.ids import random_id
from apps.common.numbers import money
from apps.customers.services import customer_for_user, resolve_guest_customer
from apps.integrations.email import resend
from apps.integrations.exceptions import ProviderError
from apps.quotes.models import Quote
from apps.quotes.services.lifecycle import is_expired, next_quote_number
from apps.quotes.services.rendering import _quote_line, serialize_quote

logger = logging.getLogger(__name__)


_PUBLIC_LINE_KEYS = ("title", "partNumber", "quantity", "unitPrice", "coreCharge", "lineTotal")


def serialize_public_quote(quote: Quote) -> dict:
    """Sin token, memo interno, vendedor ni email, porque el enlace se reenvía."""
    serialized = serialize_quote(quote)
    customer = serialized.get("customer") or {}
    lines = [_quote_line(item) for item in serialized.get("items") or []]
    return {
        "number": quote.number,
        "status": quote.status,
        "createdAt": quote.created_at,
        "expiresAt": quote.expires_at,
        "customer": {
            "name": str(customer.get("name") or ""),
            "company": str(customer.get("company") or ""),
        },
        "vehicle": serialized.get("vehicle") or {},
        "items": [{key: line.get(key) for key in _PUBLIC_LINE_KEYS} for line in lines],
        "totals": serialized.get("totals") or {},
        "payable": is_quote_payable(quote),
    }


def create_quote_from_request(payload: dict, user=None, cart_id=None) -> dict:
    """Con un `Customer` vinculado a la sesión, la cotización es de ese perfil:
    el email es el de la cuenta, el nombre y el teléfono del body solo
    completan el snapshot y el perfil no se reescribe.

    `cart_id` es el carrito de la sesión; el `cartId` del body se ignora.
    """
    customer_in = payload.get("customer")
    if not isinstance(customer_in, dict):
        customer_in = {}
    profile = customer_for_user(user)
    profile_data = (profile.data or {}) if profile is not None else {}
    name = str(customer_in.get("name") or profile_data.get("name") or "").strip()
    email = str(customer_in.get("email") or "").strip()
    phone = str(customer_in.get("phone") or profile_data.get("phone") or "").strip()
    if profile is not None:
        email = profile.email or user.email
    if not name:
        return {"error": "Name or company is required", "status": 400}

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return {"error": "Cart is empty", "status": 400}

    # El precio es siempre el del catálogo, con la misma regla de cantidad
    # que el checkout: el cliente no fija precios en una solicitud.
    try:
        priced = price_lines(raw_items)
    except InvalidQuantity:
        return {"error": STOREFRONT_QUANTITY_ERROR, "status": 400}
    except UnpricedProducts as exc:
        detail = ", ".join(
            line.product.get("partNumber") or line.product.get("title") or str(line.product_id)
            for line in exc.lines
        )
        return {
            "error": f"These items have no valid price and cannot be quoted online: {detail}",
            "status": 409,
        }
    items = [
        {
            "productId": line.product.get("id"),
            "title": line.product.get("title"),
            "partNumber": line.product.get("partNumber") or line.product.get("oemPart") or "",
            "quantity": line.quantity,
            "unitPrice": money(line.unit_price),
            "coreCharge": money(line.core_charge),
        }
        for line in priced.lines
    ]

    if not items:
        return {"error": "No valid products", "status": 400}

    customer_id = None
    if profile is not None:
        customer_id = profile.pk
    elif email:
        customer_id = resolve_guest_customer({"name": name, "email": email, "phone": phone})

    quote_id = random_id("QID")
    number = next_quote_number()
    # Envío e impuesto los fija el staff al preparar la cotización.
    totals = serialize_totals(build_totals(priced.subtotal, priced.core))
    memo = "Storefront quote request"
    if cart_id:
        memo += f" • Cart {cart_id}"

    data = {
        "customer": {"name": name, "email": email, "phone": phone},
        "vehicle": payload.get("vehicle") or {},
        "items": items,
        "totals": totals,
        "memo": memo,
        "source": "STOREFRONT_REQUEST",
    }

    now = timezone.now()
    Quote.objects.create(
        id=quote_id,
        number=number,
        customer_id=customer_id,
        status="BUILDING",
        data=data,
        created_at=now,
        expires_at=now + timezone.timedelta(days=30),
        updated_at=now,
    )

    if cart_id:
        customer_summary = {"name": name, "email": email, "phone": phone}
        _link_cart_to_quote(cart_id, quote_id, number, customer_summary)

    sales_email = settings.SALES_EMAIL
    staff_result = {"sent": False}
    if sales_email:
        # Todo dato del cliente o de la pieza pasa por `format_html`: el
        # formulario es público y el correo se abre en la bandeja de ventas.
        items_html = format_html_join(
            mark_safe("<br>"),
            "{} × {} ({})",
            ((i["quantity"], i["title"], i["partNumber"]) for i in items),
        )
        staff_result = resend.send_email(
            to=sales_email,
            subject=f"New TorqueTrack Quote Request {number}",
            html=format_html(
                "<h2>New Quote Request {}</h2>"
                "<p><b>{}</b><br>{}<br>{}</p>"
                "<p>{}</p>"
                "<p>Total before tax/shipping: ${}</p>",
                number,
                name,
                email or "No email",
                phone or "No phone",
                items_html,
                f"{totals['total']:.2f}",
            ),
        )

    customer_result = {"sent": False}
    if email:
        customer_result = resend.send_email(
            to=email,
            subject=f"TorqueTrack received your quote request {number}",
            html=format_html(
                "<h2>We received your quote request</h2>"
                "<p>Thank you {}. Your reference is <b>{}</b>. A "
                "TorqueTrack representative will contact you to confirm "
                "fitment, pricing, shipping and tax.</p>",
                name,
                number,
            ),
        )

    return {
        "ok": True,
        "quoteId": quote_id,
        "quoteNumber": number,
        "email": {"staff": staff_result["sent"], "customer": customer_result["sent"]},
    }


def _link_cart_to_quote(cart_id, quote_id, quote_number, customer):
    from apps.cart.models import Cart

    cart = Cart.objects.filter(pk=cart_id).first()
    if cart is None:
        return
    cart.data = {
        **(cart.data or {}),
        "stage": "BUILDING_QUOTE",
        "status": "BUILDING_QUOTE",
        "quoteId": quote_id,
        "quoteNumber": quote_number,
        "customer": customer,
    }
    cart.updated_at = timezone.now()
    cart.save(update_fields=["data", "updated_at"])


_TOTAL_KEYS = ("subtotal", "core", "shipping", "tax", "total")


def _matches_quote(order: Order, quote_data: dict) -> bool:
    """El pedido cobra exactamente lo cotizado: mismas líneas y mismos
    totales. Si el staff editó la cotización, el pedido quedó viejo."""
    order_data = order.data or {}
    order_totals = order_data.get("totals") or {}
    quote_totals = quote_data.get("totals") or {}
    return order_data.get("items") == quote_data.get("items") and all(
        money(order_totals.get(key)) == money(quote_totals.get(key)) for key in _TOTAL_KEYS
    )


# `CONVERTED` sigue siendo pagable: el checkout la convierte antes de abrir
# Stripe, así que un reintento (Stripe caído, sesión abandonada) reusa el
# pedido. Un pedido ya pagado se rechaza aparte.
PAYABLE_QUOTE_STATUSES = frozenset({"ACTIVE", "CONTACTED", "CONVERTED"})


def _checkout_refusal(quote: Quote) -> dict | None:
    """El vencimiento responde 410, igual que las vistas públicas por token."""
    if is_expired(quote) or quote.status == "EXPIRED":
        return {"error": "This quote has expired", "status": 410}
    if quote.status == "BUILDING":
        return {
            "error": "This quote is still being prepared. Contact TorqueTrack to finalize it.",
            "status": 409,
        }
    if quote.status not in PAYABLE_QUOTE_STATUSES:
        return {
            "error": "This quote is closed. Contact TorqueTrack for a new quote.",
            "status": 409,
        }
    return None


def is_quote_payable(quote: Quote) -> bool:
    """La página pública muestra el botón de pago con esta misma regla, así el
    SPA no la repite."""
    if _checkout_refusal(quote) is not None:
        return False
    return not Order.objects.filter(
        data__quoteNumber=quote.number, payment_status__in=CHARGED_PAYMENT_STATUSES
    ).exists()


def checkout_from_quote(quote: Quote) -> dict:
    """El token sigue vivo después de pagar, así que una cotización con un
    pedido PAID se rechaza con 409 en vez de abrir otro cobro. Se reusa el
    pedido sin pagar que coincide con la cotización; uno viejo (la cotización
    cambió) se cancela junto con sus sesiones pendientes. La cotización y sus
    pedidos se bloquean para que dos clics no creen dos pedidos.
    """
    refusal = _checkout_refusal(quote)
    if refusal is not None:
        return refusal

    with transaction.atomic():
        quote = Quote.objects.select_for_update().get(pk=quote.pk)
        # Se vuelve a mirar con la fila bloqueada: el staff pudo cerrarla
        # entre la lectura del token y este punto.
        refusal = _checkout_refusal(quote)
        if refusal is not None:
            return refusal
        orders = list(
            Order.objects.select_for_update()
            .filter(data__quoteNumber=quote.number)
            .order_by("-created_at")
        )
        # Un pedido reembolsado sigue cobrado: la cotización no se vuelve a pagar.
        if any(order.payment_status in CHARGED_PAYMENT_STATUSES for order in orders):
            return {"error": "This quote has already been paid", "status": 409}

        data = quote.data or {}
        order = None
        for candidate in orders:
            if candidate.payment_status != "UNPAID" or candidate.status == "CANCELLED":
                continue
            if _matches_quote(candidate, data):
                order = order or candidate
            else:
                cancel_unpaid_order(candidate, "QUOTE_CHANGED")

        if order is None:
            serialized = serialize_quote(quote)
            order = Order.objects.create(
                id=random_id("OID"),
                number=next_order_number(),
                customer_id=quote.customer_id,
                status="PENDING_PAYMENT",
                payment_status="UNPAID",
                data={
                    **data,
                    "customer": serialized.get("customer") or data.get("customer") or {},
                    "quoteNumber": quote.number,
                    "salesRep": data.get("createdBy") or "Online Quote",
                },
            )
        if quote.status != "CONVERTED" or data.get("orderNumber") != order.number:
            quote.status = "CONVERTED"
            quote.data = {**data, "orderNumber": order.number}
            quote.updated_at = timezone.now()
            quote.save(update_fields=["status", "data", "updated_at"])

    try:
        _, session = start_stripe_payment(order, data={"source": "PUBLIC_QUOTE"})
    except ProviderError as exc:
        # El pedido queda sin pagar y coincide con la cotización: el próximo
        # intento lo reusa.
        logger.warning("Stripe checkout for quote %s failed: %s", quote.number, exc)
        return {"error": PAYMENT_START_FAILED, "status": 502}

    return {"ok": True, "url": session["url"], "orderNumber": order.number}
