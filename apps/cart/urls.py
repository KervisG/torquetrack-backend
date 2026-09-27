from django.urls import path

from apps.cart.views import AdminCartsView, CartView

urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("admin/carts/", AdminCartsView.as_view(), name="admin-carts"),
]
