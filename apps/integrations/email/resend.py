"""Adaptador de Resend: envío de correo por la API REST, sin el SDK.

A diferencia de los demás adaptadores, `send_email` no lanza excepciones:
devuelve `{"sent": True, "id": ...}` o `{"sent": False, "reason": ...}`.
Todos los llamadores tratan el correo como un efecto secundario que puede
fallar sin cortar la operación (el reset de contraseña responde igual, la
cotización se guarda igual) y algunos muestran el motivo al staff, así que
el resultado del envío es un dato y no un caso excepcional.
"""
from __future__ import annotations

import requests
from django.conf import settings

RESEND_EMAILS_URL = "https://api.resend.com/emails"
NOT_CONFIGURED_REASON = "Email provider not configured"


def is_configured() -> bool:
    return bool(settings.RESEND_API_KEY and settings.FROM_EMAIL)


def send_email(*, to, subject, html, attachments=None, reply_to=None) -> dict:
    """Envía un correo. `to` acepta un email o una lista; cada adjunto es
    `{"filename", "content" (base64), "contentType"}`."""
    if not is_configured():
        return {"sent": False, "reason": NOT_CONFIGURED_REASON}

    payload = {
        "from": settings.FROM_EMAIL,
        "to": to if isinstance(to, list) else [to],
        "subject": subject,
        "html": html,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = [
            {
                "filename": attachment["filename"],
                "content": attachment["content"],
                "content_type": attachment.get("contentType", "application/pdf"),
            }
            for attachment in attachments
        ]

    try:
        response = requests.post(
            RESEND_EMAILS_URL,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        return {"sent": False, "reason": str(exc)}

    try:
        body = response.json() or {}
    except ValueError:
        body = {}

    if not response.ok:
        return {"sent": False, "reason": body.get("message") or "Email failed"}
    return {"sent": True, "id": body.get("id")}
