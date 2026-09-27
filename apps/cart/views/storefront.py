from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.cart.services import get_cart, replace_cart
from config.responses import service_response


class CartView(APIView):
    """Sesión opcional, igual que el checkout: con cuenta es el carrito de la
    cuenta y el `PUT` exige CSRF; sin ella, el carrito de la sesión invitada."""

    # Solo JSON: un formulario de otro sitio no puede mandar `application/json`
    # sin preflight de CORS, así que no llega a esta ruta sin CSRF (415).
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]

    def get(self, request):
        return service_response(get_cart(request.user, request.session))

    def put(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(replace_cart(request.user, request.session, body))
