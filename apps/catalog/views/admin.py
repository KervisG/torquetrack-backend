from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import HasRolePermission, has_role_permission
from apps.catalog.services import (
    build_catalog_export,
    deactivate_admin_product,
    export_filename,
    list_admin_products,
    list_applications,
    upsert_admin_product,
)
from apps.common.business_day import store_today
from config.responses import service_response


class AdminProductListView(APIView):
    """Listar pide `products.view`; crear y editar siguen en el detalle."""

    permission_classes = [HasRolePermission]
    required_permission = "products.view"

    def get(self, request):
        return Response(
            list_admin_products(
                can_view_costs=has_role_permission(request.user, "costs.view"),
            )
        )


class AdminProductExportView(APIView):
    """ZIP del catálogo para cargarlo en otro servidor con `import_catalog`.
    Pide lo mismo que el listado: `products.view`, y los costos solo con
    `costs.view`."""

    permission_classes = [HasRolePermission]
    required_permission = "products.view"

    def get(self, request):
        content = build_catalog_export(
            can_view_costs=has_role_permission(request.user, "costs.view"),
        )
        response = HttpResponse(content, content_type="application/zip")
        response["Content-Disposition"] = (
            f'attachment; filename="{export_filename(store_today())}"'
        )
        response["Cache-Control"] = "no-store"
        return response


class AdminProductDetailView(APIView):
    """`products.edit` cubre crear, editar y activar o desactivar; precios y
    costos exigen además `pricing.edit`, y los costos se ven con `costs.view`."""

    permission_classes = [HasRolePermission]
    required_permission = "products.edit"

    def put(self, request, product_id):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(
            upsert_admin_product(
                product_id,
                body,
                request.user.email,
                can_edit_pricing=has_role_permission(request.user, "pricing.edit"),
                can_view_costs=has_role_permission(request.user, "costs.view"),
            )
        )

    def delete(self, request, product_id):
        return service_response(deactivate_admin_product(product_id, request.user.email))


class AdminApplicationListView(APIView):
    """Aplicaciones para el selector de vehículos compatibles del editor. El
    panel no lee `/api/applications/` (storefront): pide `products.view`."""

    permission_classes = [HasRolePermission]
    required_permission = "products.view"

    def get(self, request):
        return Response(list_applications())
