from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cart.services import CART_SESSION_KEY
from apps.checkout.services import create_storefront_checkout
from apps.integrations.payments import stripe as stripe_payments


class CheckoutView(APIView):
    """La sesión es opcional: sin ella es un checkout invitado; con ella el
    pedido queda en el `Customer` de la cuenta y se exige CSRF."""

    permission_classes = [AllowAny]

    def post(self, request):
        if not stripe_payments.is_configured():
            return Response(
                {
                    "error": "Payments are not configured. Add STRIPE_SECRET_KEY to "
                    "the server environment."
                },
                status=503,
            )

        body = request.data if isinstance(request.data, dict) else {}
        payload, status = create_storefront_checkout(
            request.user, body, cart_id=request.session.get(CART_SESSION_KEY)
        )
        return Response(payload, status=status)
