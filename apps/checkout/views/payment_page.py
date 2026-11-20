import logging

from django.http import HttpResponse, HttpResponseRedirect
from django.utils.html import format_html
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.auth.utils.throttling import PaymentPageRateThrottle
from apps.checkout.models import Payment, PaymentStatus
from apps.checkout.services.payments import (
    CHARGED_PAYMENT_STATUSES,
    CLOSED_ORDER_STATUSES,
    PROVIDER,
    create_payment_form,
)
from apps.common.links import app_url
from apps.integrations.exceptions import ProviderError

logger = logging.getLogger(__name__)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>TorqueTrack secure payment</title>
<style>
body {{ font-family: system-ui, sans-serif; background: #f5f5f4; color: #1c1917;
  display: flex; min-height: 100vh; align-items: center; justify-content: center; margin: 0; }}
main {{ background: #fff; padding: 2rem; border-radius: 12px; max-width: 420px;
  margin: 1rem; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
button, a.button {{ background: #b45309; color: #fff; border: 0; border-radius: 8px;
  padding: .75rem 1.5rem; font-size: 1rem; cursor: pointer; text-decoration: none;
  display: inline-block; }}
</style>
</head>
<body><main>{}</main></body>
</html>"""


def _page(body, status: int) -> HttpResponse:
    response = HttpResponse(format_html(PAGE, body), status=status)
    # El token del form es de un solo uso y vence: ni cache ni historial.
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _message(title: str, text: str, link_url: str, link_text: str, status: int) -> HttpResponse:
    return _page(
        format_html(
            '<h1>{}</h1><p>{}</p><p><a class="button" href="{}">{}</a></p>',
            title,
            text,
            link_url,
            link_text,
        ),
        status,
    )


class PaymentPageView(APIView):
    """Puente al formulario de Accept Hosted. El token de Authorize.net vence
    a los 15 minutos, así que se pide al abrir este link (que sí puede ir por
    correo) y la página lo envía por POST a la pasarela.

    El id del pago (prefijo + 12 hex al azar) hace de llave: no revela nada
    del pedido y solo sirve mientras el pago está PENDING."""

    permission_classes = [AllowAny]
    throttle_classes = [PaymentPageRateThrottle]

    def get(self, request, payment_id: str):
        payment = (
            Payment.objects.select_related("order")
            .filter(pk=payment_id, provider=PROVIDER)
            .first()
        )
        if payment is None or payment.order is None:
            return _message(
                "Payment link not found",
                "This payment link is not valid.",
                app_url("/"),
                "Back to the store",
                404,
            )
        order = payment.order
        if payment.status in CHARGED_PAYMENT_STATUSES:
            return HttpResponseRedirect(app_url(f"/checkout-success?order_id={order.pk}"))
        if payment.status != PaymentStatus.PENDING or order.status in CLOSED_ORDER_STATUSES:
            return _message(
                "Payment link expired",
                "This payment link is no longer active. Please contact us or start a new "
                "checkout to complete your order.",
                app_url("/"),
                "Back to the store",
                410,
            )

        try:
            form = create_payment_form(payment)
        except ProviderError as exc:
            logger.warning("Payment form for payment %s failed: %s", payment.pk, exc)
            return _message(
                "Payment page unavailable",
                "We couldn't open the secure payment page. Please try again in a moment.",
                request.build_absolute_uri(),
                "Try again",
                502,
            )

        return _page(
            format_html(
                "<h1>Redirecting to secure payment…</h1>"
                '<form method="post" action="{}" id="payment-form">'
                '<input type="hidden" name="token" value="{}">'
                "<p>Order {}</p>"
                '<button type="submit">Continue to payment</button>'
                "</form>"
                "<script>document.getElementById('payment-form').submit();</script>",
                form["formUrl"],
                form["token"],
                order.number,
            ),
            200,
        )
