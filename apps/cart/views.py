"""`POST /api/cart/sync` and `GET /api/admin/carts`, matching
`app/api/cart/sync/route.ts` and `app/api/admin/carts/route.ts`.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.permissions import HasTorqueTrackPermission
from apps.auth.authentication import AdminSessionAuthentication
from apps.cart.services import list_admin_carts, sync_cart


class CartSyncView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return Response(sync_cart(body))


class AdminCartsView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "carts.view"

    def get(self, request):
        return Response(list_admin_carts())
