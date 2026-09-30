from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.checkout.services import (
    reconcile_expired_session,
    reconcile_failed_session,
    reconcile_paid_session,
    reconcile_refunded_charge,
    reconcile_stripe_refund,
)
from apps.integrations.exceptions import ProviderNotConfigured, WebhookSignatureError
from apps.integrations.payments import stripe as stripe_payments

SUCCESS_EVENTS = ("checkout.session.completed", "checkout.session.async_payment_succeeded")
REFUND_EVENTS = ("refund.created", "refund.updated", "refund.failed")


class StripeWebhookView(APIView):
    """Responde 200 a todo evento con firma válida, aunque la sesión sea
    desconocida: Stripe reintenta cualquier otra respuesta durante días."""

    permission_classes = [AllowAny]
    # Sin throttle a propósito: Stripe reintenta ante un 429 y la firma ya
    # descarta lo que no viene de Stripe; cortar aquí demoraría pagos reales.
    throttle_classes = []

    def post(self, request):
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe_payments.construct_webhook_event(request.body, sig_header)
        except ProviderNotConfigured:
            return Response({"error": "Webhook secret not configured"}, status=503)
        except WebhookSignatureError:
            return Response({"error": "Invalid signature"}, status=400)

        event_type = event.get("type")
        event_obj = (event.get("data") or {}).get("object") or {}
        if event_type in SUCCESS_EVENTS:
            reconcile_paid_session(event_obj)
        elif event_type == "checkout.session.async_payment_failed":
            reconcile_failed_session(event_obj)
        elif event_type == "checkout.session.expired":
            reconcile_expired_session(event_obj)
        elif event_type in REFUND_EVENTS:
            reconcile_stripe_refund(event_obj)
        elif event_type == "charge.refunded":
            reconcile_refunded_charge(event_obj)

        return Response({"received": True})
