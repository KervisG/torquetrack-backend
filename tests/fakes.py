"""Se instalan sobre el adaptador, nunca sobre `requests` ni el SDK: los tests
de dominio prueban qué se le pide al proveedor, no el mapeo HTTP."""
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

    def send_email(
        self, *, to, subject, html=None, text=None, attachments=None, reply_to=None, timeout=None
    ):
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


SPACES = "apps.integrations.storage.spaces"


class FakeSpaces:
    """`spaces.upload` y `spaces.delete` falsos: guarda los objetos en memoria
    y arma la URL pública como el CDN."""

    def __init__(self):
        self.objects = {}
        self.deleted = []

    def upload(self, *, key, content, content_type):
        self.objects[key] = {"content": content, "content_type": content_type}
        return f"https://cdn.test/{key}"

    def delete(self, key):
        self.deleted.append(key)
        self.objects.pop(key, None)


def install_spaces(monkeypatch, fake=None):
    fake = fake or FakeSpaces()
    monkeypatch.setattr(f"{SPACES}.upload", fake.upload)
    monkeypatch.setattr(f"{SPACES}.delete", fake.delete)
    return fake
