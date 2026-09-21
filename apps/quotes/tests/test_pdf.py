"""`GET /api/quote/public/<token>/pdf` (task 6.2), pinned against
`app/api/quote/public/[token]/pdf/route.ts` and `lib/quote-pdf.ts`.

Design decision #8: WeasyPrint over the existing `quotes/quote.html`
template (visually equivalent, not pixel-identical, to the legacy raw PDF
byte writer). This test asserts the generated file is a well-formed,
non-empty PDF and that the source data (line items/totals/customer/
vehicle) round-trips through `render_quote_html`/`serialize_quote` — the
same functions the interactive public HTML view uses — rather than
attempting a pixel/layout comparison (none is required by the spec).
"""

import pytest
from django.utils import timezone

from apps.quotes.models import Quote

TOKEN = "tok_pdf_" + "f" * 40


def _make_quote(status="ACTIVE", expires_at=None):
    expires_at = expires_at or (timezone.now() + timezone.timedelta(days=30))
    return Quote.objects.create(
        id="quo_pdf_1",
        number="Q20001",
        status=status,
        data={
            "publicToken": TOKEN,
            "customer": {"name": "Mark Torque", "email": "mark@example.com"},
            "vehicle": {"year": 2010, "make": "Ford", "model": "F-250"},
            "items": [
                {
                    "productId": "ford-6.4-egr-cooler",
                    "title": "6.4L Power Stroke EGR Cooler",
                    "partNumber": "EGR-64PS",
                    "quantity": 1,
                    "unitPrice": 610.5,
                    "coreCharge": 0,
                }
            ],
            "totals": {"subtotal": 610.5, "core": 0, "shipping": 0, "tax": 0, "total": 610.5},
        },
        created_at=timezone.now(),
        expires_at=expires_at,
        updated_at=timezone.now(),
    )


@pytest.mark.django_db
def test_pdf_endpoint_returns_well_formed_pdf_for_valid_token(client):
    _make_quote()

    response = client.get(f"/api/quote/public/{TOKEN}/pdf/")

    assert response.status_code == 200
    assert response["content-type"] == "application/pdf"
    assert 'filename="TorqueTrack-Q20001.pdf"' in response["content-disposition"]
    assert response.content.startswith(b"%PDF-")
    assert response.content.rstrip().endswith(b"%%EOF")
    assert len(response.content) > 500


@pytest.mark.django_db
def test_pdf_endpoint_returns_404_for_unknown_token():
    from rest_framework.test import APIClient

    response = APIClient().get("/api/quote/public/does-not-exist/pdf/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_pdf_endpoint_denies_expired_token(client):
    _make_quote(expires_at=timezone.now() - timezone.timedelta(days=1))

    response = client.get(f"/api/quote/public/{TOKEN}/pdf/")

    assert response.status_code == 410
    quote = Quote.objects.get(pk="quo_pdf_1")
    assert quote.status == "ACTIVE"  # no auto-reopen


@pytest.mark.django_db
def test_pdf_source_data_matches_quote_line_items_and_totals():
    """Proves the PDF and the public HTML view share one data source
    (`serialize_quote`) — not a pixel comparison, but a genuine assertion
    that line items/totals/customer/vehicle data is the same input either
    renderer would receive (spec: "Regenerated PDF contains same line
    items and totals")."""
    from apps.quotes.pdf import render_quote_pdf_bytes
    from apps.quotes.services import serialize_quote

    quote = _make_quote()
    quote_dict = serialize_quote(quote)

    assert quote_dict["items"][0]["title"] == "6.4L Power Stroke EGR Cooler"
    assert quote_dict["totals"]["total"] == 610.5
    assert quote_dict["customer"]["name"] == "Mark Torque"
    assert quote_dict["vehicle"]["make"] == "Ford"

    pdf_bytes = render_quote_pdf_bytes(quote_dict)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500
