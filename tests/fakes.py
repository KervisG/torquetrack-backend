"""Proveedores falsos compartidos por los tests de las apps de dominio.

Se instalan sobre el adaptador de `apps/integrations`, nunca sobre
`requests` ni sobre el SDK: los tests de dominio prueban qué se le pide al
proveedor, y el mapeo HTTP se prueba en `apps/integrations/tests/`.
"""
import threading

RESEND_SEND_EMAIL = "apps.integrations.email.resend.send_email"


def _email_payload(to, subject, html, attachments=None, reply_to=None) -> dict:
    payload = {"to": to if isinstance(to, list) else [to], "subject": subject, "html": html}
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = attachments
    return payload


class FakeResend:
    """`resend.send_email` falso: guarda cada correo (con `to` siempre como
    lista) y devuelve `result`."""

    def __init__(self, result=None):
        self.sent = []
        self.result = result or {"sent": True, "id": "email_1"}

    def send_email(self, *, to, subject, html, attachments=None, reply_to=None):
        self.sent.append(_email_payload(to, subject, html, attachments, reply_to))
        return dict(self.result)


class SlowResend(FakeResend):
    """No responde hasta que el test lo libera: si la view mandara el correo
    dentro del request, el request quedaría bloqueado."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.delivered = threading.Event()

    def send_email(self, **kwargs):
        self.release.wait(5)
        result = super().send_email(**kwargs)
        self.delivered.set()
        return result


def install_resend(monkeypatch, fake=None):
    fake = fake or FakeResend()
    monkeypatch.setattr(RESEND_SEND_EMAIL, fake.send_email)
    return fake


def forbid_resend(monkeypatch, message="No email must be sent for this request"):
    def _boom(**kwargs):
        raise AssertionError(message)

    monkeypatch.setattr(RESEND_SEND_EMAIL, _boom)
