"""Reglas de negocio de las cotizaciones en el panel de administración."""
from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.catalog.services.pricing import (
    InvalidPrice,
    InvalidQuantity,
    build_totals,
    price_lines,
    serialize_totals,
)
from apps.checkout.models import Order, OrderPaymentStatus, OrderStatus
from apps.checkout.services import next_order_number
from apps.common.ids import random_id
from apps.common.numbers import money
from apps.customers.services import find_staff_customer
from apps.integrations.email import resend
from apps.quotes.models import Quote, QuoteStatus
from apps.quotes.services.lifecycle import (
    effective_quote_status,
    next_quote_number,
    quote_expires_at,
    quote_token,
)
from apps.quotes.services.pdf import render_quote_pdf_base64
from apps.quotes.services.rendering import (
    public_quote_pdf_url,
    public_quote_url,
    render_quote_html,
    serialize_quote,
)
from apps.quotes.services.tax import (
    QUOTE_TAX_KEYS,
    QuoteTaxError,
    override_changed,
    parse_shipping_address,
    resolve_quote_tax,
)
from apps.tax.services import estimate_tax_for_customer

# Claves que escribe el sistema y no el editor del panel. El editor manda la
# cotización completa; sin conservarlas, un update rompería el enlace ya
# enviado y el convert idempotente (`orderNumber`).
_SYSTEM_QUOTE_KEYS = ("publicToken", "orderNumber", "lastEmailedAt", "lastEmailedTo", "source")

# El staff convierte solo una cotización lista para vender. No se reusa la
# regla del checkout público: sus mensajes son para el cliente y allí
# `CONVERTED` sigue siendo pagable.
CONVERTIBLE_QUOTE_STATUSES = (QuoteStatus.ACTIVE, QuoteStatus.CONTACTED)
NOT_CONVERTIBLE = "This quote cannot be converted in its current status."
INVALID_QUANTITY = "Item quantity must be a whole number of at least 1"
INVALID_PRICE = "Item prices must be amounts of 0 or more"


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
    quote.status = QuoteStatus.ACTIVE
    quote.expires_at = quote_expires_at(timezone.now())
    quote.updated_at = timezone.now()
    quote.save(update_fields=["status", "expires_at", "updated_at"])


def convert_quote_to_order(quote: Quote, actor_email: str) -> dict:
    with transaction.atomic():
        # Todo se decide sobre la fila bloqueada: dos clics, o el checkout
        # público a la vez, no pueden crear dos pedidos de la misma cotización.
        quote = Quote.objects.select_for_update().get(pk=quote.pk)
        if effective_quote_status(quote) == QuoteStatus.EXPIRED:
            return {"error": "Reopen this quote before converting it.", "status": 400}

        data = quote.data or {}
        existing_number = data.get("orderNumber")
        if existing_number:
            existing = Order.objects.filter(number=existing_number).first()
            if existing is not None:
                existing_order = {"id": existing.pk, "number": existing.number}
                return {"ok": True, "existing": True, "order": existing_order}

        if quote.status not in CONVERTIBLE_QUOTE_STATUSES or data.get("archived"):
            return {"error": NOT_CONVERTIBLE, "status": 409}

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
            status=OrderStatus.OPEN,
            payment_status=OrderPaymentStatus.UNPAID,
            data=order_data,
            updated_at=timezone.now(),
        )
        quote.status = QuoteStatus.CONVERTED
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
    html = render_quote_html(
        quote_dict, public_url=url, pdf_url=public_quote_pdf_url(public_token), for_email=True
    )

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
    if quote.status == QuoteStatus.BUILDING:
        quote.status = QuoteStatus.CONTACTED
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


def _price_quote(payload: dict):
    """Líneas normalizadas y `PricedLines`; lanza `InvalidQuantity`/`InvalidPrice`.
    El staff fija el precio de cada línea (puede ser 0) y la cantidad no tiene
    el tope del storefront; el resto de la regla es la de `price_lines`."""
    priced = price_lines(payload.get("items") or [], allow_custom_price=True, max_quantity=None)
    items = [
        {
            **line.item,
            "quantity": line.quantity,
            "unitPrice": money(line.unit_price),
            "coreCharge": money(line.core_charge),
        }
        for line in priced.lines
    ]
    return items, priced


def estimate_admin_quote_tax(payload: dict) -> dict:
    """El impuesto del editor se decide con el cliente de la cotización, nunca
    con el perfil del empleado en sesión: el cliente guardado en la cotización
    (`quoteId`) manda; si aún no tiene, el `customerId` del body o el email de
    una cuenta registrada."""
    customer = None
    quote_id = payload.get("quoteId")
    if quote_id:
        quote = Quote.objects.select_related("customer").filter(pk=quote_id).first()
        customer = quote.customer if quote is not None else None
    if customer is None:
        snapshot = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
        customer = find_staff_customer(
            payload.get("customerId"), payload.get("email") or snapshot.get("email")
        )
    return estimate_tax_for_customer(payload, customer)


def list_admin_quotes() -> list[dict]:
    """Solo lectura: `serialize_quote` ya informa `EXPIRED` a las vencidas."""
    quotes = Quote.objects.select_related("customer").order_by("created_at")
    return [serialize_quote(quote) for quote in quotes if not (quote.data or {}).get("archived")]


def upsert_admin_quote(payload: dict, actor_email: str, *, can_override_tax: bool = False) -> dict:
    """Al actualizar se conservan `number`, `created_at` y `expires_at`.

    El impuesto lo calcula el servidor (`resolve_quote_tax`): el `tax` del
    body se ignora y se recalcula sobre las líneas repreciadas y la
    `shippingAddress` guardada. La exención sale solo del `Customer`
    vinculado (`customerId`). Un `taxOverride` solo vale con
    `tax_exemptions.review` (`can_override_tax`, que resuelve la view) y deja
    `QUOTE_TAX_OVERRIDDEN` en la bitácora."""
    customer_id = payload.get("customerId") or None
    customer = find_staff_customer(customer_id) if customer_id else None
    try:
        items, priced = _price_quote(payload)
    except InvalidQuantity:
        return {"error": INVALID_QUANTITY, "status": 400}
    except InvalidPrice:
        return {"error": INVALID_PRICE, "status": 400}
    status = str(payload.get("status") or QuoteStatus.ACTIVE).upper()
    if status not in QuoteStatus.values:
        return {"error": "Invalid quote status", "status": 400}

    now = timezone.now()
    override = payload.get("taxOverride")
    try:
        address = parse_shipping_address(payload.get("shippingAddress"))
        tax = resolve_quote_tax(
            customer=customer,
            address=address,
            subtotal=priced.subtotal,
            core=priced.core,
            shipping=payload.get("shipping"),
            override=override,
            can_override=can_override_tax,
            actor_email=actor_email,
            now=now,
        )
    except QuoteTaxError as exc:
        return {"error": exc.message, "status": exc.status}
    totals = serialize_totals(
        build_totals(priced.subtotal, priced.core, payload.get("shipping"), tax.amount)
    )

    payload = {key: value for key, value in payload.items() if key not in QUOTE_TAX_KEYS}
    payload = {
        **payload,
        "items": items,
        "tax": totals["tax"],
        "shippingAddress": address,
        **tax.fields,
    }
    quote_data = {**payload, "totals": totals, "createdBy": actor_email}
    previous: dict = {}

    quote_id = payload.get("id")
    if quote_id:
        quote = Quote.objects.filter(pk=quote_id).first()
        if quote is None:
            return {"error": "Quote not found", "status": 404}
        if quote.status == QuoteStatus.CONVERTED:
            # Ya tiene pedido: editarla desalinearía el pedido con lo cotizado.
            return {"error": "Converted quotes cannot be edited", "status": 409}

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
        expires_at = quote_expires_at(now)
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

    manual = tax.fields.get("taxOverride")
    if override_changed(previous, manual):
        record_activity(
            actor=actor_email,
            action="QUOTE_TAX_OVERRIDDEN",
            entity_type="QUOTE",
            entity_id=quote_id,
            data={
                "quoteNumber": number,
                "tax": manual["amount"],
                "reason": manual["reason"],
                "previousTax": (previous.get("totals") or {}).get("tax"),
            },
        )

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
