"""Generación del PDF de cotizaciones con WeasyPrint.

WeasyPrint renderiza `quotes/quote.html` (la MISMA plantilla de la vista
HTML pública y del email de la cotización, ver `apps/quotes/services.py`)
como medio de impresión; la regla CSS `@media print` ya oculta los botones
`.actions`, así que no hace falta una plantilla aparte para el PDF. Las
líneas, los totales y los datos de cliente y vehículo coinciden con la vista
HTML porque ambos renders comparten `serialize_quote` y la misma plantilla.

WeasyPrint necesita las librerías nativas Pango/Cairo/GDK-Pixbuf, que no
existen en una máquina Windows sin instalar un runtime GTK3 con permisos de
administrador. `backend/Dockerfile` (Debian slim) las instala, así que el
contenedor Linux es el entorno donde se genera y se verifica el PDF.
"""
from __future__ import annotations

import base64


def render_quote_pdf_bytes(quote: dict) -> bytes:
    from weasyprint import HTML

    from apps.quotes.services import render_quote_html

    html = render_quote_html(quote, public_url=None, print_mode=False)
    return HTML(string=html).write_pdf()


def render_quote_pdf_base64(quote: dict) -> str:
    return base64.b64encode(render_quote_pdf_bytes(quote)).decode("ascii")
