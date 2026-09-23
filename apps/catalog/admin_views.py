from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.permissions import HasTorqueTrackPermission, has_torquetrack_permission
from apps.catalog.admin_services import deactivate_admin_product, upsert_admin_product


class AdminProductDetailView(APIView):
    """`products.edit` cubre crear, editar y activar o desactivar; precios y
    costos exigen además `pricing.edit`, y los costos se ven con `costs.view`."""

    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "products.edit"

    def put(self, request, product_id):
        body = request.data if isinstance(request.data, dict) else {}
        payload, status = upsert_admin_product(
            product_id,
            body,
            can_edit_pricing=has_torquetrack_permission(request.user, "pricing.edit"),
            can_view_costs=has_torquetrack_permission(request.user, "costs.view"),
        )
        return Response(payload, status=status)

    def delete(self, request, product_id):
        payload, status = deactivate_admin_product(product_id)
        return Response(payload, status=status)
