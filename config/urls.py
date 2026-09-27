from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.catalog.urls")),
    path("api/", include("apps.fitment.urls")),
    path("api/", include("apps.vin.urls")),
    path("api/", include("apps.cart.urls")),
    path("api/", include("apps.checkout.urls")),
    path("api/", include("apps.quotes.urls")),
    path("api/", include("apps.shipping.urls")),
    path("api/", include("apps.tax.urls")),
    path("api/", include("apps.audit.urls")),
    path("api/", include("apps.dashboard.urls")),
    path("api/", include("apps.authentication.urls")),
    path("api/", include("apps.authorization.urls")),
    path("api/", include("apps.customers.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
]
