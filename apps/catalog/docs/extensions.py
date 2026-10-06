"""Extensiones de drf-spectacular de `apps.catalog`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from apps.authorization.docs.schemas import ErrorResponseSerializer, OkResponseSerializer
from apps.catalog.docs.schemas import AdminProductWriteSerializer, CatalogRecordSerializer


class ProductPublicViewSetExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.storefront.ProductPublicViewSet"

    def view_replacement(self):
        @extend_schema_view(
            list=extend_schema(
                operation_id="catalog_products_list",
                tags=["catalog"],
                responses={200: OpenApiResponse(CatalogRecordSerializer(many=True))},
            ),
            retrieve=extend_schema(
                operation_id="catalog_product_retrieve",
                tags=["catalog"],
                description=(
                    "Active product by `id` or by `slug` (`/api/products/<id-or-slug>/`). "
                    "The id is matched first so old id URLs keep working."
                ),
                parameters=[
                    OpenApiParameter(
                        "id", str, OpenApiParameter.PATH, description="Product id or slug."
                    )
                ],
                responses={
                    200: OpenApiResponse(CatalogRecordSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                },
            ),
        )
        class ProductPublicViewSet(self.target_class):
            pass

        return ProductPublicViewSet


class ApplicationPublicViewSetExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.storefront.ApplicationPublicViewSet"

    def view_replacement(self):
        @extend_schema_view(
            list=extend_schema(operation_id="catalog_applications_list", tags=["catalog"]),
            retrieve=extend_schema(operation_id="catalog_application_retrieve", tags=["catalog"]),
        )
        class ApplicationPublicViewSet(self.target_class):
            pass

        return ApplicationPublicViewSet


class AdminProductListViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminProductListView"

    def view_replacement(self):
        class AdminProductListView(self.target_class):
            @extend_schema(
                operation_id="admin_products_list",
                tags=["admin: products"],
                summary="List products",
                description="Requires `products.view`. Costs are included only with `costs.view`.",
                responses={
                    200: OpenApiResponse(CatalogRecordSerializer(many=True)),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminProductListView


class AdminApplicationListViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminApplicationListView"

    def view_replacement(self):
        class AdminApplicationListView(self.target_class):
            @extend_schema(
                operation_id="admin_applications_list",
                tags=["admin: products"],
                summary="List vehicle applications",
                description=(
                    "Requires `products.view`. Options for a product's compatible vehicles; "
                    "`id` is the application code used in `applicationIds`."
                ),
                responses={
                    200: OpenApiResponse(CatalogRecordSerializer(many=True)),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminApplicationListView


class AdminProductDetailViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminProductDetailView"

    def view_replacement(self):
        class AdminProductDetailView(self.target_class):
            @extend_schema(
                operation_id="admin_product_save",
                tags=["admin: products"],
                summary="Create or replace a product",
                description=(
                    "Requires `products.edit`. Changing `price` also requires `pricing.edit`."
                ),
                parameters=[
                    OpenApiParameter("product_id", str, OpenApiParameter.PATH)
                ],
                request=AdminProductWriteSerializer,
                responses={
                    200: OpenApiResponse(CatalogRecordSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def put(self, request, product_id):
                return super().put(request, product_id)

            @extend_schema(
                operation_id="admin_product_deactivate",
                tags=["admin: products"],
                summary="Deactivate a product",
                description="Requires `products.edit`. The product stays in the database.",
                parameters=[
                    OpenApiParameter("product_id", str, OpenApiParameter.PATH)
                ],
                responses={
                    200: OpenApiResponse(OkResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def delete(self, request, product_id):
                return super().delete(request, product_id)

        return AdminProductDetailView


class SitemapViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.sitemap.SitemapView"

    def view_replacement(self):
        class SitemapView(self.target_class):
            @extend_schema(
                operation_id="catalog_sitemap",
                tags=["catalog"],
                summary="Storefront sitemap",
                description=(
                    "Public, no throttle. sitemaps.org XML with the storefront home, quote "
                    "and policy pages and every active product as `{APP_URL}/product/<slug>` "
                    "with `lastmod`. URLs point at the SPA (`APP_URL`), not at the API host."
                ),
                responses={(200, "application/xml"): OpenApiResponse(str)},
            )
            def get(self, request):
                return super().get(request)

        return SitemapView
