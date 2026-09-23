"""Reglas de negocio de `quote/request` y `quote/public/<token>` (vista y
checkout). `serialize_quote`, `is_expired`, `render_quote_html`,
y `quote_token` también los usa `apps/quotes/admin_services.py`; viven aquí
porque `quote/public/<token>` los necesita primero. Los correos salen por el
adaptador de Resend (`apps.integrations.email.resend`).

Reutiliza de `apps.checkout.services` los helpers numéricos (`money`,
`js_number_or`, `random_id`) y la creación de la Checkout Session de Stripe
(`create_stripe_checkout_session`) en lugar de duplicarlos; importar
servicios entre apps es un patrón habitual del proyecto.
"""
from __future__ import annotations

import secrets

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from apps.checkout.models import Order, Payment
from apps.checkout.services import (
    create_stripe_checkout_session,
    js_number_or,
    linked_customer,
    money,
    next_document_number,
    next_order_number,
    random_id,
)
from apps.customers.models import Customer
from apps.integrations.email import resend
from apps.integrations.exceptions import ProviderError
from apps.quotes.models import Quote


def quote_token() -> str:
    """Token del magic link: 24 bytes aleatorios en hexadecimal (48
    caracteres)."""
    return secrets.token_hex(24)


def next_quote_number() -> str:
    return next_document_number("quote", "Q")


def _app_base_url() -> str:
    return (settings.APP_URL or "http://localhost:5173").rstrip("/")


def public_quote_url(token: str) -> str:
    """Enlace que recibe el cliente: la página `/quote/<token>` del SPA, que
    lee `GET /api/quote/public/<token>/details/`. Nunca el endpoint HTML."""
    return f"{_app_base_url()}/quote/{token}"


def public_quote_pdf_url(token: str) -> str:
    """El PDF lo sirve la API, así que su enlace no pasa por el SPA."""
    return f"{_app_base_url()}/api/quote/public/{token}/pdf/"


def serialize_quote(quote: Quote) -> dict:
    """Serializa la cotización como `{...data, id, number, status, createdAt,
    expiresAt, customer}`. Para `customer` se prefieren los datos de la fila
    `Customer` vinculada sobre el snapshot guardado en el jsonb."""
    data = quote.data or {}
    if quote.customer_id and quote.customer is not None:
        customer = {**(quote.customer.data or {}), "email": quote.customer.email}
    else:
        customer = data.get("customer")

    return {
        **data,
        "id": quote.pk,
        "number": quote.number,
        "status": quote.status,
        "createdAt": quote.created_at,
        "expiresAt": quote.expires_at,
        "customer": customer,
    }


def is_expired(quote: Quote) -> bool:
    return bool(quote.expires_at and quote.expires_at < timezone.now())


def _quote_line(item: dict) -> dict:
    """Normaliza una línea (`quantity`/`qty`, `unitPrice`/`price`) y calcula
    su total en el backend: ni el correo ni el SPA recalculan dinero."""
    qty = js_number_or(item.get("quantity") or item.get("qty"), 1)
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
    """`GET /api/quote/public/<token>/details/`: solo lo que ve el cliente.
    Sin token, memo interno, vendedor ni email, porque el enlace se reenvía."""
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
    }


def render_quote_html(
    quote: dict,
    *,
    public_url: str | None = None,
    pdf_url: str | None = None,
    print_mode: bool = False,
) -> str:
    """Renderiza la plantilla `quotes/quote.html`, compartida por la página
    pública, el PDF y el email de la cotización. `pdf_url` por defecto es
    `<public_url>/pdf`, que solo vale cuando `public_url` es la ruta HTML de
    la API; el correo manda el suyo porque enlaza al SPA."""
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


def create_quote_from_request(payload: dict, user=None) -> dict:
    """`POST /api/quote/request` — storefront quote request.

    Con un `Customer` vinculado a la sesión, la cotización es de ese perfil:
    el email es el de la cuenta, el nombre y el teléfono del body solo
    completan el snapshot y el perfil no se reescribe.
    """
    customer_in = payload.get("customer")
    if not isinstance(customer_in, dict):
        customer_in = {}
    profile = linked_customer(user)
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
        quantity = max(1, int(js_number_or(raw_item.get("quantity") or raw_item.get("qty"), 1)))
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
        customer_id = _resolve_or_merge_customer(name, email, phone)

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
    cart_id = payload.get("cartId")
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


def _resolve_or_merge_customer(name, email, phone) -> str:
    # Solo perfiles invitados: un email tipeado en el checkout no prueba nada,
    # así que nunca debe mezclarse con el perfil de una cuenta registrada.
    existing = Customer.objects.filter(email__iexact=email, user__isnull=True).first()
    if existing:
        existing.data = {**(existing.data or {}), "name": name, "email": email, "phone": phone}
        existing.updated_at = timezone.now()
        existing.save(update_fields=["data", "updated_at"])
        return existing.pk

    customer_id = random_id("C")
    now = timezone.now()
    Customer.objects.create(
        id=customer_id,
        email=email,
        data={"id": customer_id, "name": name, "email": email, "phone": phone},
        created_at=now,
        updated_at=now,
    )
    return customer_id


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


def checkout_from_quote(quote: Quote) -> dict:
    """`POST /api/quote/public/<token>/checkout`."""
    if is_expired(quote):
        return {"error": "This quote has expired", "status": 409}

    order = (
        Order.objects.filter(data__quoteNumber=quote.number, payment_status="UNPAID")
        .order_by("-created_at")
        .first()
    )
    data = quote.data or {}
    if order is None:
        number = next_order_number()
        order_id = random_id("OID")
        serialized = serialize_quote(quote)
        order_data = {
            **data,
            "customer": serialized.get("customer") or data.get("customer") or {},
            "quoteNumber": quote.number,
            "salesRep": data.get("createdBy") or "Online Quote",
        }
        order = Order.objects.create(
            id=order_id,
            number=number,
            customer_id=quote.customer_id,
            status="PENDING_PAYMENT",
            payment_status="UNPAID",
            data=order_data,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        quote.status = "CONVERTED"
        quote.data = {**data, "orderNumber": number}
        quote.updated_at = timezone.now()
        quote.save(update_fields=["status", "data", "updated_at"])

    try:
        session_payload = {"id": order.pk, "number": order.number, **(order.data or {})}
        session = create_stripe_checkout_session(session_payload)
    except ProviderError as exc:
        return {"error": str(exc) or "Could not create secure checkout", "status": 502}

    Payment.objects.create(
        id=random_id("PAY"),
        order=order,
        provider="stripe",
        provider_id=session["id"],
        status="PENDING",
        amount=money((order.data or {}).get("totals", {}).get("total")),
        data={"sessionId": session["id"], "source": "PUBLIC_QUOTE"},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )
    return {"ok": True, "url": session["url"], "orderNumber": order.number}
