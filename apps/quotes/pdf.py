"""WeasyPrint-based PDF generation for quotes (task 6.2, design decision
#8), replacing `lib/quote-pdf.ts`'s hand-rolled raw PDF byte writer.

WeasyPrint renders `quotes/quote.html` (the SAME template used for the
public HTML view and the emailed quote — see `apps/quotes/services.py`)
as print media, which already hides the `.actions` buttons via the
`@media print` CSS rule — no separate PDF-only template is needed. Layout
is allowed to differ from the legacy generator (spec: "Quote PDF Visual
Equivalence"); line items, totals, and customer/vehicle data must match,
which is guaranteed here because both renders share one `serialize_quote`
data source and one template.

WeasyPrint needs native Pango/Cairo/GDK-Pixbuf libraries that are not
available on a bare Windows dev machine without an admin-level GTK3
runtime install; this project's `backend/Dockerfile` (Debian slim,
already the deployment target) installs them, so the Linux container is
both the correct production shape AND the environment PDF generation was
verified against in this phase — see apply-progress for the exact
commands.
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
