"""No se compara el layout: solo que el PDF sea válido y salga de los mismos
datos que la vista HTML pública."""

import pytest
from django.utils import timezone

from apps.quotes.models import Quote
from apps.quotes.tests.pdf_support import requires_weasyprint

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
@requires_weasyprint
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
    assert quote.status == "ACTIVE"  # no se reabre sola


@pytest.mark.django_db
@requires_weasyprint
def test_pdf_source_data_matches_quote_line_items_and_totals():
    from apps.quotes.services.pdf import render_quote_pdf_bytes
    from apps.quotes.services.rendering import serialize_quote

    quote = _make_quote()
    quote_dict = serialize_quote(quote)

    assert quote_dict["items"][0]["title"] == "6.4L Power Stroke EGR Cooler"
    assert quote_dict["totals"]["total"] == 610.5
    assert quote_dict["customer"]["name"] == "Mark Torque"
    assert quote_dict["vehicle"]["make"] == "Ford"

    pdf_bytes = render_quote_pdf_bytes(quote_dict)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500


def test_rendered_lines_use_whole_quantities_and_the_totals_rounding():
    # La línea se muestra con la regla de `price_lines`: precio redondeado a
    # centavos antes de multiplicar y cantidad entera (antes salía "3.0").
    from apps.quotes.services.rendering import render_quote_html

    html = render_quote_html(
        {"items": [{"title": "Glow Plug", "quantity": 3, "unitPrice": 19.995, "coreCharge": 1.005}]}
    )

    assert "<span>3</span>" in html
    assert "<span>3.0</span>" not in html
    assert "$63.03" in html


class _FakeHTML:
    """Doble de `weasyprint.HTML`: guarda el HTML que recibiría WeasyPrint, así
    el test corre sin las librerías nativas."""

    rendered: list[str] = []

    def __init__(self, string):
        _FakeHTML.rendered.append(string)

    def write_pdf(self):
        return b"%PDF-fake"


@pytest.mark.django_db
def test_pdf_footer_uses_the_company_settings(monkeypatch, settings):
    import sys
    import types

    from apps.quotes.services.pdf import render_quote_pdf_bytes
    from apps.quotes.services.rendering import serialize_quote

    settings.SALES_EMAIL = "parts@shop.example.com"
    settings.APP_URL = "https://shop.example.com"
    settings.COMPANY_ADDRESS = "Tampa, FL"
    _FakeHTML.rendered = []
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=_FakeHTML))

    render_quote_pdf_bytes(serialize_quote(_make_quote()))

    (html,) = _FakeHTML.rendered
    assert "parts@shop.example.com" in html
    assert "Tampa, FL" in html
    assert "shop.example.com" in html
    assert "torquetrackdiesel.com" not in html


LOGO_PATHS = ("M0 0H51V14H34.5V58H16.5V14H0Z", "M55 0H106V14H89.5V58H71.5V14H55Z")


def test_quote_page_draws_the_inline_svg_logo_in_the_amber_palette():
    # La página pública y el PDF no tienen `base_url`: el logo va en línea.
    from apps.quotes.services.rendering import render_quote_html

    html = render_quote_html({"number": "Q1"})

    assert '<svg class="logo" viewBox="0 0 106 58"' in html
    for path in LOGO_PATHS:
        assert path in html
    assert "#fbbf24" in html
    assert "#42ee8a" not in html
    assert ">TT<" not in html
    assert "brand/email-logo.png" not in html


def test_quote_email_variant_uses_the_hosted_png_instead_of_svg(settings):
    # Los clientes de correo bloquean el SVG.
    from apps.quotes.services.rendering import render_quote_html

    settings.APP_URL = "https://shop.example.com"

    html = render_quote_html({"number": "Q1"}, for_email=True)

    assert '<img src="https://shop.example.com/brand/email-logo.png"' in html
    assert 'alt="TorqueTrack"' in html
    assert "<svg" not in html
    assert "#42ee8a" not in html


@pytest.mark.django_db
def test_pdf_html_carries_the_inline_svg_logo(monkeypatch):
    import sys
    import types

    from apps.quotes.services.pdf import render_quote_pdf_bytes
    from apps.quotes.services.rendering import serialize_quote

    _FakeHTML.rendered = []
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=_FakeHTML))

    render_quote_pdf_bytes(serialize_quote(_make_quote()))

    (html,) = _FakeHTML.rendered
    for path in LOGO_PATHS:
        assert path in html
    assert "<img" not in html
