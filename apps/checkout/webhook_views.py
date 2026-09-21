"""`POST /api/webhooks/stripe` (task 5.4), matching
`app/api/webhooks/stripe/route.ts`.
"""
import stripe
from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backoffice.models import ActivityLog
from apps.checkout.models import Order, Payment
from apps.checkout.services import get_stripe_payment_method, money


class StripeWebhookView(APIView):
    """Verifies `Stripe-Signature` with the official SDK's
    `stripe.Webhook.construct_event` (design decision #7 — replaces the
    legacy route's hand-rolled HMAC/300s-window check) and reconciles the
    matching Order/Payment via `metadata.order_id` with `client_reference_id`
    fallback (spec: "Stripe Webhook Signature & Metadata Reconciliation")."""

    permission_classes = [AllowAny]

    def post(self, request):
        secret = settings.STRIPE_WEBHOOK_SECRET
        if not secret:
            return Response({"error": "Webhook secret not configured"}, status=503)

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, secret)
        except (ValueError, stripe.error.SignatureVerificationError):
            # No order/payment state is touched below this point — mirrors
            # the spec scenario "Invalid signature is rejected".
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
            # Idempotent replay guard: Stripe may resend the same event (or
            # a related success event) for an order already reconciled.
            # The legacy Next.js handler had no explicit event-id dedup —
            # its `payments` UPDATE ... WHERE status='PENDING' made a
            # second delivery a harmless no-op there, but it always
            # re-wrote `orders` and always inserted another `activity_logs`
            # row. Guarding on the order's own persisted `payment_status`
            # here gives true idempotency (no duplicate audit rows, no
            # redundant writes) without introducing a new table.
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

        ActivityLog.objects.create(
            actor_id="stripe",
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
            created_at=timezone.now(),
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
