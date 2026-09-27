from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cart.services import sync_cart


class CartSyncView(APIView):
    """Sesión opcional, igual que el checkout: el invitado sincroniza su
    carrito de sesión y con cuenta se exige CSRF."""

    # Solo JSON: un formulario de otro sitio no puede mandar `application/json`
    # sin preflight de CORS, así que no llega a esta ruta sin CSRF (415).
    parser_classes = [JSONParser]
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return Response(sync_cart(request.session, body))
