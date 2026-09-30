from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

# Cada app declara sus paths sin prefijo; el prefijo `api/` se pone una sola vez abajo.
api_urlpatterns = [
    path("", include("apps.catalog.urls")),
    path("", include("apps.fitment.urls")),
    path("", include("apps.vin.urls")),
    path("", include("apps.cart.urls")),
    path("", include("apps.checkout.urls")),
    path("", include("apps.quotes.urls")),
    path("", include("apps.shipping.urls")),
    path("", include("apps.tax.urls")),
    path("", include("apps.audit.urls")),
    path("", include("apps.dashboard.urls")),
    path("", include("apps.authentication.urls")),
    path("", include("apps.authorization.urls")),
    path("", include("apps.customers.urls")),
    path("", include("apps.health.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
]

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/", include(api_urlpatterns)),
]
