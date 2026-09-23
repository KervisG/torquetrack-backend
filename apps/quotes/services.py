"""Business rules for `quote/request` and `quote/public/<token>` (view +
checkout) — task 6.1 — near-verbatim ports of
`app/api/quote/request/route.ts`, `app/api/quote/public/[token]/route.ts`,
`app/api/quote/public/[token]/checkout/route.ts`, and
`lib/quote.ts`/`lib/email.ts`. `serialize_quote`, `is_expired`,
`render_quote_html`, `send_email`, and `quote_token` are also reused by
`apps/quotes/admin_services.py` (task 6.3) — they live here because
`quote/public/<token>` (this module) needs them first.

Reuses `apps.checkout.services` for the small pure-JS-port helpers
(`money`, `js_number_or`, `random_id`) and for Stripe Checkout Session
creation (`create_stripe_checkout_session`) rather than duplicating them —
cross-app service imports are an established pattern in this codebase
(`apps.checkout.views` already imports from `apps.fitment.services`,
`apps.cart.models`, `apps.customers.models`).
"""
from __future__ import annotations

import secrets

import requests
from django.conf import settings
from django.db import connection
from django.template.loader import render_to_string
from django.utils import timezone

from apps.checkout.models import Order, Payment
from apps.checkout.services import (
    create_stripe_checkout_session,
    js_number_or,
    money,
    next_order_number,
    random_id,
)
from apps.customers.models import Customer
from apps.quotes.models import Quote


def quote_token() -> str:
    """Mirror `lib/quote.ts`'s `quoteToken()`:
    `crypto.randomBytes(24).toString("hex")` -> 48 hex chars."""
    return secrets.token_hex(24)


def next_quote_number() -> str:
    """Mirror the legacy routes' quote-number allocation query."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select coalesce(max((substring(number from '[0-9]+'))::int),10000)+1"
            " as n from quotes"
        )
        (n,) = cursor.fetchone()
    return f"Q{n}"


def send_email(*, to, subject, html, attachments=None, reply_to=None) -> dict:
    """Near-verbatim port of `lib/email.ts`'s `sendEmail` — a direct
    `requests` call to the Resend REST API (no Resend SDK dependency, same
    as the legacy hand-rolled `fetch`)."""
    api_key = settings.RESEND_API_KEY
    from_email = settings.FROM_EMAIL
    if not api_key or not from_email:
        return {"sent": False, "reason": "Email provider not configured"}

    recipients = to if isinstance(to, list) else [to]
    payload = {"from": from_email, "to": recipients, "subject": subject, "html": html}
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = [
            {
                "filename": a["filename"],
                "content": a["content"],
                "content_type": a.get("contentType", "application/pdf"),
            }
            for a in attachments
        ]

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        return {"sent": False, "reason": str(exc)}

    try:
        body = response.json()
    except ValueError:
        body = {}

    if not response.ok:
        return {"sent": False, "reason": body.get("message") or "Email failed"}
    return {"sent": True, "id": body.get("id")}


def serialize_quote(quote: Quote) -> dict:
    """Mirror the legacy routes' `{...q.data, id, number, status, createdAt,
    expiresAt, customer}` shape, preferring the linked `Customer` row's data
    over the jsonb-embedded snapshot (matches the SQL `left join
    customers` + coalesce pattern used everywhere in the legacy quote
    routes)."""
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


def render_quote_html(
    quote: dict, *, public_url: str | None = None, print_mode: bool = False
) -> str:
    """Renders the same visual template as `lib/quote.ts`'s `quoteHtml()`
    (design decision #8: "layout may differ" from the legacy renderer is
    acceptable; line items/totals/customer/vehicle data must match)."""
    customer = quote.get("customer") or {}
    vehicle = quote.get("vehicle") or {}
    totals = quote.get("totals") or {}
    items = []
    for item in quote.get("items") or []:
        qty = js_number_or(item.get("quantity") or item.get("qty"), 1)
        has_unit_price = item.get("unitPrice") is not None
        raw_price = item.get("unitPrice") if has_unit_price else item.get("price")
        unit_price = money(raw_price)
        core_charge = money(item.get("coreCharge"))
        items.append(
            {
                **item,
                "quantity": qty,
                "unitPrice": unit_price,
                "coreCharge": core_charge,
                "lineTotal": money((unit_price + core_charge) * qty),
            }
        )
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
            "print_mode": print_mode,
            "greeting_name": greeting_name,
        },
    )


def create_quote_from_request(payload: dict) -> dict:
    """`POST /api/quote/request` — storefront quote request."""
    customer_in = payload.get("customer") or {}
    name = str(customer_in.get("name") or "").strip()
    email = str(customer_in.get("email") or "").strip()
    phone = str(customer_in.get("phone") or "").strip()
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
    if email:
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
        staff_result = send_email(
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
        customer_result = send_email(
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
    except Exception as exc:  # noqa: BLE001 - mirrors the route's `catch(e:any)`
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
