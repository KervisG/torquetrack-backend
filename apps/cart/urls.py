from django.urls import path

from apps.cart.views import CartSyncView

urlpatterns = [
    path("cart/sync/", CartSyncView.as_view(), name="cart-sync"),
]
