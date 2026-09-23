from django.contrib import admin
from django.urls import include, path

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
    path("api/", include("apps.auth.urls")),
    path("api/", include("apps.customers.urls")),
]
