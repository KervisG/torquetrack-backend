"""Layout compartido de los correos de notificación (`apps/common/emails.py`).

Sin base de datos: el helper solo lee `APP_URL` de settings. El logo es el PNG
que publica el frontend; los clientes de correo bloquean el SVG."""
from django.utils.html import format_html

from apps.common.emails import branded_email_html, email_logo_url


def test_email_logo_url_points_to_the_png_hosted_by_the_spa(settings):
    settings.APP_URL = "https://shop.example.com/"

    assert email_logo_url() == "https://shop.example.com/brand/email-logo.png"


def test_branded_email_wraps_the_body_with_the_logo_header_and_footer(settings):
    settings.APP_URL = "https://shop.example.com"
    body = format_html("<p>Hi {},</p>", "Pat")

    html = branded_email_html(body)

    assert (
        '<img src="https://shop.example.com/brand/email-logo.png" width="48" height="48" '
        'alt="TorqueTrack"'
    ) in html
    assert "TorqueTrack" in html
    assert "Diesel" in html
    assert "#f59e0b" in html  # línea de acento ámbar
    assert "max-width:560px" in html
    assert "<p>Hi Pat,</p>" in html
    assert html.index("email-logo.png") < html.index("<p>Hi Pat,</p>")
    assert "<svg" not in html


def test_branded_email_escapes_a_body_that_is_not_marked_safe(settings):
    # Contrato cerrado por defecto: un `str` suelto se trata como texto, así un
    # caller que olvide `format_html` no inyecta marcado del cliente.
    settings.APP_URL = "https://shop.example.com"

    html = branded_email_html("<script>alert(1)</script>")

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
