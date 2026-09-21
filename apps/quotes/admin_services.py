"""Admin quote action business rules (task 6.3): convert/preview/reopen/
send, near-verbatim ports of
`app/api/admin/quotes/[id]/{convert,preview,reopen,send}/route.ts`.

Separate module from `apps/quotes/services.py` (task 6.1's `quote/request`
+ `quote/public/<token>` business rules) for clean commit splitting, same
precedent as Phase 5's `webhook_views.py`. Reuses `services.py`'s
`serialize_quote`, `render_quote_html`, `send_email`, and `quote_token`,
and `apps.checkout.services.next_order_number`/`random_id` rather than
duplicating them.
"""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.backoffice.models import ActivityLog
from apps.checkout.models import Order
from apps.checkout.services import money, next_order_number, random_id
from apps.quotes.models import Quote
from apps.quotes.services import (
    next_quote_number,
    quote_token,
    render_quote_html,
    send_email,
    serialize_quote,
)


def ensure_public_token(quote: Quote) -> str:
    """`POST /api/admin/quotes/[id]/preview` — generate (or reuse) the
    magic-link token and return the public URL."""
    data = quote.data or {}
    token = data.get("publicToken")
    if not token:
        token = quote_token()
        quote.data = {**data, "publicToken": token}
        quote.updated_at = timezone.now()
        quote.save(update_fields=["data", "updated_at"])
    base = settings.APP_URL or "http://localhost:3000"
    return f"{base}/api/quote/public/{token}"


def reopen_quote(quote: Quote) -> None:
    """`POST /api/admin/quotes/[id]/reopen` — explicit admin action, the
    ONLY thing allowed to un-expire a quote (spec: "no reopen MUST occur
    without an explicit admin reopen action")."""
    quote.status = "ACTIVE"
    quote.expires_at = timezone.now() + timezone.timedelta(days=30)
    quote.updated_at = timezone.now()
    quote.save(update_fields=["status", "expires_at", "updated_at"])


def convert_quote_to_order(quote: Quote, actor_username: str) -> dict:
    """`POST /api/admin/quotes/[id]/convert`."""
    if quote.status == "EXPIRED":
        return {"error": "Reopen this quote before converting it.", "status": 400}

    data = quote.data or {}
    existing_number = data.get("orderNumber")
    if existing_number:
        existing = Order.objects.filter(number=existing_number).first()
        if existing is not None:
            existing_order = {"id": existing.pk, "number": existing.number}
            return {"ok": True, "existing": True, "order": existing_order}

    number = next_order_number()
    order_id = random_id("OID")
    order_data = {
        **data,
        "quoteNumber": quote.number,
        "salesRep": actor_username,
        "totals": data.get("totals"),
    }
    Order.objects.create(
        id=order_id,
        number=number,
        customer_id=quote.customer_id,
        status="OPEN",
        payment_status="UNPAID",
        data=order_data,
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )
    quote.status = "CONVERTED"
    quote.data = {**data, "orderNumber": number}
    quote.updated_at = timezone.now()
    quote.save(update_fields=["status", "data", "updated_at"])

    ActivityLog.objects.create(
        actor_id=actor_username,
        action="QUOTE_CONVERTED",
        entity_type="QUOTE",
        entity_id=quote.pk,
        data={"quoteNumber": quote.number, "orderNumber": number},
        created_at=timezone.now(),
    )
    return {"ok": True, "order": {"id": order_id, "number": number}}


def send_quote_email(quote: Quote, actor_username: str) -> dict:
    """`POST /api/admin/quotes/[id]/send`."""
    serialized = serialize_quote(quote)
    customer = serialized.get("customer") or {}
    email = str(customer.get("email") or "").strip()
    if not email:
        return {"error": "Customer email is required", "status": 400}

    ensure_public_token(quote)  # mutates + saves quote.data in place if needed
    base = settings.APP_URL or "http://localhost:3000"
    public_token = (quote.data or {}).get("publicToken")
    url = f"{base}/api/quote/public/{public_token}"
    quote_dict = serialize_quote(quote)
    html = render_quote_html(quote_dict, public_url=url)

    from apps.quotes.pdf import render_quote_pdf_base64

    sent = send_email(
        to=email,
        subject=f"Your TorqueTrack Quote {quote.number}",
        html=html,
        reply_to=settings.REPLY_TO_EMAIL or None,
        attachments=[
            {
                "filename": f"TorqueTrack-{quote.number}.pdf",
                "content": render_quote_pdf_base64(quote_dict),
                "contentType": "application/pdf",
            }
        ],
    )
    if not sent["sent"]:
        return {"error": sent.get("reason") or "Email could not be sent", "status": 502}

    ActivityLog.objects.create(
        actor_id=actor_username,
        action="QUOTE_EMAILED",
        entity_type="QUOTE",
        entity_id=quote.pk,
        data={"quoteNumber": quote.number, "to": email, "emailId": sent.get("id")},
        created_at=timezone.now(),
    )

    data = quote.data or {}
    quote.status = "CONTACTED" if quote.status == "BUILDING" else quote.status
    quote.data = {
        **data,
        "publicToken": public_token,
        "lastEmailedAt": timezone.now().isoformat(),
        "lastEmailedTo": email,
    }
    quote.updated_at = timezone.now()
    quote.save(update_fields=["status", "data", "updated_at"])

    return {"ok": True, "url": url, "emailId": sent.get("id")}


# --- list/create/delete (task 7.6), pinned against
# `app/api/admin/quotes/route.ts` and `app/api/admin/quotes/[id]/route.ts` --


def _num(value, default: float = 0.0) -> float:
    """Mirror JS `Number(x)`, falling back to `default` on `None`/parse
    failure (the `||default` half of each legacy expression is applied by
    the caller, matching JS's per-expression falsy-zero fallback)."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _quote_totals(payload: dict) -> dict:
    """Mirror `app/api/admin/quotes/route.ts`'s inline `totals()` helper."""
    items = payload.get("items") or []

    def qty(item):
        value = item.get("quantity")
        if value is None:
            value = item.get("qty")
        return _num(value, 1.0) or 1.0

    def unit_price(item):
        value = item.get("unitPrice")
        if value is None:
            value = item.get("price")
        return _num(value, 0.0)

    subtotal = money(sum(unit_price(item) * qty(item) for item in items))
    core = money(sum((_num(item.get("coreCharge"), 0.0)) * qty(item) for item in items))
    shipping = money(payload.get("shipping"))
    tax = money(payload.get("tax"))
    return {
        "subtotal": subtotal,
        "core": core,
        "shipping": shipping,
        "tax": tax,
        "total": money(subtotal + core + shipping + tax),
    }


def list_admin_quotes() -> list[dict]:
    """`GET /api/admin/quotes` — expires stale quotes in place, then returns
    every non-archived quote ordered by `created_at`."""
    Quote.objects.filter(
        status__in=["BUILDING", "ACTIVE", "CONTACTED"], expires_at__lt=timezone.now()
    ).update(status="EXPIRED")

    quotes = Quote.objects.select_related("customer").order_by("created_at")
    return [serialize_quote(quote) for quote in quotes if not (quote.data or {}).get("archived")]


def upsert_admin_quote(payload: dict, actor_username: str) -> dict:
    """`POST /api/admin/quotes` — creates a new quote, or updates an
    existing one when `payload["id"]` is present (preserving its `number`/
    `created_at`/`expires_at`)."""
    totals = _quote_totals(payload)
    status = payload.get("status") or "ACTIVE"
    customer_id = payload.get("customerId") or None
    quote_data = {**payload, "totals": totals, "createdBy": actor_username}
    now = timezone.now()

    quote_id = payload.get("id")
    if quote_id:
        quote = Quote.objects.filter(pk=quote_id).first()
        if quote is None:
            return {"error": "Quote not found", "status": 404}

        number = quote.number
        created_at = quote.created_at
        expires_at = quote.expires_at
        quote.customer_id = customer_id
        quote.status = status
        quote.data = quote_data
        quote.updated_at = now
        quote.save(update_fields=["customer_id", "status", "data", "updated_at"])
        updated = True
    else:
        quote_id = random_id("QID")
        number = next_quote_number()
        created_at = now
        expires_at = now + timezone.timedelta(days=30)
        Quote.objects.create(
            id=quote_id,
            number=number,
            customer_id=customer_id,
            status=status,
            data=quote_data,
            created_at=created_at,
            expires_at=expires_at,
            updated_at=now,
        )
        updated = False

    return {
        "updated": updated,
        "quote": {
            **payload,
            "id": quote_id,
            "number": number,
            "totals": totals,
            "createdAt": created_at,
            "expiresAt": expires_at,
        },
    }


def delete_or_archive_quote(quote: Quote, actor_username: str) -> dict:
    """`DELETE /api/admin/quotes/[id]` — archives (never deletes) a quote
    already linked to an Order, to preserve the financial/CRM trail; hard-
    deletes otherwise."""
    data = quote.data or {}
    order_number = data.get("orderNumber")

    if order_number:
        quote.data = {
            **data,
            "archived": True,
            "archivedAt": timezone.now().isoformat(),
            "archivedBy": actor_username,
        }
        quote.updated_at = timezone.now()
        quote.save(update_fields=["data", "updated_at"])
        ActivityLog.objects.create(
            actor_id=actor_username,
            action="QUOTE_ARCHIVED",
            entity_type="QUOTE",
            entity_id=quote.pk,
            data={"number": quote.number, "orderNumber": order_number},
            created_at=timezone.now(),
        )
        return {
            "ok": True,
            "archived": True,
            "quoteNumber": quote.number,
            "orderNumber": order_number,
        }

    number = quote.number
    status = quote.status
    quote_id = quote.pk
    quote.delete()
    ActivityLog.objects.create(
        actor_id=actor_username,
        action="QUOTE_DELETED",
        entity_type="QUOTE",
        entity_id=quote_id,
        data={"number": number, "status": status},
        created_at=timezone.now(),
    )
    return {"ok": True, "archived": False, "deletedQuote": number}
