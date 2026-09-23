"""El PDF usa la misma plantilla que la página pública y el correo: `@media print`
ya oculta los botones. WeasyPrint necesita Pango/Cairo, que trae la imagen de
`backend/Dockerfile`."""
from __future__ import annotations

import base64


def render_quote_pdf_bytes(quote: dict) -> bytes:
    from weasyprint import HTML

    from apps.quotes.services import render_quote_html

    html = render_quote_html(quote, public_url=None, print_mode=False)
    return HTML(string=html).write_pdf()


def render_quote_pdf_base64(quote: dict) -> str:
    return base64.b64encode(render_quote_pdf_bytes(quote)).decode("ascii")
