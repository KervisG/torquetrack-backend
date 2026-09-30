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


EASYPOST_GET_RATES = "apps.integrations.shipping.easypost.get_rates"


def quote_shipping(
    monkeypatch,
    settings,
    *,
    zip_code="33701",
    rate=12.5,
    shipment_id="shp_checkout",
    rate_id="rate_ground",
    items,
) -> dict:
    """Devuelve la selección que el SPA manda al checkout: el checkout solo
    cobra envíos cotizados por el servidor, nunca el monto del body.

    Un producto de `items` que todavía no existe se crea solo para cotizar y
    se borra después, así el caller puede cargarlo con sus propios datos; la
    tarifa ya quedó atada a sus ids en el cache."""
    from apps.catalog.models import Product
    from apps.shipping.services import get_shipping_rates

    settings.EASYPOST_API_KEY = "ep_test_fake"
    ids = {str(item["id"]) for item in items}
    existing = set(Product.objects.filter(id__in=ids).values_list("id", flat=True))
    temporary = sorted(ids - existing)
    for product_id in temporary:
        Product.objects.create(id=product_id, data={"shippingWeight": 2}, active=True)
    rates = [
        {
            "id": rate_id,
            "carrier": "USPS",
            "service": "Ground Advantage",
            "rate": rate,
            "delivery_days": 5,
            "guaranteed": False,
        }
    ]
    monkeypatch.setattr(
        EASYPOST_GET_RATES, lambda **kwargs: {"shipment_id": shipment_id, "rates": rates}
    )
    _, status = get_shipping_rates({"to": {"zip": zip_code}, "items": items})
    Product.objects.filter(id__in=temporary).delete()
    assert status == 200, "quote_shipping could not quote the given items"
    return {"shipmentId": shipment_id, "rateId": rate_id}
