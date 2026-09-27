"""Presentación de una cotización: serialización, enlaces públicos y la
plantilla HTML que comparten la página pública, el correo y el PDF."""
from __future__ import annotations

from django.template.loader import render_to_string

from apps.catalog.services.pricing import PricingError, price_lines
from apps.common.links import app_url
from apps.common.numbers import money
from apps.quotes.models import Quote
from apps.quotes.services.lifecycle import effective_quote_status


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


def _quote_line(item: dict) -> dict:
    """El total de la línea se calcula aquí, con la regla de `price_lines`: ni
    el correo ni el SPA recalculan dinero."""
    try:
        (line,) = price_lines([item], allow_custom_price=True, max_quantity=None).lines
    except PricingError:
        # Una línea guardada antes de validar se muestra sin total en vez de
        # romper la página pública.
        return {**item, "lineTotal": None}
    return {
        **item,
        "quantity": line.quantity,
        "unitPrice": money(line.unit_price),
        "coreCharge": money(line.core_charge),
        "lineTotal": money(line.line_total + line.core_total),
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
