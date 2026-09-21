from django.urls import path

from apps.cart.views import AdminCartsView, CartSyncView

urlpatterns = [
    path("cart/sync/", CartSyncView.as_view(), name="cart-sync"),
    path("admin/carts/", AdminCartsView.as_view(), name="admin-carts"),
]
