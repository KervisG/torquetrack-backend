from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cart.services import list_admin_carts
from apps.roles.permissions import HasRolePermission


class AdminCartsView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "carts.view"

    def get(self, request):
        return Response(list_admin_carts())
