from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cart.services import sync_cart


class CartSyncView(APIView):
    """Sesión opcional, igual que el checkout: el invitado sincroniza su
    carrito de sesión y con cuenta se exige CSRF."""

    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return Response(sync_cart(request.session, body))
