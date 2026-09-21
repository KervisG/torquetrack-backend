from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Route prefix mirrors the frozen Next.js app's `/api/**` paths so the
    # eventual reverse-proxy split (design decision #1) needs no path
    # rewriting — only a routing-rule flip per slice.
    path("api/", include("apps.catalog.urls")),
    path("api/", include("apps.fitment.urls")),
    path("api/", include("apps.vin.urls")),
    path("api/", include("apps.cart.urls")),
    path("api/", include("apps.checkout.urls")),
    path("api/", include("apps.quotes.urls")),
    path("api/", include("apps.shipping.urls")),
    path("api/", include("apps.tax.urls")),
    path("api/", include("apps.backoffice.urls")),
    path("api/", include("apps.accounts.urls")),
]
