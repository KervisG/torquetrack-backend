"""Extensiones de drf-spectacular de `apps.catalog`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from apps.authorization.docs.schemas import ErrorResponseSerializer, OkResponseSerializer
from apps.catalog.docs.schemas import (
    AdminBrandActiveSerializer,
    AdminBrandCreateSerializer,
    AdminBrandLogoUploadSerializer,
    AdminBrandResponseSerializer,
    AdminBrandSerializer,
    AdminProductWriteSerializer,
    CatalogRecordSerializer,
    ProductGallerySerializer,
    ProductImageOrderSerializer,
    ProductImageUploadSerializer,
    ProductPageSerializer,
)


class ProductPublicViewSetExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.storefront.ProductPublicViewSet"

    def view_replacement(self):
        @extend_schema_view(
            list=extend_schema(
                operation_id="catalog_products_list",
                tags=["catalog"],
                description=(
                    "One page of active products, searched, filtered and sorted by the "
                    "server, with the filter options (`facets`) of the whole catalog."
                ),
                parameters=[
                    OpenApiParameter("q", str, description="Text or part number."),
                    OpenApiParameter("brand", str, description="Part manufacturer."),
                    OpenApiParameter("category", str),
                    OpenApiParameter("condition", str),
                    OpenApiParameter("min", str, description="Minimum price."),
                    OpenApiParameter("max", str, description="Maximum price."),
                    OpenApiParameter("sort", str, enum=["low", "high"]),
                    OpenApiParameter("page", int),
                    OpenApiParameter("pageSize", int, description="Default 16, up to 100."),
                    OpenApiParameter(
                        "ids", str, description="Comma-separated product ids; no `facets`."
                    ),
                    OpenApiParameter("applicationId", str, description="Vehicle application."),
                    OpenApiParameter("vehicleYear", str),
                    OpenApiParameter("vehicleMake", str),
                    OpenApiParameter("vehicleModel", str),
                    OpenApiParameter("vehicleEngine", str),
                    OpenApiParameter(
                        "overview",
                        str,
                        description="Any value adds `overview`: counts by category and make.",
                    ),
                ],
                responses={200: OpenApiResponse(ProductPageSerializer)},
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


class AdminProductExportViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminProductExportView"

    def view_replacement(self):
        class AdminProductExportView(self.target_class):
            @extend_schema(
                operation_id="admin_products_export",
                tags=["admin: products"],
                summary="Export the catalog as a ZIP",
                description=(
                    "Requires `products.view`. ZIP attachment "
                    "(`torquetrack-catalog-<YYYY-MM-DD>.zip`) with `products.json` (active and "
                    "inactive, with `active` and `applicationIds`), `applications.json`, "
                    "`image/<file>` for every local `/static/image/...` image and "
                    "`missing-images.txt` when a local image is not found. Both JSON files load "
                    "back with `import_catalog --products ... --applications ...`. Cost and "
                    "supplier fields are included only with `costs.view`."
                ),
                responses={
                    (200, "application/zip"): OpenApiResponse(
                        bytes, description="Catalog ZIP attachment."
                    ),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminProductExportView


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


class AdminProductImagesViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminProductImagesView"

    def view_replacement(self):
        class AdminProductImagesView(self.target_class):
            @extend_schema(
                operation_id="admin_product_image_upload",
                tags=["admin: products"],
                summary="Upload a product photo",
                description=(
                    "Requires `products.edit`. Multipart body. The photo is stored as WebP, "
                    "scaled to 1600 px at most. The first photo becomes the cover (`image`). "
                    "Up to 12 photos per product."
                ),
                parameters=[OpenApiParameter("product_id", str, OpenApiParameter.PATH)],
                request={"multipart/form-data": ProductImageUploadSerializer},
                responses={
                    201: OpenApiResponse(ProductGallerySerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                    502: OpenApiResponse(ErrorResponseSerializer),
                    503: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request, product_id):
                return super().post(request, product_id)

            @extend_schema(
                operation_id="admin_product_images_reorder",
                tags=["admin: products"],
                summary="Reorder the product photos",
                description="Requires `products.edit`. The first id becomes the cover.",
                parameters=[OpenApiParameter("product_id", str, OpenApiParameter.PATH)],
                request=ProductImageOrderSerializer,
                responses={
                    200: OpenApiResponse(ProductGallerySerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def patch(self, request, product_id):
                return super().patch(request, product_id)

        return AdminProductImagesView


class AdminProductImageDetailViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminProductImageDetailView"

    def view_replacement(self):
        class AdminProductImageDetailView(self.target_class):
            @extend_schema(
                operation_id="admin_product_image_delete",
                tags=["admin: products"],
                summary="Delete a product photo",
                description=(
                    "Requires `products.edit`. If it was the cover, the next photo takes over."
                ),
                parameters=[
                    OpenApiParameter("product_id", str, OpenApiParameter.PATH),
                    OpenApiParameter("image_id", int, OpenApiParameter.PATH),
                ],
                responses={
                    200: OpenApiResponse(ProductGallerySerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def delete(self, request, product_id, image_id):
                return super().delete(request, product_id, image_id)

        return AdminProductImageDetailView


class AdminBrandListViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminBrandListView"

    def view_replacement(self):
        class AdminBrandListView(self.target_class):
            @extend_schema(
                operation_id="admin_brands_list",
                tags=["admin: products"],
                summary="List brands",
                description=(
                    "Requires `products.view`. A brand is the name products carry in "
                    "`manufacturer`; `Alliant Power / Bosch` counts for both brands."
                ),
                responses={
                    200: OpenApiResponse(AdminBrandSerializer(many=True)),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

            @extend_schema(
                operation_id="admin_brand_create",
                tags=["admin: products"],
                summary="Create a brand",
                description=(
                    "Requires `products.edit`. Saving a product also creates the brands "
                    "of its `manufacturer` that do not exist yet."
                ),
                request=AdminBrandCreateSerializer,
                responses={
                    201: OpenApiResponse(AdminBrandResponseSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request):
                return super().post(request)

        return AdminBrandListView


class AdminBrandDetailViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminBrandDetailView"

    def view_replacement(self):
        class AdminBrandDetailView(self.target_class):
            @extend_schema(
                operation_id="admin_brand_set_active",
                tags=["admin: products"],
                summary="Activate or deactivate a brand",
                description=(
                    "Requires `products.edit`. Sets `active` on the brand and on every "
                    "product that carries it, including products shared with another brand."
                ),
                parameters=[OpenApiParameter("brand_id", int, OpenApiParameter.PATH)],
                request=AdminBrandActiveSerializer,
                responses={
                    200: OpenApiResponse(AdminBrandResponseSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def patch(self, request, brand_id):
                return super().patch(request, brand_id)

        return AdminBrandDetailView


class AdminBrandLogoViewExtension(OpenApiViewExtension):
    target_class = "apps.catalog.views.admin.AdminBrandLogoView"

    def view_replacement(self):
        class AdminBrandLogoView(self.target_class):
            @extend_schema(
                operation_id="admin_brand_logo_upload",
                tags=["admin: products"],
                summary="Upload the brand logo",
                description=(
                    "Requires `products.edit`. Multipart body. The logo is stored as WebP, "
                    "scaled to 400 px at most, and replaces the previous one."
                ),
                parameters=[OpenApiParameter("brand_id", int, OpenApiParameter.PATH)],
                request={"multipart/form-data": AdminBrandLogoUploadSerializer},
                responses={
                    200: OpenApiResponse(AdminBrandResponseSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                    502: OpenApiResponse(ErrorResponseSerializer),
                    503: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request, brand_id):
                return super().post(request, brand_id)

            @extend_schema(
                operation_id="admin_brand_logo_delete",
                tags=["admin: products"],
                summary="Remove the brand logo",
                description="Requires `products.edit`.",
                parameters=[OpenApiParameter("brand_id", int, OpenApiParameter.PATH)],
                responses={
                    200: OpenApiResponse(AdminBrandResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def delete(self, request, brand_id):
                return super().delete(request, brand_id)

        return AdminBrandLogoView


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
