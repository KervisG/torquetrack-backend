from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import HasRolePermission
from apps.cart.services import list_admin_carts


class AdminCartsView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "carts.view"

    def get(self, request):
        return Response(list_admin_carts())
