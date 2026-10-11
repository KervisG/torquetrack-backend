"""Layout de marca de los correos de notificación que salen por Resend.

Vive en `apps/common/` porque lo usan `authentication`, `checkout` y `quotes`
y solo arma un string (sin I/O, sin modelos, sin importar apps). El logo es un
PNG público: los clientes de correo bloquean el SVG, así que el SVG en línea
queda para el PDF de la cotización."""
from __future__ import annotations

from django.conf import settings
from django.utils.html import format_html

from apps.common.links import app_url

EMAIL_LOGO_PATH = "/brand/email-logo.png"

# Colores de la marca, los mismos del sitio: negro `#0a0a0a` y ámbar
# (`#f59e0b` en franjas y botones, `#fbbf24` sobre fondo negro).
#
# El esqueleto va con tablas y estilos en línea, que todo cliente respeta. El
# `<style>` solo mejora lo que escribe cada correo (títulos, botones): Gmail y
# Apple Mail lo aplican, y donde no, el cuerpo queda como texto y enlaces
# normales. Las llaves del CSS van dobles porque el layout pasa por
# `format_html`; solo se interpolan `{logo_url}`, `{store_url}`, `{store_host}`
# y `{body}`.
_LAYOUT = (
    "<!doctype html>"
    '<html lang="en"><head>'
    '<meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    "<style>"
    ".tt-body h2{{margin:0 0 18px;padding:2px 0 2px 14px;border-left:4px solid #f59e0b;"
    "font-size:22px;line-height:1.3;color:#0a0a0a;}}"
    ".tt-body p{{margin:0 0 14px;}}"
    ".tt-body ul{{margin:0 0 14px;padding-left:20px;}}"
    ".tt-body a{{display:inline-block;background:#f59e0b;color:#0a0a0a !important;"
    "font-weight:bold;text-decoration:none;padding:12px 22px;border-radius:6px;}}"
    "</style>"
    "</head>"
    '<body style="margin:0;padding:0;background:#171717;">'
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
    'style="background:#171717;">'
    '<tr><td align="center" style="padding:28px 12px;">'
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
    'style="max-width:600px;background:#ffffff;font-family:Arial,Helvetica,sans-serif;'
    'color:#171717;">'
    # Franja ámbar, encabezado negro con el logo y el nombre.
    '<tr><td style="height:6px;line-height:6px;font-size:0;background:#f59e0b;">&nbsp;</td></tr>'
    '<tr><td style="background:#0a0a0a;padding:24px 28px;">'
    '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
    '<td style="vertical-align:middle;">'
    '<img src="{logo_url}" width="56" height="56" alt="TorqueTrack" '
    'style="display:block;border:0;outline:none;text-decoration:none;border-radius:10px;">'
    "</td>"
    '<td style="vertical-align:middle;padding-left:16px;">'
    '<div style="font-size:24px;line-height:1.1;font-weight:bold;letter-spacing:1px;'
    'color:#ffffff;">TORQUE<span style="color:#fbbf24;">TRACK</span></div>'
    '<div style="margin-top:6px;font-size:11px;line-height:1;letter-spacing:4px;'
    'color:#a3a3a3;">DIESEL PARTS</div>'
    "</td>"
    "</tr></table>"
    "</td></tr>"
    '<tr><td class="tt-body" style="padding:32px 28px 20px;font-size:15px;line-height:1.6;'
    'color:#171717;">{body}</td></tr>'
    # Pie negro con el lema de la marca.
    '<tr><td style="background:#0a0a0a;padding:22px 28px;">'
    '<div style="font-size:12px;line-height:1.4;font-weight:bold;letter-spacing:3px;'
    'color:#fbbf24;">FIND IT. PRICE IT. SHIP IT FAST.</div>'
    '<div style="margin-top:8px;font-size:12px;line-height:1.5;color:#a3a3a3;">'
    "TorqueTrack Diesel Parts &middot; "
    '<a href="{store_url}" style="color:#fbbf24;text-decoration:none;">{store_host}</a>'
    "</div>"
    "</td></tr>"
    '<tr><td style="height:6px;line-height:6px;font-size:0;background:#f59e0b;">&nbsp;</td></tr>'
    "</table>"
    "</td></tr></table>"
    "</body></html>"
)


def email_logo_url() -> str:
    """URL pública del PNG del logo. `EMAIL_LOGO_URL` (el CDN) manda; sin ella
    es el que sirve el SPA en `public/brand/`, que desde `localhost` ninguna
    bandeja puede cargar."""
    return settings.EMAIL_LOGO_URL or app_url(EMAIL_LOGO_PATH)


def branded_email_html(body) -> str:
    """Envuelve el cuerpo del correo en el layout de marca.

    `body` tiene que venir armado con `format_html` (o `mark_safe` para un
    literal fijo): un `str` suelto se escapa como texto, así un dato del
    cliente que se cuele sin escapar no llega como marcado."""
    store_url = app_url()
    return format_html(
        _LAYOUT,
        logo_url=email_logo_url(),
        store_url=store_url,
        store_host=store_url.split("://", 1)[-1],
        body=body,
    )
