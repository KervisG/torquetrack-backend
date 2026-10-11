"""Layout compartido de los correos de notificación (`apps/common/emails.py`).

Sin base de datos: el helper solo lee settings. El logo es un PNG público; los
clientes de correo bloquean el SVG."""
from django.utils.html import format_html

from apps.common.emails import branded_email_html, email_logo_url


def test_email_logo_url_points_to_the_png_hosted_by_the_spa(settings):
    settings.APP_URL = "https://shop.example.com/"

    assert email_logo_url() == "https://shop.example.com/brand/email-logo.png"


def test_a_configured_logo_url_wins_over_the_spa(settings):
    # En local `APP_URL` es `localhost`, que ninguna bandeja puede cargar: el
    # logo se sirve desde el CDN.
    settings.APP_URL = "http://localhost:5173"
    settings.EMAIL_LOGO_URL = "https://cdn.example.com/brand/email-logo-v1.png"

    assert email_logo_url() == "https://cdn.example.com/brand/email-logo-v1.png"
    assert 'src="https://cdn.example.com/brand/email-logo-v1.png"' in branded_email_html("x")


def test_branded_email_wraps_the_body_with_the_logo_header_and_footer(settings):
    settings.APP_URL = "https://shop.example.com"
    body = format_html("<p>Hi {},</p>", "Pat")

    html = branded_email_html(body)

    assert (
        '<img src="https://shop.example.com/brand/email-logo.png" width="56" height="56" '
        'alt="TorqueTrack"'
    ) in html
    assert "TorqueTrack Diesel Parts" in html
    assert "max-width:600px" in html
    assert "<p>Hi Pat,</p>" in html
    assert html.index("email-logo.png") < html.index("<p>Hi Pat,</p>")
    assert "<svg" not in html


def test_branded_email_uses_the_brand_colors(settings):
    html = branded_email_html("x")

    # Negro de la marca en el encabezado y el pie, ámbar en los acentos.
    assert html.count("background:#0a0a0a") >= 2
    assert "#f59e0b" in html and "#fbbf24" in html
    assert "FIND IT. PRICE IT. SHIP IT FAST." in html


def test_branded_email_links_to_the_store(settings):
    settings.APP_URL = "https://shop.example.com/"

    assert 'href="https://shop.example.com"' in branded_email_html("x")


def test_branded_email_escapes_a_body_that_is_not_marked_safe(settings):
    # Contrato cerrado por defecto: un `str` suelto se trata como texto, así un
    # caller que olvide `format_html` no inyecta marcado del cliente.
    settings.APP_URL = "https://shop.example.com"

    html = branded_email_html("<script>alert(1)</script>")

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
