"""`PUT/DELETE /api/admin/products/[id]` (task 7.3), matching
`app/api/admin/products/[id]/route.ts`.
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.permissions import HasTorqueTrackPermission
from apps.auth.authentication import AdminSessionAuthentication
from apps.catalog.admin_services import deactivate_admin_product, upsert_admin_product


class AdminProductDetailView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "products.edit"

    def put(self, request, product_id):
        body = request.data if isinstance(request.data, dict) else {}
        return Response(upsert_admin_product(product_id, body))

    def delete(self, request, product_id):
        return Response(deactivate_admin_product(product_id))
