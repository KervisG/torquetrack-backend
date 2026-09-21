from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.catalog.admin_views import AdminProductDetailView
from apps.catalog.views import ApplicationPublicViewSet, ProductPublicViewSet

router = SimpleRouter(trailing_slash=True)
router.register("products", ProductPublicViewSet, basename="product")
router.register("applications", ApplicationPublicViewSet, basename="application")

urlpatterns = router.urls + [
    path(
        "admin/products/<str:product_id>/",
        AdminProductDetailView.as_view(),
        name="admin-product-detail",
    ),
]
