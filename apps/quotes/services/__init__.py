"""API pública de los services de cotizaciones; cada módulo es dueño de su
tema: `lifecycle` (número, token y vencimiento), `rendering` (serialización,
enlaces y HTML), `pdf` (WeasyPrint), `storefront` (solicitud, enlace público
y checkout), `admin` (editor y acciones del panel) y `tax` (impuesto que
calcula el servidor al guardar desde el panel)."""
from apps.quotes.services.admin import (
    convert_quote_to_order,
    delete_or_archive_quote,
    ensure_public_token,
    estimate_admin_quote_tax,
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
    unexpired_quotes_q,
)
from apps.quotes.services.pdf import render_quote_pdf_bytes
from apps.quotes.services.rendering import (
    render_quote_html,
    serialize_quote,
)
from apps.quotes.services.storefront import (
    PAYABLE_QUOTE_STATUSES,
    checkout_from_quote,
    create_quote_from_request,
    serialize_public_quote,
)
from apps.quotes.services.tax import TAX_OVERRIDE_PERMISSION

__all__ = [
    "EXPIRABLE_QUOTE_STATUSES",
    "PAYABLE_QUOTE_STATUSES",
    "TAX_OVERRIDE_PERMISSION",
    "checkout_from_quote",
    "convert_quote_to_order",
    "create_quote_from_request",
    "delete_or_archive_quote",
    "effective_quote_status",
    "ensure_public_token",
    "estimate_admin_quote_tax",
    "expire_stale_quotes",
    "is_expired",
    "list_admin_quotes",
    "next_quote_number",
    "render_quote_html",
    "render_quote_pdf_bytes",
    "reopen_quote",
    "send_quote_email",
    "serialize_public_quote",
    "serialize_quote",
    "unexpired_quotes_q",
    "upsert_admin_quote",
]
