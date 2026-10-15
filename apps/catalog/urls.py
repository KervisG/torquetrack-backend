from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.catalog.views import (
    AdminApplicationListView,
    AdminBrandDetailView,
    AdminBrandListView,
    AdminBrandLogoView,
    AdminCategoryDetailView,
    AdminCategoryListView,
    AdminProductDetailView,
    AdminProductExportView,
    AdminProductImageDetailView,
    AdminProductImagesView,
    AdminProductListView,
    ApplicationPublicViewSet,
    ProductPublicViewSet,
    SitemapView,
)

router = SimpleRouter(trailing_slash=True)
router.register("products", ProductPublicViewSet, basename="product")
router.register("applications", ApplicationPublicViewSet, basename="application")

urlpatterns = router.urls + [
    # Sin slash final: es el nombre de archivo que piden los buscadores.
    path("sitemap.xml", SitemapView.as_view(), name="sitemap"),
    path("admin/products/", AdminProductListView.as_view(), name="admin-products"),
    path(
        "admin/applications/",
        AdminApplicationListView.as_view(),
        name="admin-applications",
    ),
    path("admin/brands/", AdminBrandListView.as_view(), name="admin-brands"),
    path(
        "admin/brands/<int:brand_id>/",
        AdminBrandDetailView.as_view(),
        name="admin-brand-detail",
    ),
    path(
        "admin/brands/<int:brand_id>/logo/",
        AdminBrandLogoView.as_view(),
        name="admin-brand-logo",
    ),
    path("admin/categories/", AdminCategoryListView.as_view(), name="admin-categories"),
    path(
        "admin/categories/<int:category_id>/",
        AdminCategoryDetailView.as_view(),
        name="admin-category-detail",
    ),
    # Antes del detalle: si no, `export` se tomaría como un `product_id`.
    path(
        "admin/products/export/",
        AdminProductExportView.as_view(),
        name="admin-products-export",
    ),
    path(
        "admin/products/<str:product_id>/",
        AdminProductDetailView.as_view(),
        name="admin-product-detail",
    ),
    path(
        "admin/products/<str:product_id>/images/",
        AdminProductImagesView.as_view(),
        name="admin-product-images",
    ),
    path(
        "admin/products/<str:product_id>/images/<int:image_id>/",
        AdminProductImageDetailView.as_view(),
        name="admin-product-image-detail",
    ),
]
