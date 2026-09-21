from django.urls import path

from apps.shipping.views import ShippingRatesView

urlpatterns = [
    path("shipping/rates/", ShippingRatesView.as_view(), name="shipping-rates"),
]
