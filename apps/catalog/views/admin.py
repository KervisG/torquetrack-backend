from django.http import HttpResponse
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import HasRolePermission, has_role_permission
from apps.catalog.services import (
    build_catalog_export,
    create_admin_brand,
    create_admin_category,
    delete_admin_product,
    export_filename,
    list_admin_brands,
    list_admin_categories,
    list_admin_products,
    list_applications,
    remove_admin_brand_logo,
    set_admin_brand_active,
    set_admin_brand_logo,
    set_admin_category_line,
    set_admin_product_active,
    upsert_admin_product,
)
from apps.catalog.services.images import (
    add_product_image,
    delete_product_image,
    reorder_product_images,
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
        response["Content-Disposition"] = f'attachment; filename="{export_filename(store_today())}"'
        response["Cache-Control"] = "no-store"
        return response


class AdminProductDetailView(APIView):
    """`products.edit` cubre crear, editar, suspender o reactivar (PATCH) y
    borrar (DELETE); precios y costos exigen además `pricing.edit`, y los
    costos se ven con `costs.view`."""

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

    def patch(self, request, product_id):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(set_admin_product_active(product_id, body, request.user.email))

    def delete(self, request, product_id):
        return service_response(delete_admin_product(product_id, request.user.email))


class AdminApplicationListView(APIView):
    """Aplicaciones para el selector de vehículos compatibles del editor. El
    panel no lee `/api/applications/` (storefront): pide `products.view`."""

    permission_classes = [HasRolePermission]
    required_permission = "products.view"

    def get(self, request):
        return Response(list_applications())


class AdminProductImagesView(APIView):
    """Subir una foto (multipart, campo `file`) y reordenar la galería."""

    permission_classes = [HasRolePermission]
    required_permission = "products.edit"
    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request, product_id):
        return service_response(
            add_product_image(
                product_id,
                request.FILES.get("file"),
                request.data.get("alt"),
                request.user.email,
            )
        )

    def patch(self, request, product_id):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(reorder_product_images(product_id, body.get("order")))


class AdminProductImageDetailView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "products.edit"

    def delete(self, request, product_id, image_id):
        return service_response(delete_product_image(product_id, image_id, request.user.email))


class AdminBrandListView(APIView):
    """Listar pide `products.view`; crear una marca, `products.edit`."""

    permission_classes = [HasRolePermission]

    @property
    def required_permission(self):
        return "products.edit" if self.request.method == "POST" else "products.view"

    def get(self, request):
        return Response(list_admin_brands())

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(create_admin_brand(body, request.user.email))


class AdminBrandDetailView(APIView):
    """Activar o desactivar una marca, con todos los productos que la llevan."""

    permission_classes = [HasRolePermission]
    required_permission = "products.edit"

    def patch(self, request, brand_id):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(set_admin_brand_active(brand_id, body, request.user.email))


class AdminBrandLogoView(APIView):
    """Subir (multipart, campo `file`) o quitar el logo de la marca."""

    permission_classes = [HasRolePermission]
    required_permission = "products.edit"
    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request, brand_id):
        return service_response(
            set_admin_brand_logo(brand_id, request.FILES.get("file"), request.user.email)
        )

    def delete(self, request, brand_id):
        return service_response(remove_admin_brand_logo(brand_id, request.user.email))


class AdminCategoryListView(APIView):
    """Listar pide `products.view`; crear una categoría, `products.edit`."""

    permission_classes = [HasRolePermission]

    @property
    def required_permission(self):
        return "products.edit" if self.request.method == "POST" else "products.view"

    def get(self, request):
        return Response(list_admin_categories())

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(create_admin_category(body, request.user.email))


class AdminCategoryDetailView(APIView):
    """Mover una categoría a otra línea de la portada."""

    permission_classes = [HasRolePermission]
    required_permission = "products.edit"

    def patch(self, request, category_id):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(set_admin_category_line(category_id, body, request.user.email))
