from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.catalog.views import (
    AdminApplicationListView,
    AdminProductDetailView,
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
    path(
        "admin/products/<str:product_id>/",
        AdminProductDetailView.as_view(),
        name="admin-product-detail",
    ),
]
