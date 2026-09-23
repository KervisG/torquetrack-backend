from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.permissions import HasTorqueTrackPermission
from apps.cart.services import list_admin_carts, sync_cart


class CartSyncView(APIView):
    """Sesión opcional, igual que el checkout: el invitado sincroniza su
    carrito de sesión y con cuenta se exige CSRF."""

    authentication_classes = [SessionUserAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return Response(sync_cart(request.session, body))


class AdminCartsView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "carts.view"

    def get(self, request):
        return Response(list_admin_carts())
