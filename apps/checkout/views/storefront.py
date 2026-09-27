from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cart.services import current_cart_id
from apps.checkout.services import create_storefront_checkout
from apps.integrations.payments import stripe as stripe_payments
from config.responses import service_response


class CheckoutView(APIView):
    """La sesión es opcional: sin ella es un checkout invitado; con ella el
    pedido queda en el `Customer` de la cuenta y se exige CSRF."""

    # Solo JSON: un formulario de otro sitio no puede mandar `application/json`
    # sin preflight de CORS, así que no llega a esta ruta sin CSRF (415).
    parser_classes = [JSONParser]
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
        return service_response(
            create_storefront_checkout(
                request.user, body, cart_id=current_cart_id(request.user, request.session)
            )
        )
