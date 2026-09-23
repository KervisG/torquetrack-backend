"""Vista de `POST /api/webhooks/stripe`."""
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record_activity
from apps.checkout.models import Order, Payment
from apps.checkout.services import get_stripe_payment_method, money
from apps.integrations.exceptions import ProviderNotConfigured, WebhookSignatureError
from apps.integrations.payments import stripe as stripe_payments


class StripeWebhookView(APIView):
    """Verifica `Stripe-Signature` con el adaptador de Stripe
    (`construct_webhook_event`) y concilia el Order/Payment correspondiente por
    `metadata.order_id`, con `client_reference_id` como respaldo."""

    permission_classes = [AllowAny]

    def post(self, request):
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe_payments.construct_webhook_event(request.body, sig_header)
        except ProviderNotConfigured:
            return Response({"error": "Webhook secret not configured"}, status=503)
        except WebhookSignatureError:
            # Con firma inválida no se toca ningún estado de order/payment.
            return Response({"error": "Invalid signature"}, status=400)

        event_type = event["type"]
        session_obj = event["data"]["object"]
        metadata = session_obj.get("metadata") or {}
        order_id = metadata.get("order_id") or session_obj.get("client_reference_id")

        success_types = ("checkout.session.completed", "checkout.session.async_payment_succeeded")
        if event_type in success_types and order_id:
            self._mark_paid(order_id, session_obj)
        elif event_type == "checkout.session.async_payment_failed" and order_id:
            self._mark_failed(order_id)

        return Response({"received": True})

    def _mark_paid(self, order_id, session_obj):
        order = Order.objects.filter(pk=order_id).first()
        if order is None:
            return
        if order.payment_status == "PAID":
            # Guarda de idempotencia: Stripe puede reenviar el mismo evento (o
            # otro evento de éxito relacionado) para un pedido ya conciliado.
            # Chequear el `payment_status` persistido del pedido evita filas
            # duplicadas en `activity_logs` y escrituras redundantes sin
            # necesidad de una tabla de deduplicación por id de evento.
            return

        method = get_stripe_payment_method(session_obj.get("payment_intent"))
        order_data = order.data or {}
        core_amount = money((order_data.get("totals") or {}).get("core"))

        paid_patch = {
            "payment": {
                "provider": "stripe",
                "brand": (method or {}).get("brand"),
                "last4": (method or {}).get("last4"),
                "paymentIntent": session_obj.get("payment_intent"),
                "paidAt": timezone.now().isoformat(),
            }
        }
        if core_amount > 0 and not order_data.get("coreCase"):
            paid_patch["coreCase"] = {
                "status": "AWAITING CORE",
                "amount": core_amount,
                "createdAt": timezone.now().isoformat(),
                "createdBy": "stripe",
            }

        order.status = "OPEN"
        order.payment_status = "PAID"
        order.updated_at = timezone.now()
        order.data = {**order_data, **paid_patch}
        order.save(update_fields=["status", "payment_status", "updated_at", "data"])

        payment = Payment.objects.filter(
            order_id=order_id, provider="stripe", status="PENDING"
        ).first()
        if payment is not None:
            customer_details = session_obj.get("customer_details") or {}
            customer_email = customer_details.get("email") or session_obj.get("customer_email")
            payment.status = "PAID"
            payment.provider_id = session_obj.get("id")
            payment.updated_at = timezone.now()
            payment.data = {
                **(payment.data or {}),
                "payment_intent": session_obj.get("payment_intent"),
                "payment_status": session_obj.get("payment_status"),
                "customer_email": customer_email,
                "brand": (method or {}).get("brand"),
                "last4": (method or {}).get("last4"),
                "funding": (method or {}).get("funding"),
            }
            payment.save(update_fields=["status", "provider_id", "updated_at", "data"])

        record_activity(
            actor="stripe",
            action="PAYMENT_PAID",
            entity_type="ORDER",
            entity_id=order_id,
            data={
                "sessionId": session_obj.get("id"),
                "paymentIntent": session_obj.get("payment_intent"),
                "amountTotal": session_obj.get("amount_total"),
                "brand": (method or {}).get("brand"),
                "last4": (method or {}).get("last4"),
            },
        )

    def _mark_failed(self, order_id):
        order = Order.objects.filter(pk=order_id).first()
        if order is None or order.payment_status == "FAILED":
            return
        order.payment_status = "FAILED"
        order.updated_at = timezone.now()
        order.save(update_fields=["payment_status", "updated_at"])
        Payment.objects.filter(order_id=order_id, provider="stripe", status="PENDING").update(
            status="FAILED", updated_at=timezone.now()
        )
