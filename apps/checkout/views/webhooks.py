import logging

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.checkout.services import handle_webhook_event
from apps.integrations.exceptions import (
    ProviderError,
    ProviderNotConfigured,
    WebhookSignatureError,
)
from apps.integrations.payments import authorize_net

logger = logging.getLogger(__name__)


class AuthorizeNetWebhookView(APIView):
    """Responde 200 a todo evento con firma válida, aunque la transacción sea
    desconocida. Solo un fallo al releer la transacción responde 503, para
    que Authorize.net reintente más tarde."""

    permission_classes = [AllowAny]
    # Sin throttle a propósito: Authorize.net reintenta ante un 429 y la firma
    # ya descarta lo que no viene de la pasarela; cortar aquí demoraría pagos.
    throttle_classes = []

    def post(self, request):
        signature = request.META.get("HTTP_X_ANET_SIGNATURE", "")
        try:
            event = authorize_net.verify_webhook(request.body, signature)
        except ProviderNotConfigured:
            return Response({"error": "Webhook signature key not configured"}, status=503)
        except WebhookSignatureError:
            return Response({"error": "Invalid signature"}, status=400)

        try:
            handle_webhook_event(event)
        except ProviderError as exc:
            logger.warning(
                "Authorize.net webhook %s could not be reconciled: %s",
                event.get("notificationId"),
                exc,
            )
            return Response({"error": "Payment provider unavailable"}, status=503)
        return Response({"received": True})
