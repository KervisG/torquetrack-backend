"""Cotizaciones del storefront: solicitud, enlace público y checkout."""
from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from apps.checkout.models import Order
from apps.checkout.services import (
    PAYMENT_START_FAILED,
    cancel_unpaid_order,
    next_order_number,
    start_stripe_payment,
)
from apps.common.ids import random_id
from apps.common.links import app_url
from apps.common.numbers import money, to_number
from apps.customers.services import customer_for_user, resolve_guest_customer
from apps.integrations.email import resend
from apps.integrations.exceptions import ProviderError
from apps.numbering.services import next_document_number
from apps.quotes.models import Quote

logger = logging.getLogger(__name__)


def quote_token() -> str:
    return secrets.token_hex(24)


def next_quote_number() -> str:
    return next_document_number("quote", "Q")


def public_quote_url(token: str) -> str:
    """El cliente recibe la página del SPA, nunca el endpoint HTML de la API."""
    return app_url(f"/quote/{token}")


def public_quote_pdf_url(token: str) -> str:
    """El PDF lo sirve la API, así que su enlace no pasa por el SPA."""
    return app_url(f"/api/quote/public/{token}/pdf/")


def serialize_quote(quote: Quote) -> dict:
    """El snapshot de `customer` gana sobre el perfil vinculado: una solicitud
    invitada no reescribe el perfil, así que lo que escribió el cliente vive
    solo ahí. El email siempre es el del perfil."""
    data = quote.data or {}
    if quote.customer_id and quote.customer is not None:
        customer = {
            **(quote.customer.data or {}),
            **(data.get("customer") or {}),
            "email": quote.customer.email,
        }
    else:
        customer = data.get("customer")

    return {
        **data,
        "id": quote.pk,
        "number": quote.number,
        "status": effective_quote_status(quote),
        "createdAt": quote.created_at,
        "expiresAt": quote.expires_at,
        "customer": customer,
    }


def is_expired(quote: Quote) -> bool:
    return bool(quote.expires_at and quote.expires_at < timezone.now())


# Estados abiertos que el vencimiento convierte en `EXPIRED`; los cerrados
# (`CONVERTED`, `LOST`...) conservan el suyo.
EXPIRABLE_QUOTE_STATUSES = ("BUILDING", "ACTIVE", "CONTACTED")


def effective_quote_status(quote: Quote) -> str:
    """El vencimiento se calcula al leer: ningún GET persiste `EXPIRED`."""
    if quote.status in EXPIRABLE_QUOTE_STATUSES and is_expired(quote):
        return "EXPIRED"
    return quote.status


def unexpired_quotes_q() -> Q:
    return Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())


def expire_stale_quotes() -> int:
    return Quote.objects.filter(
        status__in=EXPIRABLE_QUOTE_STATUSES, expires_at__lt=timezone.now()
    ).update(status="EXPIRED", updated_at=timezone.now())


def _quote_line(item: dict) -> dict:
    """El total de la línea se calcula aquí: ni el correo ni el SPA recalculan dinero."""
    qty = to_number(item.get("quantity") or item.get("qty"), 1)
    has_unit_price = item.get("unitPrice") is not None
    raw_price = item.get("unitPrice") if has_unit_price else item.get("price")
    unit_price = money(raw_price)
    core_charge = money(item.get("coreCharge"))
    return {
        **item,
        "quantity": qty,
        "unitPrice": unit_price,
        "coreCharge": core_charge,
        "lineTotal": money((unit_price + core_charge) * qty),
    }


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


def render_quote_html(
    quote: dict,
    *,
    public_url: str | None = None,
    pdf_url: str | None = None,
    print_mode: bool = False,
) -> str:
    """El `pdf_url` por defecto solo vale cuando `public_url` es la ruta HTML
    de la API; el correo manda el suyo porque enlaza al SPA."""
    customer = quote.get("customer") or {}
    vehicle = quote.get("vehicle") or {}
    totals = quote.get("totals") or {}
    items = [_quote_line(item) for item in quote.get("items") or []]
    greeting_name = (customer.get("name") or customer.get("company") or "Customer").split(" ")[0]
    return render_to_string(
        "quotes/quote.html",
        {
            "quote": quote,
            "customer": customer,
            "vehicle": vehicle,
            "totals": totals,
            "items": items,
            "public_url": public_url or "#",
            "pdf_url": pdf_url or (f"{public_url}/pdf" if public_url else "#"),
            "print_mode": print_mode,
            "greeting_name": greeting_name,
        },
    )


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

    ids = [str(x.get("productId") or x.get("id")) for x in raw_items]
    products_by_id = {p.id: (p.data or {}) for p in _active_products(ids)}

    items = []
    subtotal = 0.0
    core_total = 0.0
    for raw_item in raw_items:
        product_data = products_by_id.get(str(raw_item.get("productId") or raw_item.get("id")))
        if not product_data:
            continue
        quantity = max(1, int(to_number(raw_item.get("quantity") or raw_item.get("qty"), 1)))
        unit_price = money(product_data.get("price"))
        core_charge = money(product_data.get("coreCharge"))
        subtotal += unit_price * quantity
        core_total += core_charge * quantity
        items.append(
            {
                "productId": product_data.get("id"),
                "title": product_data.get("title"),
                "partNumber": product_data.get("partNumber") or product_data.get("oemPart") or "",
                "quantity": quantity,
                "unitPrice": unit_price,
                "coreCharge": core_charge,
            }
        )

    if not items:
        return {"error": "No valid products", "status": 400}

    customer_id = None
    if profile is not None:
        customer_id = profile.pk
    elif email:
        customer_id = resolve_guest_customer({"name": name, "email": email, "phone": phone})

    quote_id = random_id("QID")
    number = next_quote_number()
    totals = {
        "subtotal": money(subtotal),
        "core": money(core_total),
        "shipping": 0,
        "tax": 0,
        "total": money(subtotal + core_total),
    }
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
        items_html = "<br>".join(
            f"{i['quantity']} × {i['title']} ({i['partNumber']})" for i in items
        )
        staff_result = resend.send_email(
            to=sales_email,
            subject=f"New TorqueTrack Quote Request {number}",
            html=(
                f"<h2>New Quote Request {number}</h2>"
                f"<p><b>{name}</b><br>{email or 'No email'}<br>{phone or 'No phone'}</p>"
                f"<p>{items_html}</p>"
                f"<p>Total before tax/shipping: ${totals['total']:.2f}</p>"
            ),
        )

    customer_result = {"sent": False}
    if email:
        customer_result = resend.send_email(
            to=email,
            subject=f"TorqueTrack received your quote request {number}",
            html=(
                "<h2>We received your quote request</h2>"
                f"<p>Thank you {name}. Your reference is <b>{number}</b>. A "
                "TorqueTrack representative will contact you to confirm "
                "fitment, pricing, shipping and tax.</p>"
            ),
        )

    return {
        "ok": True,
        "quoteId": quote_id,
        "quoteNumber": number,
        "email": {"staff": staff_result["sent"], "customer": customer_result["sent"]},
    }


def _active_products(ids):
    from apps.catalog.models import Product

    return Product.objects.filter(id__in=ids, active=True)


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
        data__quoteNumber=quote.number, payment_status="PAID"
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
        if any(order.payment_status == "PAID" for order in orders):
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
