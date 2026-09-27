"""Reglas de negocio de las cotizaciones en el panel de administración."""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import Order
from apps.checkout.services import next_order_number
from apps.common.ids import random_id
from apps.common.numbers import money, to_number
from apps.integrations.email import resend
from apps.quotes.models import Quote
from apps.quotes.services.lifecycle import effective_quote_status, next_quote_number, quote_token
from apps.quotes.services.pdf import render_quote_pdf_base64
from apps.quotes.services.rendering import (
    public_quote_pdf_url,
    public_quote_url,
    render_quote_html,
    serialize_quote,
)

# Claves que escribe el sistema y no el editor del panel. El editor manda la
# cotización completa; sin conservarlas, un update rompería el enlace ya
# enviado y el convert idempotente (`orderNumber`).
_SYSTEM_QUOTE_KEYS = ("publicToken", "orderNumber", "lastEmailedAt", "lastEmailedTo", "source")


def ensure_public_token(quote: Quote) -> str:
    data = quote.data or {}
    token = data.get("publicToken")
    if not token:
        token = quote_token()
        quote.data = {**data, "publicToken": token}
        quote.updated_at = timezone.now()
        quote.save(update_fields=["data", "updated_at"])
    return public_quote_url(token)


def reopen_quote(quote: Quote) -> None:
    """Única forma de reactivar una cotización vencida: nada la reabre de forma
    automática."""
    quote.status = "ACTIVE"
    quote.expires_at = timezone.now() + timezone.timedelta(days=30)
    quote.updated_at = timezone.now()
    quote.save(update_fields=["status", "expires_at", "updated_at"])


def convert_quote_to_order(quote: Quote, actor_email: str) -> dict:
    if effective_quote_status(quote) == "EXPIRED":
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
        "salesRep": actor_email,
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

    record_activity(
        actor=actor_email,
        action="QUOTE_CONVERTED",
        entity_type="QUOTE",
        entity_id=quote.pk,
        data={"quoteNumber": quote.number, "orderNumber": number},
    )
    return {"ok": True, "order": {"id": order_id, "number": number}}


def send_quote_email(quote: Quote, actor_email: str) -> dict:
    serialized = serialize_quote(quote)
    customer = serialized.get("customer") or {}
    email = str(customer.get("email") or "").strip()
    if not email:
        return {"error": "Customer email is required", "status": 400}
    # Sin proveedor el envío fallaría igual: se corta antes de generar el PDF
    # para que el panel reciba el motivo aunque WeasyPrint no esté instalado.
    if not resend.is_configured():
        return {"error": "Email provider not configured", "status": 502}

    url = ensure_public_token(quote)  # también guarda el token si faltaba
    public_token = (quote.data or {}).get("publicToken")
    quote_dict = serialize_quote(quote)
    html = render_quote_html(quote_dict, public_url=url, pdf_url=public_quote_pdf_url(public_token))

    sent = resend.send_email(
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

    record_activity(
        actor=actor_email,
        action="QUOTE_EMAILED",
        entity_type="QUOTE",
        entity_id=quote.pk,
        data={"quoteNumber": quote.number, "to": email, "emailId": sent.get("id")},
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


# --- listado, alta y baja ---


def _quote_totals(payload: dict) -> dict:
    items = payload.get("items") or []

    def qty(item):
        value = item.get("quantity")
        if value is None:
            value = item.get("qty")
        return to_number(value, 1.0) or 1.0

    def unit_price(item):
        value = item.get("unitPrice")
        if value is None:
            value = item.get("price")
        return to_number(value, 0.0)

    subtotal = money(sum(unit_price(item) * qty(item) for item in items))
    core = money(sum(to_number(item.get("coreCharge"), 0.0) * qty(item) for item in items))
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
    """Solo lectura: `serialize_quote` ya informa `EXPIRED` a las vencidas."""
    quotes = Quote.objects.select_related("customer").order_by("created_at")
    return [serialize_quote(quote) for quote in quotes if not (quote.data or {}).get("archived")]


def upsert_admin_quote(payload: dict, actor_email: str) -> dict:
    """Al actualizar se conservan `number`, `created_at` y `expires_at`."""
    totals = _quote_totals(payload)
    status = payload.get("status") or "ACTIVE"
    customer_id = payload.get("customerId") or None
    quote_data = {**payload, "totals": totals, "createdBy": actor_email}
    now = timezone.now()

    quote_id = payload.get("id")
    if quote_id:
        quote = Quote.objects.filter(pk=quote_id).first()
        if quote is None:
            return {"error": "Quote not found", "status": 404}

        number = quote.number
        created_at = quote.created_at
        expires_at = quote.expires_at
        previous = quote.data or {}
        kept = {
            key: previous[key]
            for key in _SYSTEM_QUOTE_KEYS
            if key in previous and key not in payload
        }
        quote.customer_id = customer_id
        quote.status = status
        quote.data = {**quote_data, **kept}
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


def delete_or_archive_quote(quote: Quote, actor_email: str) -> dict:
    """Una cotización ya convertida en pedido se archiva, nunca se borra, para
    conservar el rastro financiero."""
    data = quote.data or {}
    order_number = data.get("orderNumber")

    if order_number:
        quote.data = {
            **data,
            "archived": True,
            "archivedAt": timezone.now().isoformat(),
            "archivedBy": actor_email,
        }
        quote.updated_at = timezone.now()
        quote.save(update_fields=["data", "updated_at"])
        record_activity(
            actor=actor_email,
            action="QUOTE_ARCHIVED",
            entity_type="QUOTE",
            entity_id=quote.pk,
            data={"number": quote.number, "orderNumber": order_number},
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
    record_activity(
        actor=actor_email,
        action="QUOTE_DELETED",
        entity_type="QUOTE",
        entity_id=quote_id,
        data={"number": number, "status": status},
    )
    return {"ok": True, "archived": False, "deletedQuote": number}
