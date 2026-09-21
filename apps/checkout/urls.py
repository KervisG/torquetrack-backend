from django.urls import path

from apps.checkout.views import CheckoutView

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
]
