"""Layout de marca de los correos de notificación que salen por Resend.

Vive en `apps/common/` porque lo usan `authentication`, `checkout` y `quotes`
y solo arma un string (sin I/O, sin modelos, sin importar apps). El logo es el
PNG que publica el SPA: los clientes de correo bloquean el SVG, así que el SVG
en línea queda para la página pública y el PDF de la cotización."""
from __future__ import annotations

from django.utils.html import format_html

from apps.common.links import app_url

EMAIL_LOGO_PATH = "/brand/email-logo.png"

# Tablas y estilos en línea: Gmail y Outlook descartan `<style>` y el layout
# con flex o grid. Solo `{logo_url}` y `{body}` se interpolan.
_LAYOUT = (
    "<!doctype html>"
    '<html><body style="margin:0;padding:0;background:#f5f5f5;">'
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
    'style="background:#f5f5f5;">'
    '<tr><td align="center" style="padding:24px 12px;">'
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
    'style="max-width:560px;background:#ffffff;border:1px solid #e5e5e5;'
    'font-family:Arial,Helvetica,sans-serif;color:#171717;">'
    '<tr><td style="background:#0a0a0a;padding:20px 24px;">'
    '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
    '<td style="vertical-align:middle;">'
    '<img src="{logo_url}" width="48" height="48" alt="TorqueTrack" '
    'style="display:block;border:0;outline:none;text-decoration:none;">'
    "</td>"
    '<td style="vertical-align:middle;padding-left:12px;font-size:20px;font-weight:bold;'
    'color:#ffffff;">TorqueTrack <span style="color:#fbbf24;">Diesel</span></td>'
    "</tr></table>"
    "</td></tr>"
    '<tr><td style="height:4px;line-height:4px;font-size:0;background:#f59e0b;">&nbsp;</td></tr>'
    '<tr><td style="padding:24px;font-size:15px;line-height:1.6;color:#171717;">{body}</td></tr>'
    '<tr><td style="padding:16px 24px;border-top:1px solid #e5e5e5;font-size:12px;'
    'line-height:1.5;color:#737373;">TorqueTrack Diesel Parts &middot; '
    "Find it. Price it. Ship it fast.</td></tr>"
    "</table>"
    "</td></tr></table>"
    "</body></html>"
)


def email_logo_url() -> str:
    """URL absoluta del PNG del logo que sirve el SPA (`public/brand/`)."""
    return app_url(EMAIL_LOGO_PATH)


def branded_email_html(body) -> str:
    """Envuelve el cuerpo del correo en el layout de marca.

    `body` tiene que venir armado con `format_html` (o `mark_safe` para un
    literal fijo): un `str` suelto se escapa como texto, así un dato del
    cliente que se cuele sin escapar no llega como marcado."""
    return format_html(_LAYOUT, logo_url=email_logo_url(), body=body)
