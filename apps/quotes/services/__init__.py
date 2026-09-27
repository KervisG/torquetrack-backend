"""API pública de los services de cotizaciones; cada módulo es dueño de su
tema: `lifecycle` (número, token y vencimiento), `rendering` (serialización,
enlaces y HTML), `pdf` (WeasyPrint), `storefront` (solicitud, enlace público
y checkout) y `admin` (editor y acciones del panel)."""
from apps.quotes.services.admin import (
    convert_quote_to_order,
    delete_or_archive_quote,
    ensure_public_token,
    list_admin_quotes,
    reopen_quote,
    send_quote_email,
    upsert_admin_quote,
)
from apps.quotes.services.lifecycle import (
    EXPIRABLE_QUOTE_STATUSES,
    effective_quote_status,
    expire_stale_quotes,
    is_expired,
    next_quote_number,
    quote_token,
    unexpired_quotes_q,
)
from apps.quotes.services.pdf import render_quote_pdf_base64, render_quote_pdf_bytes
from apps.quotes.services.rendering import (
    public_quote_pdf_url,
    public_quote_url,
    render_quote_html,
    serialize_quote,
)
from apps.quotes.services.storefront import (
    PAYABLE_QUOTE_STATUSES,
    checkout_from_quote,
    create_quote_from_request,
    is_quote_payable,
    serialize_public_quote,
)

__all__ = [
    "EXPIRABLE_QUOTE_STATUSES",
    "PAYABLE_QUOTE_STATUSES",
    "checkout_from_quote",
    "convert_quote_to_order",
    "create_quote_from_request",
    "delete_or_archive_quote",
    "effective_quote_status",
    "ensure_public_token",
    "expire_stale_quotes",
    "is_expired",
    "is_quote_payable",
    "list_admin_quotes",
    "next_quote_number",
    "public_quote_pdf_url",
    "public_quote_url",
    "quote_token",
    "render_quote_html",
    "render_quote_pdf_base64",
    "render_quote_pdf_bytes",
    "reopen_quote",
    "send_quote_email",
    "serialize_public_quote",
    "serialize_quote",
    "unexpired_quotes_q",
    "upsert_admin_quote",
]
